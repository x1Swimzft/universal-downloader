import asyncio
import uuid
import os
import re
import socket
import ipaddress
import json
import html as html_lib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin, quote
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

from app.models.schemas import MediaInfo, FormatOption, PreviewEntry

from app.services.adapters.common import (
    BROWSER_CHOICES,
    _cookie_preferences,
    _validated_cookie_file,
    get_cookie_preferences,
    set_cookie_preferences,
)

from app.services.adapters.common import _fetch_public_html
from app.services.adapters.generic import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    _audio_formats,
    _best_thumbnail_url,
    _build_ydl_opts,
    _clean_url,
    _collect_entries,
    _collect_images,
    _download_photo_post,
    _extract_platform,
    _fetch_pinterest_image,
    _find_output_file,
    _flat_info,
    _get_base_opts,
    _has_playable_format,
    _is_photo_url,
    _pinterest_image_info,
    _single_entry,
    _upgrade_pinterest_image,
)

from app.services.adapters.instagram import (
    _IG_EMBED_UA,
    _instagram_embed_info,
    _instagram_media_info,
    _instagram_preview_entry,
    _instagram_shortcode,
)

from app.services.adapters.tiktok import (
    _TIKTOK_MOBILE_UA,    _fetch_tiktok_photos,
    _tiktok_fetch_html,
    _parse_tiktok_photo_html,
    _tiktok_photo_info,
)

from app.services.adapters.common import (
    _find_key,
    _json_object_after,
    TIKTOK_UA,
    _get_text,
    _image_extension,
    _meta_content,
    _parse_script_json,
    _photo_referer,
    _safe_cover_url,
    is_private_or_loopback_ip,
    validate_url_not_private,
)
from app.services.adapters.music import (
    MUSIC_TIMEOUT,
    _download_music_cover,
    _embed_music_metadata,
    _music_ffmpeg_args,
    _music_media_info,
    _resolve_spotify,
    is_music_url,
    resolve_music,
)
from app.services.mediaops import (
    AUDIO_FILENAME_TEMPLATES,
    PRESET_CHOICES,
    _ffmpeg_executable,
    _normalize_preset,
    _postprocess_file,
    _preset_ffmpeg_args,
    _preset_output_ext,
    format_audio_filename,
    parse_timestamp,
    sanitize_name,
    validate_clip_range,
)


def _friendly_error(msg: str, url: str) -> Optional[str]:
    """Map known raw yt-dlp failures to a message an end user can act on."""
    if "instagram.com" in url and (
        "No video formats found" in msg or "There is no video in this post" in msg
    ):
        return "This Instagram post only contains photos (no video found), or requires logging in."
    if "tiktok.com" in url and "HTTP Error 403" in msg:
        return "TikTok blocked this request (HTTP 403). Your network or region may be blocked - try another network or VPN."
    return None


_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_ERROR_MESSAGES = {
    "AUTH_403": "403 Forbidden - open Settings and enable Browser Cookies, then retry.",
    "COOKIE_REQUIRED": "Sign-in required - open Settings and enable Browser Cookies, then retry.",
    "COOKIE_LOCKED": "The browser cookie database is locked. Close Chrome/Edge, then retry, or export cookies.txt and select it in Settings.",
    "RATE_LIMIT": "Rate limited by the site - wait a moment, then retry, or enable Browser Cookies in Settings.",
    "NETWORK_TRANSIENT": "Network problem - check your connection, then retry.",
    "UNSUPPORTED_URL": "This link is unsupported or the media is unavailable.",
    "LINK_EXPIRED": "This link has expired - request a fresh link and try again.",
    "PLATFORM_CHANGED": "The site changed its page and this version cannot read it. Update the app, then retry.",
}

_SETTINGS_ACTION_CODES = {"AUTH_403", "COOKIE_REQUIRED", "COOKIE_LOCKED", "RATE_LIMIT"}


def _clean_error_text(message: str) -> str:
    text = _ANSI_RE.sub("", str(message or "")).strip()
    text = re.sub(r"^ERROR:\s*", "", text, flags=re.IGNORECASE)
    # Never leak yt-dlp CLI flags into the UI.
    text = re.sub(r"\s*--cookies(?:-from-browser)?(?:=\S+)?", "", text).strip()
    return text or "Download failed"


def classify_error(message: str, url: str = "") -> str:
    """Map a raw yt-dlp failure to a stable error code for the UI."""
    text = _clean_error_text(message)
    lower = text.lower()
    cookie_lock = any(
        hint in lower
        for hint in (
            "could not copy chrome cookie database",
            "cookie database",
            "cookie db",
        )
    ) or (
        any(hint in lower for hint in ("database is locked", "permission denied"))
        and any(hint in lower for hint in ("cookie", "chrome", "edge", "browser"))
    )
    if cookie_lock:
        return "COOKIE_LOCKED"
    if "403" in text or "forbidden" in lower:
        return "AUTH_403"
    if any(
        hint in lower
        for hint in (
            "sign in",
            "sign-in",
            "login",
            "log in",
            "logging in",
            "login page",
            "login required",
            "cookies",
            "private",
            "age-restricted",
            "age restricted",
            "confirm your age",
            "members-only",
            "requires authentication",
        )
    ):
        return "COOKIE_REQUIRED"
    if "429" in text or "rate limit" in lower or "too many requests" in lower:
        return "RATE_LIMIT"
    if any(
        hint in lower
        for hint in (
            "link has expired",
            "url has expired",
            "link expired",
            "no longer valid",
            "410 gone",
        )
    ):
        return "LINK_EXPIRED"
    if any(
        hint in lower
        for hint in (
            "failed to parse",
            "unable to parse",
            "unexpected response",
            "extractor is out of date",
            "no media data found",
        )
    ):
        return "PLATFORM_CHANGED"
    if (
        any(
            hint in lower
            for hint in (
                "timed out",
                "timeout",
                "connection",
                "network",
                "temporary failure",
                "unreachable",
                "getaddrinfo",
            )
        )
        or re.search(r"\b5\d{2}\b", text)
    ):
        return "NETWORK_TRANSIENT"
    if any(
        hint in lower
        for hint in (
            "unsupported url",
            "no video formats",
            "not available",
            "video unavailable",
            "no media",
        )
    ):
        return "UNSUPPORTED_URL"
    return "UNKNOWN"


def diagnostic_message(message: str, url: str = "") -> tuple[str, str]:
    """Return a stable error code plus user-facing guidance."""
    code = classify_error(message, url)
    return code, _ERROR_MESSAGES.get(code, _clean_error_text(message))


def error_action(code: str) -> Optional[str]:
    """Return the UI action a given error code should offer, if any."""
    return "open_settings" if code in _SETTINGS_ACTION_CODES else None




# Instagram only serves embed metadata to link-preview crawlers; a browser UA
# gets the login shell. Keep this separate from normal page requests.


def _cookie_source_configured() -> bool:
    browser = str(_cookie_preferences.get("cookies_from_browser") or "none").strip().lower()
    return bool(_cookie_preferences.get("cookies_file")) or browser not in ("", "none")


async def extract_info(url: str) -> MediaInfo:
    """Extract metadata without downloading."""
    if not validate_url_not_private(url):
        raise ValueError("Invalid or private URL not allowed")

    if is_music_url(url):
        return _music_media_info(await resolve_music(url))

    is_tiktok_photo = "tiktok.com" in url.lower() and "/photo/" in url.lower()
    photo_images: List[str] = []
    photo_title: Optional[str] = None
    if is_tiktok_photo:
        photo_images, photo_title = await _fetch_tiktok_photos(url)

    clean_url = _clean_url(url)
    ig_target = _instagram_shortcode(clean_url)
    embed_attempted = False
    embed_info: Optional[MediaInfo] = None
    if ig_target and not _cookie_source_configured():
        embed_attempted = True
        embed_info = await _instagram_embed_info(clean_url)
        # A video result with no formats is only a poster; let yt-dlp try first.
        if embed_info is not None and embed_info.media_type != "video":
            return embed_info

    is_photo = _is_photo_url(url)
    ydl_opts = _get_base_opts(clean_url)
    ydl_opts["skip_download"] = True
    # Photo carousels need full entry metadata; video playlists stay flat.
    ydl_opts["extract_flat"] = False if is_photo else "in_playlist"
    ydl_opts["noplaylist"] = False
    if is_photo:
        ydl_opts["ignore_no_formats_error"] = True

    loop = asyncio.get_event_loop()

    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(clean_url, download=False)

    try:
        info = await loop.run_in_executor(None, _extract)
    except Exception as e:
        if is_tiktok_photo and photo_images:
            return _tiktok_photo_info(photo_images, photo_title, [])
        if _extract_platform(clean_url) == "pinterest":
            fallback = await _pinterest_image_info(clean_url)
            if fallback is not None:
                return fallback
        if ig_target:
            if not embed_attempted:
                embed_info = await _instagram_embed_info(clean_url)
            if embed_info is not None and embed_info.media_type != "video":
                return embed_info
            friendly = _friendly_error(str(e), clean_url)
            if friendly:
                raise ValueError(friendly) from e
            raise ValueError(_ERROR_MESSAGES["COOKIE_REQUIRED"]) from e
        friendly = _friendly_error(str(e), clean_url)
        if friendly:
            raise ValueError(friendly) from e
        raise

    if not isinstance(info, dict):
        raise ValueError("No media information found for this link")

    if is_tiktok_photo and photo_images:
        return _tiktok_photo_info(
            photo_images, photo_title or info.get("title"), _audio_formats(info)
        )

    if _extract_platform(clean_url) == "pinterest" and not _has_playable_format(info):
        fallback = await _pinterest_image_info(clean_url)
        if fallback is not None:
            return fallback

    images = _collect_images(info) if is_photo else []
    if images:
        return MediaInfo(
            title=info.get("title") or "Photo post",
            thumbnail=images[0],
            uploader=info.get("uploader") or info.get("channel") or info.get("creator"),
            platform=_extract_platform(clean_url),
            images=images,
            media_type="carousel" if len(images) > 1 else "image",
        )

    if info.get("_type") == "playlist" and not is_photo:
        entries = _collect_entries(info)
        if entries:
            raw_duration = info.get("duration")
            return MediaInfo(
                title=info.get("title") or "Playlist",
                thumbnail=_best_thumbnail_url(info),
                duration=round(raw_duration)
                if isinstance(raw_duration, (int, float))
                else None,
                uploader=info.get("uploader")
                or info.get("channel")
                or info.get("creator"),
                platform=_extract_platform(clean_url),
                entries=[PreviewEntry(**entry) for entry in entries],
                formats=[],
                images=[],
                media_type="playlist",
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
            formats.append(_audio_format(f))

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


async def inspect_entries(url: str) -> List[dict]:
    """Flat playlist inspection: expanded entries, or one item for a single URL."""
    if not validate_url_not_private(url):
        raise ValueError("Invalid or private URL not allowed")
    if is_music_url(url):
        return (await resolve_music(url))["entries"]
    if "tiktok.com" in url.lower() and "/photo/" in url.lower():
        images, title = await _fetch_tiktok_photos(url)
        if images:
            return [
                {
                    "url": url,
                    "title": title or "TikTok photo",
                    "duration": None,
                    "thumbnail": images[0],
                    "platform": "tiktok",
                    "media_type": "carousel" if len(images) > 1 else "image",
                }
            ]
    clean_url = _clean_url(url)
    ig_target = _instagram_shortcode(clean_url)
    embed_attempted = False
    embed_info: Optional[MediaInfo] = None
    if ig_target and not _cookie_source_configured():
        embed_attempted = True
        embed_info = await _instagram_embed_info(clean_url)
        if embed_info is not None and embed_info.media_type != "video":
            return [_instagram_preview_entry(embed_info, clean_url)]
    try:
        info = await asyncio.get_running_loop().run_in_executor(
            None, _flat_info, clean_url
        )
    except Exception:
        if ig_target:
            if not embed_attempted:
                embed_info = await _instagram_embed_info(clean_url)
            if embed_info is not None and embed_info.media_type != "video":
                return [_instagram_preview_entry(embed_info, clean_url)]
        raise
    if not isinstance(info, dict):
        if ig_target:
            if not embed_attempted:
                embed_info = await _instagram_embed_info(clean_url)
            if embed_info is not None and embed_info.media_type != "video":
                return [_instagram_preview_entry(embed_info, clean_url)]
        raise ValueError("No media information found for this link")
    entries = _collect_entries(info)
    if entries:
        return entries
    if info.get("_type") == "playlist":
        raise ValueError("This playlist has no downloadable entries")
    return [_single_entry(info, clean_url)]


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
    search_query: Optional[str] = None,
    music_metadata: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    """Download and convert media. Returns (final file path, title)."""
    if not validate_url_not_private(url):
        raise ValueError("Invalid or private URL not allowed")

    if is_music_url(url) and not search_query:
        resolved = await resolve_music(url)
        if resolved.get("media_type") != "track":
            raise ValueError(
                "This is a Spotify or Apple Music album or playlist. "
                "Select individual tracks to download."
            )
        entry = (resolved.get("entries") or [None])[0]
        if not entry:
            raise ValueError("No downloadable track was found for this music link.")
        search_query = entry.get("search_query")
        if not search_query:
            raise ValueError("Could not build a search query for this music track.")
        if music_metadata is None:
            music_metadata = {
                "title": entry.get("title"),
                "artist": entry.get("artist"),
                "album": entry.get("album"),
                "track_number": entry.get("track_number"),
                "thumbnail": entry.get("thumbnail") or resolved.get("thumbnail"),
            }

    clean_url = _clean_url(url)
    start, end = validate_clip_range(start_time, end_time)
    audio_requested = (
        fmt in ("mp3", "m4a", "opus")
        or is_music_url(url)
        or bool(search_query)
    )
    preset_name = _normalize_preset(preset, social_bypass, audio=audio_requested)
    if audio_requested and preset_name in ("edit_ready", "social_bypass"):
        preset_name = None

    is_tiktok_photo = "tiktok.com" in url.lower() and "/photo/" in url.lower()
    # Images, and legacy video/default requests, use the photo ZIP path.
    # Audio codecs stay on yt-dlp so the background music is downloadable.
    if not search_query and (
        fmt == "images"
        or (is_tiktok_photo and fmt not in ("mp3", "m4a", "opus"))
    ):
        return await _download_photo_post(url, tmp_dir, job_store, job_id, cancel_event)

    download_url = clean_url
    download_fmt = fmt
    if search_query:
        download_fmt = fmt if fmt in ("mp3", "m4a", "opus") else "mp3"
        download_url = f"ytsearch1:{str(search_query).strip()}"

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
        download_fmt, quality, output_path, progress_hook, download_url, start, end
    )

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(download_url, download=True)
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

    filepath = _find_output_file(
        tmp_dir,
        job_id,
        download_fmt if download_fmt in ("mp3", "m4a", "opus") else None,
    )
    if preset_name:
        filepath = await loop.run_in_executor(None, _postprocess_file, filepath, preset_name)

    if search_query or music_metadata is not None:
        metadata = dict(music_metadata or {})
        if not metadata.get("title"):
            metadata["title"] = extracted_title
        cover_path = None
        if metadata.get("thumbnail"):
            cover_path = await _download_music_cover(
                metadata.get("thumbnail"), tmp_dir, job_id
            )
        filepath = await loop.run_in_executor(
            None, _embed_music_metadata, filepath, metadata, cover_path
        )
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

