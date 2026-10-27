"""Adapter interface shared by every platform extractor.

An adapter answers "is this my URL, and what is it?" and may optionally own the
download. Returning None always means "not my job, fall through" - never an
error. `generic` is the documented fallback and is not registered.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple

from app.models.schemas import MediaInfo


@dataclass(frozen=True)
class DownloadOptions:
    fmt: str  # mp3 | m4a | opus | mp4 | images
    quality: str  # "1080", "320", ...
    preset: Optional[str] = None  # edit_ready | audio_norm | audio_lossless | social_bypass
    social_bypass: bool = False
    start_time: Optional[float] = None
    end_time: Optional[float] = None


@dataclass
class DownloadContext:
    url: str
    options: DownloadOptions
    tmp_dir: str
    job_id: str
    job_store: Dict[str, Any]
    cancel_event: Optional[asyncio.Event] = None
    search_query: Optional[str] = None  # music bridge: ytsearch1 query
    music_metadata: Optional[Dict[str, Any]] = None  # tagging input


class Adapter(Protocol):
    name: str

    def matches(self, url: str) -> bool:
        ...

    async def probe(self, url: str) -> Optional[MediaInfo]:
        ...

    async def entries(self, url: str) -> Optional[List[dict]]:
        ...

    async def download(self, ctx: DownloadContext) -> Optional[Tuple[str, str]]:
        ...
