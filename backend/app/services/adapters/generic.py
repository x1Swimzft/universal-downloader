"""Generic yt-dlp pipeline helpers and the shared photo-post downloader."""
from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from typing import Any, Dict, List, Optional

import httpx
import yt_dlp
from yt_dlp.utils import download_range_func

from app.models.schemas import FormatOption, MediaInfo

from .common import (
    TIKTOK_UA,
    _cookie_preferences,
    _image_extension,
    _photo_referer,
    _safe_cover_url,
    _validated_cookie_file,
)


def _url_allowed(url: str) -> bool:
    """Compatibility seam: the tests monkeypatch extractor.validate_url_not_private."""
    from app.services import extractor

    return extractor.validate_url_not_private(url)


async def _fetch_pinterest(url: str) -> Optional[Dict[str, Any]]:
    """Compatibility seam: the tests monkeypatch extractor._fetch_pinterest_image."""
    from app.services import extractor

    return await extractor._fetch_pinterest_image(url)


MAX_IMAGES = 30


MAX_IMAGE_BYTES = 20 * 1024 * 1024


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


def _extract_platform(url: str) -> str:
    """Detect platform from URL."""
    patterns = {
        "youtube": r"(youtube\.com|youtu\.be)",
        "tiktok": r"tiktok\.com",
        "instagram": r"instagram\.com",
        "twitter": r"(twitter\.com|\bx\.com)",
        "facebook": r"(facebook\.com|fb\.watch)",
        "soundcloud": r"soundcloud\.com",
        "bilibili": r"bilibili\.com",
        "reddit": r"reddit\.com",
        "vimeo": r"vimeo\.com",
        "spotify": r"spotify\.com",
        "apple": r"music\.apple\.com",
        "twitch": r"twitch\.tv",
        "kick": r"kick\.com",
        "pinterest": r"(pinterest\.[a-z.]+|pin\.it)",
        "bandcamp": r"bandcamp\.com",
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


def _collect_entries(info: Dict[str, Any], limit: int = 100) -> List[dict]:
    """Flatten playlist entries into preview rows, rebuilding bare YouTube IDs."""
    raw_entries = info.get("entries")
    if not isinstance(raw_entries, list):
        return []

    parent_is_youtube = "youtube" in str(
        info.get("extractor_key") or info.get("ie_key") or ""
    ).lower()
    entries: List[dict] = []
    seen: set[str] = set()

    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        value = entry.get("webpage_url") or entry.get("url")
        if not isinstance(value, str) or not value.strip():
            continue
        url = value.strip()
        if not url.lower().startswith(("http://", "https://")):
            entry_extractor = str(
                entry.get("ie_key") or entry.get("extractor_key") or ""
            ).lower()
            if "youtube" in entry_extractor or parent_is_youtube:
                url = f"https://www.youtube.com/watch?v={url}"
            else:
                continue
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)

        title = entry.get("title")
        thumbnail = entry.get("thumbnail")
        raw_duration = entry.get("duration")
        entries.append(
            {
                "url": url,
                "title": title if isinstance(title, str) and title.strip() else "Untitled",
                "duration": raw_duration
                if isinstance(raw_duration, (int, float))
                and not isinstance(raw_duration, bool)
                else None,
                "thumbnail": thumbnail
                if isinstance(thumbnail, str) and thumbnail
                else _best_thumbnail_url(entry),
                "platform": _extract_platform(url),
                "media_type": "video",
            }
        )
        if len(entries) >= limit:
            break

    return entries


_PINTEREST_ORIGINAL_RE = re.compile(r"^(https?://i\.pinimg\.com/)[^/]+/", re.IGNORECASE)


def _upgrade_pinterest_image(url: Optional[str]) -> Optional[str]:
    """Ask Pinterest for the original image instead of the preview size."""
    safe = _safe_cover_url(url)
    if not safe:
        return None
    return _PINTEREST_ORIGINAL_RE.sub(r"\1originals/", safe)


async def _fetch_pinterest_image(
    url: str,
) -> Optional[tuple[Optional[str], Optional[str], bool]]:
    """Return (original image, title, has_video) from a Pinterest pin page."""
    page = await _fetch_public_html(url, referer="https://www.pinterest.com/")
    if not page:
        return None
    title = _meta_content(page, "og:title")
    if _meta_content(page, "og:video") or _meta_content(page, "og:video:url"):
        return None, title, True
    image = _upgrade_pinterest_image(_meta_content(page, "og:image"))
    if not image:
        return None
    return image, title, False


async def _pinterest_image_info(url: str) -> Optional[MediaInfo]:
    result = await _fetch_pinterest(url)
    if not result:
        return None
    image, title, has_video = result
    if has_video or not image:
        return None
    return MediaInfo(
        title=title or "Pinterest pin",
        thumbnail=image,
        platform="pinterest",
        images=[image],
        media_type="image",
    )


def _has_playable_format(info: Dict[str, Any]) -> bool:
    for item in info.get("formats") or []:
        if not isinstance(item, dict):
            continue
        if item.get("vcodec") not in (None, "none") or item.get("acodec") not in (None, "none"):
            return True
    return False


def _is_audio_only(f: Dict[str, Any]) -> bool:
    return f.get("vcodec") == "none" and f.get("acodec") != "none"


def _audio_format(f: Dict[str, Any]) -> FormatOption:
    bitrate = f.get("abr") or f.get("tbr")
    return FormatOption(
        format_id=f.get("format_id", ""),
        ext=f.get("ext", ""),
        resolution="audio",
        filesize=f.get("filesize") or f.get("filesize_approx"),
        note=f"audio {bitrate}kbps" if bitrate else "audio",
    )


def _audio_formats(info: Dict[str, Any]) -> list[FormatOption]:
    return [
        _audio_format(f)
        for f in info.get("formats") or []
        if isinstance(f, dict) and _is_audio_only(f)
    ]


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


def _flat_info(clean_url: str) -> Optional[Dict[str, Any]]:
    opts = _get_base_opts(clean_url)
    opts.update(
        {
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
        }
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(clean_url, download=False)


def _single_entry(info: Dict[str, Any], fallback_url: str) -> dict:
    title = info.get("title")
    raw_duration = info.get("duration")
    url = info.get("webpage_url")
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        url = fallback_url
    return {
        "url": url,
        "title": title if isinstance(title, str) and title.strip() else "Untitled",
        "duration": raw_duration
        if isinstance(raw_duration, (int, float)) and not isinstance(raw_duration, bool)
        else None,
        "thumbnail": _best_thumbnail_url(info),
        "platform": _extract_platform(url),
        "media_type": "video",
    }


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
            "continuedl": True,
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


def _find_output_file(
    tmp_dir: str, job_id: str, preferred_ext: Optional[str] = None
) -> str:
    cover_prefix = f"{job_id}.cover."
    candidates = [
        name
        for name in os.listdir(tmp_dir)
        if name.startswith(job_id)
        and not name.startswith(cover_prefix)
        and not name.endswith((".part", ".ytdl"))
    ]
    if preferred_ext:
        suffix = f".{preferred_ext.lower()}"
        for name in candidates:
            if name.lower().endswith(suffix):
                return os.path.join(tmp_dir, name)
    if candidates:
        return os.path.join(tmp_dir, candidates[0])
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

    referer = _photo_referer(original_url)
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
