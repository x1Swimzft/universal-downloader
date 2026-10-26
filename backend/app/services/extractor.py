import asyncio
import uuid
import os
import re
import socket
import ipaddress
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin
from typing import Dict, Any, Optional, List
import httpx

USER_EXTRACTOR_DIR = Path(
    os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
) / "UniversalDownloader" / "bin"

# Prefer a user-installed yt-dlp wheel over the bundled copy, including in a
# frozen backend where PyInstaller's importer would otherwise win.
if (USER_EXTRACTOR_DIR / "yt_dlp" / "__init__.py").is_file():
    from importlib.machinery import PathFinder

    class _UserYtDlpFinder:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "yt_dlp" or fullname.startswith("yt_dlp."):
                return PathFinder.find_spec(
                    fullname, path if path is not None else [str(USER_EXTRACTOR_DIR)]
                )
            return None

    sys.meta_path.insert(0, _UserYtDlpFinder())

import yt_dlp
from yt_dlp.utils import download_range_func

from app.models.schemas import MediaInfo, FormatOption


BROWSER_CHOICES = ("none", "chrome", "edge", "brave", "firefox")
PRESET_CHOICES = ("edit_ready", "audio_norm", "audio_lossless", "social_bypass")
MAX_COOKIE_FILE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024
TIKTOK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

_cookie_preferences: Dict[str, Optional[str]] = {
    "cookies_from_browser": "none",
    "cookies_file": None,
}


def is_private_or_loopback_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or not ip.is_global
        )
    except ValueError:
        return False


def validate_url_not_private(url_str: str) -> bool:
    """Ensure URL is not pointing to private/loopback/link-local addresses."""
    if not url_str or not isinstance(url_str, str):
        return False
    try:
        clean = url_str.strip()
        parsed = urlparse(clean)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False

        # Check explicit loopback hostnames
        if hostname.lower() in ("localhost", "localhost.", "127.0.0.1", "::1"):
            return False

        # If it's an IP literal
        try:
            ip = ipaddress.ip_address(hostname)
            return not is_private_or_loopback_ip(str(ip))
        except ValueError:
            pass

        # Resolve via DNS
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_addr = sockaddr[0]
            if is_private_or_loopback_ip(ip_addr):
                return False
        return True
    except Exception:
        return False


def _validated_cookie_file(path: Optional[str]) -> Optional[str]:
    """Return a real cookies.txt path or raise. Empty string clears the setting."""
    if path is None:
        return None
    cleaned = str(path).strip()
    if not cleaned:
        return None
    if cleaned.startswith(("\\\\", "//")):
        raise ValueError("Cookies file must be on a local drive")
    if not os.path.isabs(cleaned):
        raise ValueError("Cookies file must be an absolute path")
    if os.path.splitext(cleaned)[1].lower() != ".txt":
        raise ValueError("Cookies file must be a .txt file")
    real = os.path.realpath(cleaned)
    if not os.path.isfile(real):
        raise ValueError("Cookies file does not exist")
    if os.path.getsize(real) <= 0 or os.path.getsize(real) > MAX_COOKIE_FILE_BYTES:
        raise ValueError("Cookies file is empty or larger than 5 MB")
    return real


def set_cookie_preferences(
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    if cookies_from_browser is not None:
        browser = str(cookies_from_browser).strip().lower()
        if browser not in BROWSER_CHOICES:
            raise ValueError("Invalid browser cookie source")
        _cookie_preferences["cookies_from_browser"] = browser
    if cookies_file is not None:
        _cookie_preferences["cookies_file"] = _validated_cookie_file(cookies_file)
    return get_cookie_preferences()


def get_cookie_preferences() -> Dict[str, Optional[str]]:
    return dict(_cookie_preferences)


_TIMESTAMP_RE = re.compile(r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\s*$")
_SECONDS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")


def parse_timestamp(value: Optional[Any]) -> Optional[float]:
    """Parse MM:SS, HH:MM:SS, or raw seconds into a non-negative number."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid timestamp")
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value)
        match = _TIMESTAMP_RE.match(text)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2))
            secs = int(match.group(3))
            fraction = match.group(4) or "0"
            if minutes > 59 or secs > 59:
                raise ValueError("Timestamp minutes and seconds must be below 60")
            seconds = hours * 3600 + minutes * 60 + secs + int(fraction.ljust(3, "0")) / 1000
        else:
            match = _SECONDS_RE.match(text)
            if not match:
                raise ValueError("Use MM:SS or HH:MM:SS for timestamps")
            seconds = float(match.group(1))
    if seconds < 0 or seconds > 86400:
        raise ValueError("Timestamp must be between 0:00 and 24:00:00")
    return round(seconds, 3)


def validate_clip_range(
    start_time: Optional[Any], end_time: Optional[Any]
) -> tuple[Optional[float], Optional[float]]:
    start = parse_timestamp(start_time)
    end = parse_timestamp(end_time)
    if start is None and end is None:
        return None, None
    if start is not None and end is not None and start >= end:
        raise ValueError("Start time must be before end time")
    return start, end


def _normalize_preset(preset: Optional[str], social_bypass: bool = False) -> Optional[str]:
    if social_bypass:
        return "social_bypass"
    if preset in (None, "", "none"):
        return None
    if preset not in PRESET_CHOICES:
        raise ValueError("Unknown edit preset")
    return str(preset)


def _preset_output_ext(preset: str) -> str:
    return {
        "edit_ready": ".mp4",
        "audio_norm": ".m4a",
        "audio_lossless": ".flac",
        "social_bypass": ".mp4",
    }[preset]


def _preset_ffmpeg_args(preset: str, src: str, dst: str) -> List[str]:
    """Arguments after the ffmpeg executable. Kept pure so it is unit-testable."""
    if preset == "edit_ready":
        opts = [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
        ]
    elif preset == "audio_norm":
        opts = [
            "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:a", "aac", "-b:a", "192k",
        ]
    elif preset == "audio_lossless":
        opts = ["-vn", "-c:a", "flac"]
    elif preset == "social_bypass":
        opts = [
            "-vf", "fps=30", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-map_metadata", "-1",
        ]
    else:
        raise ValueError("Unknown edit preset")
    return ["-y", "-i", src, *opts, dst]


def _ffmpeg_executable() -> str:
    found = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
    if not found:
        raise ValueError("FFmpeg was not found. Reinstall the app or add FFmpeg to PATH.")
    return found


def _postprocess_file(path: str, preset: str) -> str:
    final_path = os.path.splitext(path)[0] + _preset_output_ext(preset)
    temp_path = f"{path}.preset{_preset_output_ext(preset)}"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [_ffmpeg_executable(), *_preset_ffmpeg_args(preset, path, temp_path)],
            capture_output=True,
            text=True,
            timeout=900,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("FFmpeg post-processing timed out") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise ValueError(f"FFmpeg post-processing failed: {detail[-1] if detail else 'unknown error'}")
    if not os.path.isfile(temp_path):
        raise ValueError("FFmpeg did not produce an output file")
    os.replace(temp_path, final_path)
    if os.path.abspath(path) != os.path.abspath(final_path):
        try:
            os.remove(path)
        except OSError:
            pass
    return final_path


def _clean_url(url: str) -> str:
    """Normalize and clean URL for reliable extraction across all platforms."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        # Handle YouTube URLs
        if "youtube.com" in netloc or "youtu.be" in netloc:
            if "youtu.be" in netloc:
                video_id = parsed.path.strip("/").split("/")[0]
                if video_id:
                    return f"https://www.youtube.com/watch?v={video_id}"
            elif "/shorts/" in parsed.path:
                short_id = parsed.path.split("/shorts/")[1].strip("/").split("/")[0].split("?")[0]
                if short_id:
                    return f"https://www.youtube.com/watch?v={short_id}"
            else:
                query_params = parse_qs(parsed.query)
                if "v" in query_params:
                    clean_query = urlencode({"v": query_params["v"][0]})
                    return f"https://www.youtube.com/watch?{clean_query}"
        # Handle TikTok photo/slideshow URLs -> map to /video/ so extractor matches
        if "tiktok.com" in netloc and "/photo/" in parsed.path:
            clean_path = parsed.path.replace("/photo/", "/video/")
            return urlunparse(parsed._replace(path=clean_path))
        # Instagram: drop img_index / igsh / utm_* so the whole post is inspected
        if "instagram.com" in netloc:
            return urlunparse(parsed._replace(query="", fragment=""))
    except Exception:
        pass

    return url


def _friendly_error(msg: str, url: str) -> Optional[str]:
    """Map known raw yt-dlp failures to a message an end user can act on."""
    if "instagram.com" in url and (
        "No video formats found" in msg or "There is no video in this post" in msg
    ):
        return "This Instagram post only contains photos (no video found), or requires logging in."
    if "tiktok.com" in url and "HTTP Error 403" in msg:
        return "TikTok blocked this request (HTTP 403). Your network or region may be blocked - try another network or VPN."
    return None


def _extract_platform(url: str) -> str:
    """Detect platform from URL."""
    patterns = {
        "youtube": r"(youtube\.com|youtu\.be)",
        "tiktok": r"tiktok\.com",
        "instagram": r"instagram\.com",
        "twitter": r"(twitter\.com|x\.com)",
        "facebook": r"(facebook\.com|fb\.watch)",
        "soundcloud": r"soundcloud\.com",
        "bilibili": r"bilibili\.com",
        "reddit": r"reddit\.com",
        "vimeo": r"vimeo\.com",
    }
    for name, pattern in patterns.items():
        if re.search(pattern, url, re.IGNORECASE):
            return name
    return "media"


def _is_photo_url(url: str) -> bool:
    lower = url.lower()
    return (
        "instagram.com/" in lower and ("/p/" in lower or "/reel/" in lower)
    ) or ("tiktok.com" in lower and "/photo/" in lower)


def _best_thumbnail_url(info: Dict[str, Any]) -> Optional[str]:
    candidates = [
        item
        for item in (info.get("thumbnails") or [])
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    ]
    if candidates:
        best = max(
            candidates,
            key=lambda item: (item.get("width") or 0) * (item.get("height") or 0),
        )
        return best["url"]
    thumb = info.get("thumbnail")
    return thumb if isinstance(thumb, str) and thumb else None


def _collect_images(info: Dict[str, Any]) -> List[str]:
    """Collect image URLs from a single photo post or an image-only carousel."""
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if isinstance(e, dict)]
        # Mixed carousels contain videos; keep the normal video pipeline.
        if any(entry.get("formats") for entry in entries):
            return []
        images = [u for entry in entries if (u := _best_thumbnail_url(entry))]
        return list(dict.fromkeys(images))
    if info.get("formats"):
        return []
    thumb = _best_thumbnail_url(info)
    return [thumb] if thumb else []


def _find_key(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def _parse_tiktok_photo_html(html: str) -> tuple[List[str], Optional[str]]:
    """Extract slideshow image URLs from TikTok's hydration JSON."""
    match = re.search(
        r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return [], None
    try:
        data = json.loads(match.group(1))
    except (TypeError, ValueError):
        return [], None

    image_post = _find_key(data, "imagePost")
    if not isinstance(image_post, dict):
        return [], None

    images: List[str] = []
    for item in image_post.get("images") or []:
        if not isinstance(item, dict):
            continue
        urls: List[str] = []
        for holder in ("imageURL", "displayImage"):
            value = item.get(holder)
            if isinstance(value, dict) and isinstance(value.get("urlList"), list):
                urls = [u for u in value["urlList"] if isinstance(u, str) and u.startswith("http")]
                if urls:
                    break
        if urls:
            images.append(urls[0])
    title = _find_key(data, "desc")
    return list(dict.fromkeys(images)), title if isinstance(title, str) else None


async def _fetch_tiktok_photos(url: str) -> tuple[List[str], Optional[str]]:
    headers = {"User-Agent": TIKTOK_UA, "Referer": "https://www.tiktok.com/"}
    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=20.0, follow_redirects=False
        ) as client:
            current = url
            for _ in range(4):
                if not validate_url_not_private(current):
                    return [], None
                resp = await client.get(current)
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return [], None
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    return [], None
                return _parse_tiktok_photo_html(resp.text)
    except Exception:
        return [], None
    return [], None


def _get_base_opts(url: str = "") -> Dict[str, Any]:
    """Base options that bypass bot checks, solve JS challenges, and unlock full HD resolutions."""
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "js_runtimes": {"node": {}},
    }
    cookies_file = _cookie_preferences.get("cookies_file")
    browser = _cookie_preferences.get("cookies_from_browser") or "none"
    if cookies_file:
        opts["cookiefile"] = cookies_file
    elif browser != "none":
        opts["cookiesfrombrowser"] = (browser,)
    return opts


async def extract_info(url: str) -> MediaInfo:
    """Extract metadata without downloading."""
    if not validate_url_not_private(url):
        raise ValueError("Invalid or private URL not allowed")

    if "tiktok.com" in url.lower() and "/photo/" in url.lower():
        images, photo_title = await _fetch_tiktok_photos(url)
        if images:
            return MediaInfo(
                title=photo_title or "TikTok photo",
                thumbnail=images[0],
                platform="tiktok",
                images=images,
                media_type="carousel" if len(images) > 1 else "image",
            )

    clean_url = _clean_url(url)
    ydl_opts = _get_base_opts(clean_url)
    ydl_opts["skip_download"] = True
    ydl_opts["extract_flat"] = False
    if _is_photo_url(url):
        ydl_opts["ignore_no_formats_error"] = True

    loop = asyncio.get_event_loop()

    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(clean_url, download=False)

    try:
        info = await loop.run_in_executor(None, _extract)
    except Exception as e:
        friendly = _friendly_error(str(e), clean_url)
        if friendly:
            raise ValueError(friendly) from e
        raise

    if not isinstance(info, dict):
        raise ValueError("No media information found for this link")

    images = _collect_images(info) if _is_photo_url(url) else []
    if images:
        return MediaInfo(
            title=info.get("title") or "Photo post",
            thumbnail=images[0],
            uploader=info.get("uploader") or info.get("channel") or info.get("creator"),
            platform=_extract_platform(clean_url),
            images=images,
            media_type="carousel" if len(images) > 1 else "image",
        )

    formats: list[FormatOption] = []
    seen_resolutions: set[str] = set()

    for f in info.get("formats", []):
        ext = f.get("ext", "")
        height = f.get("height")
        acodec = f.get("acodec", "none")
        vcodec = f.get("vcodec", "none")

        if vcodec != "none" and height:
            resolution = f"{height}p"
            if resolution not in seen_resolutions:
                seen_resolutions.add(resolution)
                formats.append(
                    FormatOption(
                        format_id=f.get("format_id", ""),
                        ext=ext,
                        resolution=resolution,
                        filesize=f.get("filesize") or f.get("filesize_approx"),
                        note=f.get("format_note", ""),
                    )
                )
        elif vcodec == "none" and acodec != "none":
            formats.append(
                FormatOption(
                    format_id=f.get("format_id", ""),
                    ext=ext,
                    resolution="audio",
                    filesize=f.get("filesize") or f.get("filesize_approx"),
                    note=f"audio {f.get('abr', '')}kbps",
                )
            )

    raw_duration = info.get("duration")
    duration = round(raw_duration) if isinstance(raw_duration, (int, float)) else None

    return MediaInfo(
        title=info.get("title") or "Unknown",
        thumbnail=info.get("thumbnail"),
        duration=duration,
        uploader=info.get("uploader") or info.get("channel") or info.get("creator"),
        platform=_extract_platform(clean_url),
        formats=formats,
        media_type="video",
    )


def _build_ydl_opts(
    fmt: str,
    quality: str,
    output_path: str,
    progress_hook,
    url: str = "",
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
) -> Dict[str, Any]:
    """Build yt-dlp options for the requested format and quality."""
    opts = _get_base_opts(url)
    opts.update(
        {
            "outtmpl": output_path,
            "progress_hooks": [progress_hook],
            "merge_output_format": "mp4" if fmt in ("mp4", "images") else None,
            "postprocessors": [],
        }
    )

    if start_time is not None or end_time is not None:
        opts["download_ranges"] = download_range_func(
            None, [(start_time or 0, end_time if end_time is not None else float("inf"))]
        )
        opts["force_keyframes_at_cuts"] = True

    if fmt in ("mp3", "m4a", "opus"):
        opts["format"] = "bestaudio/best"
        opts["postprocessors"].append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt,
                "preferredquality": quality if fmt == "mp3" else "0",
            }
        )
    else:  # mp4
        height = quality.rstrip("p") if quality else "1080"
        if not height.isdigit():
            height = "1080"
        h = str(height)
        val = int(h)

        if val > 1080:
            # 4K / 2K resolutions: YouTube only provides VP9/AV1. Select genuine >1080p stream first, then fall back
            opts["format"] = (
                f"bestvideo[height>{1080}][height<={h}]+bestaudio[ext=m4a]"
                f"/bestvideo[height>{1080}][height<={h}]+bestaudio"
                f"/bestvideo[height<={h}][vcodec^=avc1]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={h}][vcodec^=avc1]+bestaudio"
                f"/bestvideo[height<={h}]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={h}]+bestaudio"
                f"/best[height<={h}]"
                f"/bestvideo+bestaudio"
                f"/best"
            )
        else:
            # <= 1080p: Prioritize compatible H.264 (avc1) + AAC (m4a), with graceful fallbacks
            opts["format"] = (
                f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={h}][vcodec^=avc1]+bestaudio"
                f"/bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={h}]+bestaudio"
                f"/best[height<={h}]"
                f"/bestvideo+bestaudio"
                f"/best"
            )

    return opts


def _image_extension(url: str, content_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
    }
    clean_type = (content_type or "").split(";")[0].strip().lower()
    if clean_type in mapping:
        return mapping[clean_type]
    suffix = os.path.splitext(urlparse(url).path)[1].lower()
    return ".jpg" if suffix == ".jpeg" else suffix if suffix in (".jpg", ".png", ".webp") else ".jpg"


def _find_output_file(tmp_dir: str, job_id: str) -> str:
    for name in os.listdir(tmp_dir):
        if name.startswith(job_id) and not name.endswith((".part", ".ytdl")):
            return os.path.join(tmp_dir, name)
    raise FileNotFoundError(f"Output file not found for job {job_id}")


async def _download_photo_post(
    original_url: str,
    tmp_dir: str,
    job_store: Dict[str, Any],
    job_id: str,
    cancel_event: Optional[asyncio.Event] = None,
) -> tuple[str, str]:
    info = await extract_info(original_url)
    images = info.images[:MAX_IMAGES]
    if not images:
        raise ValueError("No downloadable photos were found in this post.")

    referer = "https://www.tiktok.com/" if "tiktok.com" in original_url else "https://www.instagram.com/"
    headers = {"User-Agent": TIKTOK_UA, "Referer": referer}
    saved: List[str] = []

    async with httpx.AsyncClient(
        headers=headers, timeout=45.0, follow_redirects=False
    ) as client:
        for index, image_url in enumerate(images):
            if cancel_event and cancel_event.is_set():
                raise yt_dlp.utils.DownloadError("Cancelled by user")
            current = image_url
            for _ in range(4):
                if not validate_url_not_private(current):
                    raise ValueError("Photo URL points to a private or invalid address")
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Photo download redirected without a target")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if not content_type.startswith("image/"):
                        raise ValueError("Photo download returned a non-image response")
                    path = os.path.join(
                        tmp_dir,
                        f"{job_id}_photo_{index + 1:02d}{_image_extension(current, content_type)}",
                    )
                    written = 0
                    with open(path, "wb") as out:
                        async for chunk in response.aiter_bytes(64 * 1024):
                            written += len(chunk)
                            if written > MAX_IMAGE_BYTES:
                                raise ValueError("A photo is larger than the 20 MB limit")
                            out.write(chunk)
                    saved.append(path)
                    break
            else:
                raise ValueError("Too many redirects while downloading a photo")

            if job_id in job_store:
                job_store[job_id]["progress"] = round((index + 1) / len(images) * 99, 1)

    if cancel_event and cancel_event.is_set():
        raise yt_dlp.utils.DownloadError("Cancelled by user")
    if len(saved) == 1:
        return saved[0], info.title
    if not saved:
        raise ValueError("No downloadable photos were found in this post.")

    zip_path = os.path.join(tmp_dir, f"{job_id}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for index, path in enumerate(saved, start=1):
            bundle.write(path, f"photo_{index:02d}{os.path.splitext(path)[1]}")
    for path in saved:
        try:
            os.remove(path)
        except OSError:
            pass
    return zip_path, info.title


async def download_media(
    url: str,
    fmt: str,
    quality: str,
    tmp_dir: str,
    job_store: Dict[str, Any],
    job_id: str,
    cancel_event: Optional[asyncio.Event] = None,
    start_time: Optional[Any] = None,
    end_time: Optional[Any] = None,
    preset: Optional[str] = None,
    social_bypass: bool = False,
) -> tuple[str, str]:
    """Download and convert media. Returns (final file path, title)."""
    if not validate_url_not_private(url):
        raise ValueError("Invalid or private URL not allowed")
    clean_url = _clean_url(url)
    start, end = validate_clip_range(start_time, end_time)
    preset_name = _normalize_preset(preset, social_bypass)

    if fmt == "images" or ("tiktok.com" in url.lower() and "/photo/" in url.lower()):
        return await _download_photo_post(url, tmp_dir, job_store, job_id, cancel_event)

    filename_template = f"{job_id}.%(ext)s"
    output_path = os.path.join(tmp_dir, filename_template)

    def progress_hook(d):
        if cancel_event and cancel_event.is_set():
            raise yt_dlp.utils.DownloadError("Cancelled by user")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100) if total else 0
            speed_bps = d.get("speed") or 0
            if job_id in job_store:
                job_store[job_id]["progress"] = round(pct, 1)
                job_store[job_id]["speed"] = round(speed_bps / (1024 * 1024), 1) if speed_bps else 0.0
        elif d["status"] == "finished":
            if cancel_event and cancel_event.is_set():
                raise yt_dlp.utils.DownloadError("Cancelled by user")
            if job_id in job_store:
                job_store[job_id]["progress"] = 99.0

    ydl_opts = _build_ydl_opts(
        fmt, quality, output_path, progress_hook, clean_url, start, end
    )

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(clean_url, download=True)
            return info_dict.get("title", "download") if info_dict else "download"

    try:
        extracted_title = await loop.run_in_executor(None, _download)
    except Exception as e:
        friendly = _friendly_error(str(e), clean_url)
        if friendly:
            raise ValueError(friendly) from e
        raise

    if cancel_event and cancel_event.is_set():
        raise yt_dlp.utils.DownloadError("Cancelled by user")

    filepath = _find_output_file(tmp_dir, job_id)
    if preset_name:
        filepath = await loop.run_in_executor(None, _postprocess_file, filepath, preset_name)
    return filepath, extracted_title


async def get_direct_stream_url(url: str, height: Optional[str] = None) -> Optional[dict]:
    if not validate_url_not_private(url):
        return None
    clean_url = _clean_url(url)
    ydl_opts = _get_base_opts(clean_url)
    loop = asyncio.get_event_loop()

    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            formats = info.get("formats", [])
            target_h = int(height) if height and str(height).isdigit() else None

            for f in reversed(formats):
                f_height = f.get("height") or 0
                height_match = (target_h is None) or (f_height == target_h)

                if (
                    f.get("ext") == "mp4"
                    and f.get("acodec") not in (None, "none")
                    and f.get("vcodec") not in (None, "none")
                    and height_match
                    and f.get("url")
                ):
                    return {
                        "url": f["url"],
                        "title": info.get("title", "download"),
                        "filesize": f.get("filesize") or f.get("filesize_approx"),
                        "http_headers": f.get("http_headers", {}),
                    }
            return None

    return await loop.run_in_executor(None, _extract)

