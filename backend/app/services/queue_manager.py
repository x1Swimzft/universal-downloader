import os
import json
import uuid
import asyncio
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Set

from app.services.extractor import download_media

TMP_DIR = os.environ.get("TMP_DIR", os.path.join(os.path.dirname(__file__), "../../tmp"))


@dataclass
class QueueItem:
    id: str
    url: str
    format: str = "mp4"
    quality: str = "720"
    title: Optional[str] = None
    status: str = "queued"  # queued | downloading | completed | error
    progress: float = 0.0
    filename: Optional[str] = None
    error: Optional[str] = None


class QueueManager:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._semaphore: Optional[asyncio.Semaphore] = None
        self.items: Dict[str, QueueItem] = {}
        self.external_task_store: Dict[str, Any] = {}
        self._subscribers: Set[asyncio.Queue] = set()
        self._running_jobs: Set[str] = set()

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    def add(
        self,
        url: str,
        fmt: str = "mp4",
        quality: str = "720",
        title: Optional[str] = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        item = QueueItem(
            id=job_id,
            url=url,
            format=fmt,
            quality=quality,
            title=title or url,
            status="queued",
            progress=0.0,
        )
        self.items[job_id] = item
        self.start_worker()
        return job_id

    def start_worker(self):
        for jid, item in list(self.items.items()):
            if item.status == "queued" and jid not in self._running_jobs:
                self._running_jobs.add(jid)
                asyncio.create_task(self._worker(jid))

    async def _worker(self, job_id: str):
        async with self.semaphore:
            item = self.items.get(job_id)
            if not item:
                self._running_jobs.discard(job_id)
                return

            item.status = "downloading"
            item.progress = 0.0
            await self.broadcast()

            tmp_store: Dict[str, Any] = {job_id: {"progress": 0.0}}
            stop_polling = asyncio.Event()

            async def _poll_progress():
                while not stop_polling.is_set():
                    if job_id in tmp_store:
                        item.progress = float(tmp_store[job_id].get("progress", 0.0))
                        await self.broadcast()
                    try:
                        await asyncio.wait_for(stop_polling.wait(), timeout=0.4)
                    except asyncio.TimeoutError:
                        pass

            poll_task = asyncio.create_task(_poll_progress())

            try:
                os.makedirs(TMP_DIR, exist_ok=True)
                filepath, extracted_title = await download_media(
                    item.url, item.format, item.quality, TMP_DIR, tmp_store, job_id
                )
                if not item.title or item.title == item.url:
                    item.title = extracted_title
                item.status = "completed"
                item.progress = 100.0
                item.filename = filepath
                item.error = None

                if self.external_task_store is not None:
                    self.external_task_store[job_id] = {
                        "status": "done",
                        "progress": 100.0,
                        "filename": filepath,
                        "title": item.title,
                        "format": "mp3" if item.format == "mp3" else "mp4",
                        "error": None,
                    }
            except Exception as e:
                item.status = "error"
                item.error = str(e)
                if self.external_task_store is not None:
                    self.external_task_store[job_id] = {
                        "status": "error",
                        "progress": item.progress,
                        "filename": None,
                        "title": item.title,
                        "format": "mp3" if item.format == "mp3" else "mp4",
                        "error": str(e),
                    }
            finally:
                stop_polling.set()
                await poll_task
                self._running_jobs.discard(job_id)
                await self.broadcast()

    async def broadcast(self):
        if not self._subscribers:
            return
        payload = json.dumps([asdict(item) for item in self.items.values()])
        msg = f"data: {payload}\n\n"
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    async def subscribe(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        try:
            initial = json.dumps([asdict(item) for item in self.items.values()])
            yield f"data: {initial}\n\n"
            while True:
                msg = await q.get()
                yield msg
        finally:
            self._subscribers.discard(q)


queue_mgr = QueueManager(max_concurrent=3)
