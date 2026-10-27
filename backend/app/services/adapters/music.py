"""Spotify and Apple Music bridge: metadata resolution and audio tagging."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, urljoin, urlparse, urlunparse

import httpx

from app.models.schemas import MediaInfo, PreviewEntry

from ..mediaops import _ffmpeg_executable
from .common import (
    MUSIC_TIMEOUT,
    TIKTOK_UA,
    _image_extension,
    _meta_content,
    _parse_script_json,
    _safe_cover_url,
)


async def _fetch_text(url: str) -> Optional[str]:
    """Compatibility seam: the tests monkeypatch extractor._get_text."""
    from app.services import extractor

    return await extractor._get_text(url)


def _url_allowed(url: str) -> bool:
    """Compatibility seam: the tests monkeypatch extractor.validate_url_not_private."""
    from app.services import extractor

    return extractor.validate_url_not_private(url)


MAX_COVER_BYTES = 10 * 1024 * 1024




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
    if not sources:
        # Live embed entities ship artwork only under visualIdentity.image.
        identity = node.get("visualIdentity")
        images = identity.get("image") if isinstance(identity, dict) else None
        if isinstance(images, list):
            sources = images
    best: Optional[str] = None
    best_area = -1
    for item in sources:
        if not isinstance(item, dict):
            continue
        url = _safe_cover_url(item.get("url"))
        if not url:
            continue
        width = item.get("width") or item.get("maxWidth") or 0
        height = item.get("height") or item.get("maxHeight") or 0
        area = width * height
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
    payload_text = await _fetch_text(
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
    html_text = await _fetch_text(f"https://open.spotify.com/embed/{kind}/{spotify_id}")
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
    html_text = await _fetch_text(embed_url)
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


async def _download_music_cover(
    url: Optional[str], tmp_dir: str, job_id: str
) -> Optional[str]:
    """Best-effort cover fetch into tmp; queue cleanup owns the file."""
    safe = _safe_cover_url(url)
    if not safe or not _url_allowed(safe):
        return None
    headers = {"User-Agent": TIKTOK_UA, "Accept": "image/*"}
    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=MUSIC_TIMEOUT, follow_redirects=False
        ) as client:
            current = safe
            for _ in range(4):
                if not _url_allowed(current):
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
