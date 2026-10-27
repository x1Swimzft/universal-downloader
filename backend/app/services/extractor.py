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


BROWSER_CHOICES = ("none", "chrome", "edge", "brave", "firefox")
MAX_COOKIE_FILE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024

_cookie_preferences: Dict[str, Optional[str]] = {
    "cookies_from_browser": "none",
    "cookies_file": None,
}


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


_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_ERROR_MESSAGES = {
    "AUTH_403": "403 Forbidden - open Settings and enable Browser Cookies, then retry.",
    "COOKIE_REQUIRED": "Sign-in required - open Settings and enable Browser Cookies, then retry.",
    "COOKIE_LOCKED": "The browser cookie database is locked. Close Chrome/Edge, then retry, or export cookies.txt and select it in Settings.",
    "RATE_LIMIT": "Rate limited by the site - wait a moment, then retry, or enable Browser Cookies in Settings.",
    "NETWORK_TRANSIENT": "Network problem - check your connection, then retry.",
    "UNSUPPORTED_URL": "This link is unsupported or the media is unavailable.",
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


async def _fetch_public_html(url: str, referer: Optional[str] = None) -> Optional[str]:
    headers = {"User-Agent": TIKTOK_UA}
    if referer:
        headers["Referer"] = referer
    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=MUSIC_TIMEOUT, follow_redirects=False
        ) as client:
            current = url
            for _ in range(4):
                if not validate_url_not_private(current):
                    return None
                response = await client.get(current)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    return None
                return response.text
    except Exception:
        return None
    return None


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
    result = await _fetch_pinterest_image(url)
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


# Instagram only serves embed metadata to link-preview crawlers; a browser UA
# gets the login shell. Keep this separate from normal page requests.


def _cookie_source_configured() -> bool:
    browser = str(_cookie_preferences.get("cookies_from_browser") or "none").strip().lower()
    return bool(_cookie_preferences.get("cookies_file")) or browser not in ("", "none")


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

