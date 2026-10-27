"""Shared HTTP, HTML and URL-safety helpers used by every adapter."""
from __future__ import annotations

import html as html_lib
import ipaddress
import json
import re
import socket
from typing import Any, Optional
from urllib.parse import urlparse

import httpx


MUSIC_TIMEOUT = 15.0


TIKTOK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


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


def _photo_referer(url: str) -> str:
    lower = url.lower()
    if "tiktok.com" in lower:
        return "https://www.tiktok.com/"
    if "pinterest." in lower or "pin.it" in lower:
        return "https://www.pinterest.com/"
    return "https://www.instagram.com/"


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
