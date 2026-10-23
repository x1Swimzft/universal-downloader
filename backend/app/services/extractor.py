import asyncio
import uuid
import os
import re
import socket
import ipaddress
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Dict, Any, Optional
import yt_dlp

from app.models.schemas import MediaInfo, FormatOption


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
    except Exception:
        pass

    return url


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


def _get_base_opts(url: str = "") -> Dict[str, Any]:
    """Base options that bypass bot checks, solve JS challenges, and unlock full HD resolutions."""
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "js_runtimes": {"node": {}},
    }
    return opts


async def extract_info(url: str) -> MediaInfo:
    """Extract metadata without downloading."""
    if not validate_url_not_private(url):
        raise ValueError("Invalid or private URL not allowed")
    clean_url = _clean_url(url)
    ydl_opts = _get_base_opts(clean_url)
    ydl_opts["skip_download"] = True
    ydl_opts["extract_flat"] = False

    loop = asyncio.get_event_loop()

    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(clean_url, download=False)

    info = await loop.run_in_executor(None, _extract)

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
        title=info.get("title", "Unknown"),
        thumbnail=info.get("thumbnail"),
        duration=duration,
        uploader=info.get("uploader") or info.get("channel") or info.get("creator"),
        platform=_extract_platform(clean_url),
        formats=formats,
    )


def _build_ydl_opts(
    fmt: str,
    quality: str,
    output_path: str,
    progress_hook,
    url: str = "",
) -> Dict[str, Any]:
    """Build yt-dlp options for the requested format and quality."""
    opts = _get_base_opts(url)
    opts.update(
        {
            "outtmpl": output_path,
            "progress_hooks": [progress_hook],
            "merge_output_format": "mp4" if fmt == "mp4" else None,
            "postprocessors": [],
        }
    )

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


async def download_media(
    url: str,
    fmt: str,
    quality: str,
    tmp_dir: str,
    job_store: Dict[str, Any],
    job_id: str,
    cancel_event: Optional[asyncio.Event] = None,
) -> tuple[str, str]:
    """Download and convert media. Returns (final file path, title)."""
    if not validate_url_not_private(url):
        raise ValueError("Invalid or private URL not allowed")
    clean_url = _clean_url(url)
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

    ydl_opts = _build_ydl_opts(fmt, quality, output_path, progress_hook, clean_url)

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(clean_url, download=True)
            return info_dict.get("title", "download") if info_dict else "download"

    extracted_title = await loop.run_in_executor(None, _download)

    if cancel_event and cancel_event.is_set():
        raise yt_dlp.utils.DownloadError("Cancelled by user")

    for f in os.listdir(tmp_dir):
        if f.startswith(job_id) and not f.endswith((".part", ".ytdl")):
            return os.path.join(tmp_dir, f), extracted_title

    raise FileNotFoundError(f"Output file not found for job {job_id}")


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

