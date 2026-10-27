"""TikTok adapter: Photo Mode metadata chain (desktop -> mobile -> embed)."""
from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from app.models.schemas import FormatOption, MediaInfo

from .common import TIKTOK_UA, _find_key, _json_object_after, _meta_content


def _url_allowed(url: str) -> bool:
    """Compatibility seam: the tests monkeypatch extractor.validate_url_not_private."""
    from app.services import extractor

    return extractor.validate_url_not_private(url)


async def _fetch_html(url: str, user_agent: str) -> Optional[str]:
    """Compatibility seam: the tests monkeypatch extractor._tiktok_fetch_html."""
    from app.services import extractor

    return await extractor._tiktok_fetch_html(url, user_agent)


_TIKTOK_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)


_TIKTOK_AWEME_RE = re.compile(r"/(?:photo|video)/(\d+)")


def _tiktok_first_url(holder: Any) -> Optional[str]:
    """First full-size CDN URL in a urlList holder."""
    if isinstance(holder, dict) and isinstance(holder.get("urlList"), list):
        for url in holder["urlList"]:
            if isinstance(url, str) and url.startswith("http"):
                return url
    return None


def _tiktok_image_urls(node: Any) -> List[str]:
    """One full-size URL per image from an imagePost/imagePostInfo object."""
    if not isinstance(node, dict):
        return []
    items = node.get("displayImages")
    if not isinstance(items, list):
        items = node.get("images")
    if not isinstance(items, list):
        return []
    urls: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = (
            _tiktok_first_url(item.get("imageURL"))
            or _tiktok_first_url(item.get("displayImage"))
            or _tiktok_first_url(item)
        )
        if url:
            urls.append(url)
    return urls


def _tiktok_title(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    lines = html_lib.unescape(value).strip().splitlines()
    title = lines[0].strip() if lines else ""
    return title[:120].rstrip() or None


def _parse_tiktok_photo_html(html: str) -> tuple[List[str], Optional[str]]:
    """Extract full-size slideshow URLs and a title from any TikTok page variant."""
    images: List[str] = []
    title: Optional[str] = None

    match = re.search(
        r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        try:
            data = json.loads(match.group(1))
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            for key in ("imagePost", "imagePostInfo"):
                node = _find_key(data, key)
                if isinstance(node, dict):
                    images.extend(_tiktok_image_urls(node))
                    title = title or _tiktok_title(
                        node.get("title") or node.get("desc")
                    )
            title = title or _tiktok_title(_find_key(data, "desc"))

    # Page variants keep these objects outside the hydration script (mobile/embed).
    for marker in ('"imagePost"', '"imagePostInfo"'):
        node = _json_object_after(html, marker)
        if isinstance(node, dict):
            images.extend(_tiktok_image_urls(node))
            title = title or _tiktok_title(node.get("title") or node.get("desc"))

    title = title or _tiktok_title(_meta_content(html, "og:title"))
    return list(dict.fromkeys(images)), title


async def _tiktok_fetch_html(url: str, user_agent: str) -> Optional[str]:
    headers = {"User-Agent": user_agent, "Referer": "https://www.tiktok.com/"}
    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=20.0, follow_redirects=False
        ) as client:
            current = url
            for _ in range(4):
                if not _url_allowed(current):
                    return None
                resp = await client.get(current)
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    host = (urlparse(current).hostname or "").lower()
                    if host != "tiktok.com" and not host.endswith(".tiktok.com"):
                        return None
                    continue
                if resp.status_code >= 400:
                    return None
                return resp.text
    except Exception:
        return None
    return None


async def _fetch_tiktok_photos(url: str) -> tuple[List[str], Optional[str]]:
    """Try desktop, mobile, then embed pages for photo slideshow images."""
    clean = str(url or "").strip()
    candidates = [(clean, TIKTOK_UA)]
    separator = "&" if "?" in clean else "?"
    candidates.append(
        (clean + separator + "is_from_webapp=1&sender_device=pc", _TIKTOK_MOBILE_UA)
    )
    aweme_match = _TIKTOK_AWEME_RE.search(clean)
    if aweme_match:
        candidates.append(
            (f"https://www.tiktok.com/embed/v2/{aweme_match.group(1)}", TIKTOK_UA)
        )
    for candidate, agent in candidates:
        page = await _fetch_html(candidate, agent)
        if not page:
            continue
        images, title = _parse_tiktok_photo_html(page)
        if images:
            return images, title
    return [], None


def _tiktok_photo_info(
    images: List[str], title: Optional[str], formats: list[FormatOption]
) -> MediaInfo:
    return MediaInfo(
        title=title or "TikTok photo",
        thumbnail=images[0],
        platform="tiktok",
        images=images,
        formats=formats,
        media_type="carousel" if len(images) > 1 else "image",
    )
