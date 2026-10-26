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


BROWSER_CHOICES = ("none", "chrome", "edge", "brave", "firefox")
PRESET_CHOICES = ("edit_ready", "audio_norm", "audio_lossless", "social_bypass")
MAX_COOKIE_FILE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_COVER_BYTES = 10 * 1024 * 1024
MUSIC_TIMEOUT = 15.0
AUDIO_FILENAME_TEMPLATES = (
    "{track} - {artist} - {title}",
    "{artist} - {title}",
    "{title} ({artist})",
    "{title}",
)
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


_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_name(text: str) -> str:
    """Strip characters Windows rejects and trim trailing dots/spaces."""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("", str(text or "")).strip()
    return cleaned.strip(" .")


def format_audio_filename(
    template: str,
    metadata: Dict[str, Any],
    ext: str,
    playlist: bool = False,
) -> str:
    """Render one of the supported audio filename presets."""
    metadata = metadata or {}
    chosen = (
        template.strip()
        if isinstance(template, str) and template.strip()
        else AUDIO_FILENAME_TEMPLATES[1]
    )
    title = str(metadata.get("title") or "").strip()
    artist = str(metadata.get("artist") or "").strip()
    album = str(metadata.get("album") or "").strip()
    raw_track = metadata.get("track_number")
    track = None
    if isinstance(raw_track, int) and not isinstance(raw_track, bool) and raw_track > 0:
        track = raw_track
    elif str(raw_track or "").strip().isdigit():
        track = int(str(raw_track).strip())

    name = chosen
    for token, value in (
        ("{track}", f"{track:02d}" if track else ""),
        ("{artist}", artist),
        ("{title}", title),
        ("{album}", album),
    ):
        name = name.replace(token, value)
    name = re.sub(r"\{[^{}]*\}", "", name)
    name = re.sub(r"\s*\(\s*\)", "", name)
    name = re.sub(r"\s*-\s*-\s*", " - ", name)
    name = re.sub(r"^(?:\s*-\s*)+|(?:\s*-\s*)+$", "", name)
    name = sanitize_name(name) or sanitize_name(title) or "Untitled"

    if playlist and track and "{track}" not in chosen:
        name = f"{track:02d} - {name}"

    extension = str(ext or "").strip()
    if extension and not extension.startswith("."):
        extension = "." + extension
    return name + extension


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


_SPOTIFY_PATH_RE = re.compile(
    r"^/(?:intl-[a-z-]+/)?(track|album|playlist)/([A-Za-z0-9]+)", re.IGNORECASE
)


def is_music_url(url: str) -> bool:
    """True for Spotify track/album/playlist and Apple Music links."""
    if not isinstance(url, str) or not url.strip():
        return False
    cleaned = url.strip()
    if "://" not in cleaned:
        cleaned = "https://" + cleaned
    try:
        parsed = urlparse(cleaned)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if host == "open.spotify.com":
        return bool(_SPOTIFY_PATH_RE.match(parsed.path))
    if host == "music.apple.com":
        return bool(parsed.path.strip("/"))
    return False


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


async def _get_text(url: str) -> Optional[str]:
    """Fetch a public HTML/JSON page from a fixed music host."""
    headers = {
        "User-Agent": TIKTOK_UA,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=MUSIC_TIMEOUT, follow_redirects=False
        ) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                return None
            return response.text
    except Exception:
        return None


def _parse_script_json(html_text: Optional[str], script_id: str) -> Any:
    if not html_text:
        return None
    match = re.search(
        r'<script[^>]*\bid=["\']' + re.escape(script_id) + r'["\'][^>]*>(.*?)</script>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (TypeError, ValueError):
        return None


def _meta_content(html_text: str, prop: str) -> Optional[str]:
    for tag in re.findall(r"<meta\b[^>]*>", html_text or "", flags=re.IGNORECASE):
        if re.search(
            r'(?:property|name)\s*=\s*["\']' + re.escape(prop) + r'["\']',
            tag,
            flags=re.IGNORECASE,
        ):
            match = re.search(
                r'content\s*=\s*["\']([^"\']*)["\']',
                tag,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match:
                content = html_lib.unescape(match.group(1)).strip()
                if content:
                    return content
    return None


def _safe_cover_url(value: Any) -> Optional[str]:
    """Accept only http(s) cover URLs without literal private hosts."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            return None
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if is_private_or_loopback_ip(str(ip)):
                return None
        except ValueError:
            pass
    except ValueError:
        return None
    return url


def _music_duration(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    seconds = value / 1000 if value > 10000 else value
    return round(seconds)


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def _search_query(artist: Optional[str], title: Optional[str]) -> str:
    title_text = str(title or "").strip()
    artist_text = str(artist or "").strip()
    if artist_text and title_text:
        return f"{artist_text} - {title_text} official audio"
    if title_text:
        return f"{title_text} official audio"
    return ""


def _music_entry(
    url: str,
    title: str,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    track_number: Optional[Any] = None,
    duration: Optional[Any] = None,
    thumbnail: Optional[str] = None,
    platform: str = "spotify",
) -> Dict[str, Any]:
    clean_title = str(title or "").strip() or "Untitled"
    clean_artist = str(artist).strip() if artist else None
    clean_album = str(album).strip() if album else None
    return {
        "url": url,
        "title": clean_title,
        "artist": clean_artist,
        "album": clean_album,
        "track_number": _positive_int(track_number),
        "duration": _music_duration(duration),
        "thumbnail": _safe_cover_url(thumbnail),
        "platform": platform,
        "media_type": "audio",
        "search_query": _search_query(clean_artist, clean_title),
    }


def _unique_music_url(url: str, source: str, index: int, seen: set) -> str:
    if url not in seen:
        seen.add(url)
        return url
    candidate = f"{source}#track-{index}"
    if candidate in seen:
        candidate = f"{source}#track-{index}-{len(seen) + 1}"
    seen.add(candidate)
    return candidate


def _music_collection(
    platform: str,
    media_type: str,
    title: Optional[str],
    artist: Optional[str],
    album: Optional[str],
    thumbnail: Optional[str],
    entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "platform": platform,
        "title": str(title or "").strip() or "Music",
        "artist": artist,
        "album": album,
        "thumbnail": _safe_cover_url(thumbnail),
        "media_type": media_type,
        "entries": entries,
    }


def _spotify_target(url: str) -> tuple[str, str]:
    match = _SPOTIFY_PATH_RE.match(urlparse(url).path)
    if not match:
        raise ValueError("This is not a supported Spotify link.")
    return match.group(1).lower(), match.group(2)


def _spotify_artists(value: Any) -> List[str]:
    if isinstance(value, dict):
        value = [value]
    elif isinstance(value, str):
        value = [value]
    names: List[str] = []
    if isinstance(value, list):
        for item in value:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names


def _spotify_cover(node: Dict[str, Any]) -> Optional[str]:
    cover = node.get("coverArt")
    sources: List[Any] = []
    if isinstance(cover, dict):
        raw = cover.get("sources")
        sources = raw if isinstance(raw, list) else [cover]
    elif isinstance(cover, str):
        sources = [{"url": cover}]
    best: Optional[str] = None
    best_area = -1
    for item in sources:
        if not isinstance(item, dict):
            continue
        url = _safe_cover_url(item.get("url"))
        if not url:
            continue
        area = (item.get("width") or 0) * (item.get("height") or 0)
        if area >= best_area:
            best, best_area = url, area
    return best


def _find_spotify_entity(node: Any) -> Optional[Dict[str, Any]]:
    if isinstance(node, dict):
        if isinstance(node.get("trackList"), list):
            return node
        if node.get("type") in ("track", "album", "playlist") and (
            "name" in node or "title" in node
        ):
            return node
        for value in node.values():
            found = _find_spotify_entity(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_spotify_entity(value)
            if found is not None:
                return found
    return None


def _spotify_entity_track(
    entity: Dict[str, Any], source: str
) -> Optional[Dict[str, Any]]:
    title = entity.get("name") or entity.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    artists = _spotify_artists(entity.get("artists"))
    artist = ", ".join(artists) if artists else entity.get("subtitle")
    album = entity.get("album")
    if isinstance(album, dict):
        album = album.get("name")
    return _music_entry(
        source,
        title,
        artist if isinstance(artist, str) else None,
        album if isinstance(album, str) else None,
        entity.get("trackNumber"),
        entity.get("duration") if entity.get("duration") is not None else entity.get("duration_ms"),
        _spotify_cover(entity),
        "spotify",
    )


def _spotify_entry(
    item: Dict[str, Any],
    index: int,
    source: str,
    top_artist: Optional[str],
    album: Optional[str],
    top_cover: Optional[str],
) -> Dict[str, Any]:
    uri = str(item.get("uri") or "")
    match = re.match(r"spotify:track:([A-Za-z0-9]+)", uri, flags=re.IGNORECASE)
    url = (
        f"https://open.spotify.com/track/{match.group(1)}"
        if match
        else f"{source}#track-{index}"
    )
    artist = item.get("subtitle")
    if not isinstance(artist, str) or not artist.strip():
        names = _spotify_artists(item.get("artists"))
        artist = ", ".join(names) if names else top_artist
    item_album = item.get("album")
    duration = (
        item.get("duration") if item.get("duration") is not None else item.get("duration_ms")
    )
    return _music_entry(
        url,
        item.get("title") or item.get("name") or "Untitled",
        artist if isinstance(artist, str) else top_artist,
        item_album if isinstance(item_album, str) else album,
        _positive_int(item.get("trackNumber")) or index,
        duration,
        _spotify_cover(item) or top_cover,
        "spotify",
    )


async def _spotify_oembed(source: str) -> Optional[Dict[str, Any]]:
    payload_text = await _get_text(
        f"https://open.spotify.com/oembed?url={quote(source, safe='')}"
    )
    if not payload_text:
        return None
    try:
        payload = json.loads(payload_text)
    except (TypeError, ValueError):
        return None
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    return _music_entry(
        source,
        title,
        payload.get("author_name"),
        None,
        None,
        None,
        payload.get("thumbnail_url"),
        "spotify",
    )


async def _resolve_spotify(url: str) -> Dict[str, Any]:
    kind, spotify_id = _spotify_target(url)
    source = f"https://open.spotify.com/{kind}/{spotify_id}"
    html_text = await _get_text(f"https://open.spotify.com/embed/{kind}/{spotify_id}")
    data = _parse_script_json(html_text, "__NEXT_DATA__")
    entity = _find_spotify_entity(data) if data is not None else None

    if kind == "track":
        entry = _spotify_entity_track(entity, source) if entity else None
        if entry is None:
            entry = await _spotify_oembed(source)
        if entry is None:
            raise ValueError(
                "Could not read this Spotify track. It may be private or unavailable."
            )
        return _music_collection(
            "spotify",
            "track",
            entry["title"],
            entry["artist"],
            entry["album"],
            entry["thumbnail"],
            [entry],
        )

    if entity is None:
        raise ValueError("Spotify did not return a track list for this album or playlist.")
    track_list = entity.get("trackList")
    if not isinstance(track_list, list) or not track_list:
        raise ValueError("Spotify did not return a track list for this album or playlist.")

    title = entity.get("name") or entity.get("title") or "Spotify playlist"
    artists = _spotify_artists(entity.get("artists"))
    artist = ", ".join(artists) if artists else entity.get("subtitle")
    if not isinstance(artist, str) or not artist.strip():
        artist = None
    cover = _spotify_cover(entity)
    album = title if kind == "album" else None
    entries: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(track_list, 1):
        if not isinstance(item, dict):
            continue
        entry = _spotify_entry(item, index, source, artist, album, cover)
        entry["url"] = _unique_music_url(entry["url"], source, index, seen)
        entries.append(entry)
    if not entries:
        raise ValueError("Spotify did not return a track list for this album or playlist.")
    if not artist:
        artist = entries[0]["artist"]
    return _music_collection(
        "spotify", kind, title, artist, album, cover, entries
    )


def _apple_target(url: str) -> tuple[str, str, str, Optional[str]]:
    parsed = urlparse(url)
    source = urlunparse(parsed._replace(fragment=""))
    path = parsed.path or "/"
    query = parse_qs(parsed.query)
    if "i" in query or "/song/" in path.lower():
        kind = "track"
    elif "/playlist/" in path.lower():
        kind = "playlist"
    else:
        kind = "album"
    embed = "https://embed.music.apple.com" + path
    if parsed.query:
        embed += "?" + parsed.query
    return kind, source, embed, (query.get("i") or [None])[0]


def _collect_apple_songs(
    node: Any, songs: List[Dict[str, Any]], seen: set
) -> None:
    if isinstance(node, dict):
        title = node.get("title")
        artist = node.get("artistName")
        node_type = str(node.get("type") or "").lower()
        if (
            isinstance(title, str)
            and title.strip()
            and isinstance(artist, str)
            and artist.strip()
            and node_type not in ("album", "playlist")
        ):
            key = node.get("id") or node.get("songId")
            if not isinstance(key, (str, int)):
                key = (title.strip().lower(), artist.strip().lower())
            if key not in seen:
                seen.add(key)
                songs.append(node)
        for value in node.values():
            _collect_apple_songs(value, songs, seen)
    elif isinstance(node, list):
        for value in node:
            _collect_apple_songs(value, songs, seen)


def _apple_artwork(node: Dict[str, Any]) -> Optional[str]:
    artwork = node.get("artwork")
    url = None
    if isinstance(artwork, dict):
        url = artwork.get("url") or artwork.get("template")
    elif isinstance(artwork, str):
        url = artwork
    if not url:
        url = node.get("artworkUrl")
    safe = _safe_cover_url(url)
    if not safe:
        return None
    return safe.replace("{w}", "600").replace("{h}", "600")


def _apple_entry(
    song: Dict[str, Any],
    index: int,
    fallback_url: str,
    collection_album: Optional[str],
    fallback_cover: Optional[str],
) -> Dict[str, Any]:
    candidate = song.get("url")
    url = None
    if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
        host = (urlparse(candidate).hostname or "").lower()
        if host == "music.apple.com":
            url = candidate
    if not url:
        url = fallback_url
    album = song.get("albumName")
    if not isinstance(album, str) or not album.strip():
        album = collection_album
    duration = song.get("durationInMillis")
    if duration is None:
        duration = song.get("duration")
    return _music_entry(
        url,
        song.get("title") or song.get("name") or "Untitled",
        song.get("artistName") if isinstance(song.get("artistName"), str) else None,
        album if isinstance(album, str) else None,
        _positive_int(song.get("trackNumber")) or index,
        duration,
        _apple_artwork(song) or fallback_cover,
        "apple",
    )


async def _resolve_apple(url: str) -> Dict[str, Any]:
    kind, source, embed_url, track_id = _apple_target(url)
    html_text = await _get_text(embed_url)
    data = _parse_script_json(html_text, "serialized-server-data")
    songs: List[Dict[str, Any]] = []
    if data is not None:
        _collect_apple_songs(data, songs, set())
    og_title = _meta_content(html_text or "", "og:title")
    og_image = _safe_cover_url(_meta_content(html_text or "", "og:image"))

    if kind == "track":
        chosen = None
        chosen_index = 1
        if track_id:
            for index, song in enumerate(songs, 1):
                song_url = str(song.get("url") or "")
                if f"i={track_id}" in song_url or str(song.get("id") or "") == str(track_id):
                    chosen, chosen_index = song, index
                    break
        if chosen is None and songs:
            chosen, chosen_index = songs[0], 1
        if chosen is not None:
            entry = _apple_entry(chosen, chosen_index, source, None, og_image)
            return _music_collection(
                "apple",
                "track",
                entry["title"],
                entry["artist"],
                entry["album"],
                entry["thumbnail"],
                [entry],
            )
        if og_title:
            entry = _music_entry(
                source, og_title, None, None, None, None, og_image, "apple"
            )
            return _music_collection(
                "apple", "track", entry["title"], None, None, entry["thumbnail"], [entry]
            )
        raise ValueError(
            "Could not read this Apple Music track. It may be private or unavailable."
        )

    if not songs:
        raise ValueError(
            "Apple Music did not return a track list for this album or playlist."
        )
    album = None
    if kind == "album":
        album = next(
            (
                song.get("albumName")
                for song in songs
                if isinstance(song.get("albumName"), str) and song.get("albumName")
            ),
            None,
        )
    entries: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    for index, song in enumerate(songs, 1):
        entry = _apple_entry(
            song, index, f"{source}#track-{index}", album, og_image
        )
        entry["url"] = _unique_music_url(entry["url"], source, index, seen_urls)
        entries.append(entry)
    title = og_title or album or songs[0].get("title") or "Apple Music"
    return _music_collection(
        "apple",
        kind,
        title,
        entries[0]["artist"],
        album,
        og_image or entries[0]["thumbnail"],
        entries,
    )


async def resolve_music(url: str) -> Dict[str, Any]:
    """Resolve a Spotify or Apple Music link into preview entries."""
    target = str(url or "").strip()
    if "://" not in target:
        target = "https://" + target
    if not is_music_url(target):
        raise ValueError("This is not a supported Spotify or Apple Music link.")
    host = (urlparse(target).hostname or "").lower()
    if host == "open.spotify.com":
        return await _resolve_spotify(target)
    return await _resolve_apple(target)


def _music_media_info(data: Dict[str, Any]) -> MediaInfo:
    entries = [PreviewEntry(**entry) for entry in data.get("entries") or []]
    platform = data.get("platform")
    if data.get("media_type") == "track" and entries:
        entry = entries[0]
        return MediaInfo(
            title=entry.title,
            thumbnail=entry.thumbnail or data.get("thumbnail"),
            duration=entry.duration,
            uploader=entry.artist or data.get("artist"),
            platform=platform,
            formats=[],
            media_type="video",
            artist=entry.artist,
            album=entry.album,
            track_number=entry.track_number,
            search_query=entry.search_query,
        )
    return MediaInfo(
        title=data.get("title") or "Music",
        thumbnail=data.get("thumbnail"),
        uploader=data.get("artist"),
        platform=platform,
        entries=entries,
        formats=[],
        media_type="playlist",
        artist=data.get("artist"),
        album=data.get("album"),
    )


_PINTEREST_ORIGINAL_RE = re.compile(r"^(https?://i\.pinimg\.com/)[^/]+/", re.IGNORECASE)


def _upgrade_pinterest_image(url: Optional[str]) -> Optional[str]:
    """Ask Pinterest for the original image instead of the preview size."""
    safe = _safe_cover_url(url)
    if not safe:
        return None
    return _PINTEREST_ORIGINAL_RE.sub(r"\1originals/", safe)


def _photo_referer(url: str) -> str:
    lower = url.lower()
    if "tiktok.com" in lower:
        return "https://www.tiktok.com/"
    if "pinterest." in lower or "pin.it" in lower:
        return "https://www.pinterest.com/"
    return "https://www.instagram.com/"


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
_IG_EMBED_UA = (
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
)
_IG_SHORTCODE_RE = re.compile(r"/(p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.IGNORECASE)
_IG_MEDIA_KEYS = (
    "is_video",
    "display_url",
    "display_resources",
    "image_versions2",
    "video_versions",
    "video_url",
    "carousel_media",
    "edge_sidecar_to_children",
    "edge_media_to_caption",
    "caption",
)


def _instagram_shortcode(url: str) -> Optional[tuple[str, str]]:
    """Return (kind, shortcode) for public Instagram post/reel/tv links."""
    if not isinstance(url, str) or not url.strip():
        return None
    cleaned = url.strip()
    if "://" not in cleaned:
        cleaned = "https://" + cleaned
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None
    if (parsed.hostname or "").lower().rstrip(".") not in ("instagram.com", "www.instagram.com"):
        return None
    match = _IG_SHORTCODE_RE.search(parsed.path or "")
    if not match:
        return None
    return match.group(1).lower(), match.group(2)


def _json_string_after(text: str, marker: str) -> Optional[str]:
    """Decode the JSON string value that follows a marker (honours escapes)."""
    pos = text.find(marker)
    if pos < 0:
        return None
    pos += len(marker)
    while pos < len(text) and text[pos] in " \t\r\n:":
        pos += 1
    if pos >= len(text) or text[pos] != '"':
        return None
    pos += 1
    raw: List[str] = []
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            raw.append(text[pos : pos + 2])
            pos += 2
            continue
        if char == '"':
            try:
                return json.loads('"' + "".join(raw) + '"')
            except (TypeError, ValueError):
                return None
        raw.append(char)
        pos += 1
    return None


def _json_object_after(text: str, marker: str) -> Optional[Dict[str, Any]]:
    """Brace-match and decode the first JSON object after a marker."""
    pos = text.find(marker)
    if pos < 0:
        return None
    start = text.find("{", pos + len(marker))
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start : index + 1])
                except (TypeError, ValueError):
                    return None
                return value if isinstance(value, dict) else None
    return None


def _instagram_context_payload(html_text: str) -> Any:
    raw = _json_string_after(html_text, '"contextJSON"')
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("context"), str):
        try:
            data["context"] = json.loads(data["context"])
        except (TypeError, ValueError):
            pass
    return data


def _ig_media_url(item: Any) -> Optional[str]:
    if isinstance(item, str):
        return _safe_cover_url(item)
    if isinstance(item, dict):
        for key in ("src", "url"):
            safe = _safe_cover_url(item.get(key))
            if safe:
                return safe
    return None


def _ig_resource_area(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    width = item.get("width") or item.get("config_width") or 0
    height = item.get("height") or item.get("config_height") or 0
    try:
        return int(width) * int(height)
    except (TypeError, ValueError):
        return 0


def _ig_best_image(node: Dict[str, Any]) -> Optional[str]:
    candidates: List[tuple[str, int]] = []
    for key in ("display_resources", "thumbnail_resources"):
        items = node.get(key)
        if isinstance(items, dict):
            items = [items]
        if isinstance(items, list):
            for item in items:
                url = _ig_media_url(item)
                if url:
                    candidates.append((url, _ig_resource_area(item)))
    versions = node.get("image_versions2")
    if isinstance(versions, dict):
        for item in versions.get("candidates") or []:
            url = _ig_media_url(item)
            if url:
                candidates.append((url, _ig_resource_area(item)))
    for key in ("display_url", "thumbnail_src"):
        url = _safe_cover_url(node.get(key))
        if url:
            candidates.append((url, 0))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1])[0]


def _ig_is_video(node: Dict[str, Any]) -> bool:
    return bool(node.get("is_video")) or bool(node.get("video_versions")) or bool(
        node.get("video_url")
    )


def _ig_duration(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return round(float(value), 3)


def _ig_caption(node: Dict[str, Any]) -> Optional[str]:
    edge_holder = node.get("edge_media_to_caption")
    edges = edge_holder.get("edges") if isinstance(edge_holder, dict) else None
    if isinstance(edges, list) and edges and isinstance(edges[0], dict):
        text = (edges[0].get("node") or {}).get("text")
        if isinstance(text, str) and text.strip():
            return text
    caption = node.get("caption")
    if isinstance(caption, dict) and isinstance(caption.get("text"), str):
        if caption["text"].strip():
            return caption["text"]
    if isinstance(caption, str) and caption.strip():
        return caption
    return None


def _ig_owner(node: Dict[str, Any]) -> Optional[str]:
    for key in ("owner", "user"):
        holder = node.get(key)
        if isinstance(holder, dict) and isinstance(holder.get("username"), str):
            username = holder["username"].strip()
            if username:
                return username
    return None


def _ig_media_nodes(root: Any) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    seen: set[int] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if id(value) in seen:
                return
            seen.add(id(value))
            if any(key in value for key in _IG_MEDIA_KEYS):
                nodes.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(root)
    return nodes


def _ig_row_text(text: Any, limit: int = 120) -> Optional[str]:
    first = html_lib.unescape(str(text or "")).strip().splitlines()
    line = first[0].strip() if first else ""
    return line[:limit].rstrip() or None


def _ig_clean_og_title(text: Any) -> Optional[str]:
    cleaned = html_lib.unescape(str(text or "")).strip()
    cleaned = re.sub(r'^.*?\bon Instagram:?\s*"?', "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip().strip('"').strip()
    return _ig_row_text(cleaned)


def _instagram_media_info(html_text: str) -> Optional[MediaInfo]:
    raw_text = html_text or ""
    # JSON payloads may be HTML-escaped; meta tags must stay as-is so their
    # own content escaping does not break attribute parsing.
    text = html_lib.unescape(raw_text)
    roots: List[Any] = []
    context = _instagram_context_payload(text)
    if context is not None:
        roots.append(context)
    for marker in ('"gql_data"', "__additionalDataLoaded"):
        data = None
        raw = _json_string_after(text, marker)
        if raw:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = None
        else:
            data = _json_object_after(text, marker)
        if isinstance(data, dict):
            roots.append(data)

    images: List[str] = []
    video_thumbnail: Optional[str] = None
    duration: Optional[float] = None
    uploader: Optional[str] = None
    caption: Optional[str] = None
    is_video = False
    carousel_items = 0
    for root in roots:
        for node in _ig_media_nodes(root):
            if caption is None:
                caption = _ig_caption(node)
            if uploader is None:
                uploader = _ig_owner(node)
            has_children = bool(
                node.get("carousel_media") or node.get("edge_sidecar_to_children")
            )
            if has_children:
                children = node.get("carousel_media")
                if isinstance(children, list):
                    carousel_items = max(carousel_items, len(children))
                edges = (node.get("edge_sidecar_to_children") or {}).get("edges")
                if isinstance(edges, list):
                    carousel_items = max(carousel_items, len(edges))
                continue
            if _ig_is_video(node):
                if not is_video:
                    is_video = True
                    video_thumbnail = _ig_best_image(node)
                    duration = _ig_duration(node.get("video_duration"))
                continue
            image = _ig_best_image(node)
            if image:
                images.append(image)
    images = list(dict.fromkeys(images))

    og_title = _ig_clean_og_title(_meta_content(raw_text, "og:title"))
    og_image = _safe_cover_url(
        _meta_content(raw_text, "og:image") or _meta_content(raw_text, "twitter:image")
    )
    og_video = _safe_cover_url(
        _meta_content(raw_text, "og:video")
        or _meta_content(raw_text, "og:video:secure_url")
    )
    if not is_video and og_video:
        is_video = True
        video_thumbnail = images[0] if images else og_image
    if not is_video and not images and og_image:
        images = [og_image]

    title = _ig_row_text(caption) or og_title or "Instagram post"
    if is_video and not images:
        return MediaInfo(
            title=title,
            thumbnail=video_thumbnail or og_image,
            duration=duration,
            uploader=uploader,
            platform="instagram",
            formats=[],
            images=[],
            media_type="video",
        )
    if not images:
        return None
    return MediaInfo(
        title=title,
        thumbnail=images[0],
        uploader=uploader,
        platform="instagram",
        images=images,
        media_type="carousel"
        if len(images) > 1 or carousel_items > 1
        else "image",
    )


async def _instagram_html(url: str) -> Optional[str]:
    headers = {"User-Agent": _IG_EMBED_UA, "Referer": "https://www.instagram.com/"}
    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=15.0, follow_redirects=True
        ) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                return None
            return response.text
    except Exception:
        return None


async def _instagram_embed_info(url: str) -> Optional[MediaInfo]:
    """Public embed fallback: works without cookies and never sends a session."""
    target = _instagram_shortcode(url)
    if not target:
        return None
    kind, shortcode = target
    candidates = [f"https://www.instagram.com/p/{shortcode}/embed/captioned/"]
    if kind != "p":
        candidates.append(
            f"https://www.instagram.com/{kind}/{shortcode}/embed/captioned/"
        )
    for embed_url in candidates:
        html_text = await _instagram_html(embed_url)
        if not html_text:
            continue
        info = _instagram_media_info(html_text)
        if info is not None:
            return info
    return None


def _instagram_preview_entry(info: MediaInfo, url: str) -> dict:
    return {
        "url": url,
        "title": info.title,
        "duration": info.duration,
        "thumbnail": info.thumbnail,
        "platform": "instagram",
        "media_type": info.media_type,
    }


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
    cover_prefix = f"{job_id}.cover."
    for name in os.listdir(tmp_dir):
        if (
            name.startswith(job_id)
            and not name.startswith(cover_prefix)
            and not name.endswith((".part", ".ytdl"))
        ):
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


async def _download_music_cover(
    url: Optional[str], tmp_dir: str, job_id: str
) -> Optional[str]:
    """Best-effort cover fetch into tmp; queue cleanup owns the file."""
    safe = _safe_cover_url(url)
    if not safe or not validate_url_not_private(safe):
        return None
    headers = {"User-Agent": TIKTOK_UA, "Accept": "image/*"}
    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=MUSIC_TIMEOUT, follow_redirects=False
        ) as client:
            current = safe
            for _ in range(4):
                if not validate_url_not_private(current):
                    return None
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        return None
                    content_type = response.headers.get("content-type", "")
                    if not content_type.startswith("image/"):
                        return None
                    path = os.path.join(
                        tmp_dir,
                        f"{job_id}.cover{_image_extension(current, content_type)}",
                    )
                    written = 0
                    try:
                        with open(path, "wb") as out:
                            async for chunk in response.aiter_bytes(64 * 1024):
                                written += len(chunk)
                                if written > MAX_COVER_BYTES:
                                    raise ValueError("Cover is larger than the 10 MB limit")
                                out.write(chunk)
                    except Exception:
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                        return None
                    return path
    except Exception:
        return None
    return None


def _music_ffmpeg_args(
    src: str,
    dst: str,
    metadata: Dict[str, Any],
    cover_path: Optional[str] = None,
) -> List[str]:
    """Arguments after the ffmpeg executable. Kept pure for unit tests."""
    metadata = metadata or {}
    ext = os.path.splitext(dst)[1].lower()
    args = ["-y", "-i", src]
    if cover_path and ext in (".mp3", ".m4a", ".flac"):
        args += [
            "-i", cover_path,
            "-map", "0:a", "-map", "1:v", "-c", "copy",
            "-disposition:v", "attached_pic",
            "-metadata:s:v", "title=Album cover",
            "-metadata:s:v", "comment=Cover (front)",
        ]
    else:
        args += ["-map_metadata", "0", "-c", "copy"]
    for key in ("title", "artist", "album"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            args += ["-metadata", f"{key}={str(value).strip()}"]
    track = _positive_int(metadata.get("track_number"))
    if track:
        args += ["-metadata", f"track={track}"]
    args.append(dst)
    return args


def _embed_music_metadata(
    path: str,
    metadata: Dict[str, Any],
    cover_path: Optional[str] = None,
) -> str:
    """Attach tags/cover, falling back to the untagged file on any failure."""
    ext = os.path.splitext(path)[1].lower()
    temp_path = f"{path}.tagged{ext}"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    attempts: List[List[str]] = []
    if cover_path:
        attempts.append(_music_ffmpeg_args(path, temp_path, metadata, cover_path))
    attempts.append(_music_ffmpeg_args(path, temp_path, metadata, None))
    for args in attempts:
        try:
            proc = subprocess.run(
                [_ffmpeg_executable(), *args],
                capture_output=True,
                text=True,
                timeout=300,
                creationflags=creationflags,
            )
        except Exception:
            continue
        if proc.returncode == 0 and os.path.isfile(temp_path):
            try:
                os.replace(temp_path, path)
                return path
            except OSError:
                pass
        try:
            os.remove(temp_path)
        except OSError:
            pass
    return path


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
    preset_name = _normalize_preset(preset, social_bypass)

    if (
        (fmt == "images" or ("tiktok.com" in url.lower() and "/photo/" in url.lower()))
        and not search_query
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

    filepath = _find_output_file(tmp_dir, job_id)
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

