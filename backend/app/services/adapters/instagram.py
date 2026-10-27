"""Instagram adapter: embed fallback, crawler UA and media parsing."""
from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from app.models.schemas import MediaInfo

from .common import _json_object_after, _json_string_after, _meta_content, _safe_cover_url


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
