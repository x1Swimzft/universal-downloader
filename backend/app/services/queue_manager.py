import os
import re
import json
import uuid
import shutil
import asyncio
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Set

from app.services.extractor import download_media, _extract_platform

TMP_DIR = os.environ.get("TMP_DIR", os.path.join(os.path.dirname(__file__), "../../tmp"))
DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "Universal Downloader")


def _normalize_windows_path(path_str: str) -> str:
    """Strip extended device prefixes (\\?\\ or \\.\\) for standard DOS drives and canonicalize."""
    if not path_str or not isinstance(path_str, str):
        return ""
    p = path_str.strip()
    m = re.match(r'^(?:\\\\|\/\/)(?:\?|\.)[\/\\]([a-zA-Z]:.*)', p)
    if m:
        p = m.group(1)
    return os.path.normcase(os.path.realpath(p))


def is_allowed_path(target_path: str, allowed_root: str) -> bool:
    if not target_path or not allowed_root:
        return False
    # Reject remote UNC network paths
    if target_path.strip().startswith(("\\\\", "//")):
        if not re.match(r'^(?:\\\\|\/\/)(?:\?|\.)[\/\\][a-zA-Z]:', target_path.strip()):
            return False
    if allowed_root.strip().startswith(("\\\\", "//")):
        if not re.match(r'^(?:\\\\|\/\/)(?:\?|\.)[\/\\][a-zA-Z]:', allowed_root.strip()):
            return False

    real_target = _normalize_windows_path(target_path)
    real_root = _normalize_windows_path(allowed_root)
    if not real_target or not real_root:
        return False
    return real_target == real_root or real_target.startswith(real_root + os.sep)


def is_safe_save_dir(folder: str) -> tuple[bool, str]:
    if not folder or not isinstance(folder, str):
        return False, "Save folder must be an absolute path"

    cleaned = folder.strip()

    # Reject remote UNC network paths
    if cleaned.startswith(("\\\\", "//")):
        if not re.match(r'^(?:\\\\|\/\/)(?:\?|\.)[\/\\][a-zA-Z]:[\\\/]', cleaned):
            return False, "Network / UNC paths are not allowed as save folder"

    # Reject drive-relative or non-absolute paths
    norm_for_abs = cleaned
    m = re.match(r'^(?:\\\\|\/\/)(?:\?|\.)[\/\\]([a-zA-Z]:.*)', norm_for_abs)
    if m:
        norm_for_abs = m.group(1)
    if not os.path.isabs(norm_for_abs):
        return False, "Save folder must be an absolute path"

    real = _normalize_windows_path(cleaned)

    # Reject drive roots (e.g., C:\, D:\, C:, /)
    drive, tail = os.path.splitdrive(real)
    if not tail or tail.strip(os.sep) == "":
        return False, "Cannot use drive root as save folder"

    # Reject critical Windows/system directories
    forbidden_dirs = [
        os.environ.get("SystemRoot", r"C:\Windows"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramData", r"C:\ProgramData"),
        r"C:\Windows",
        r"C:\Windows\System32",
    ]
    for fdir in forbidden_dirs:
        if fdir:
            f_real = _normalize_windows_path(fdir)
            if real == f_real or real.startswith(f_real + os.sep):
                return False, f"Cannot use system directory as save folder: {fdir}"

    # Verify folder is writable
    try:
        os.makedirs(real, exist_ok=True)
        test_file = os.path.join(real, f".write_test_{uuid.uuid4().hex}")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_file)
    except Exception as e:
        return False, f"Save folder is not writable: {str(e)}"

    return True, ""


def safe_filename(title: str, ext: str) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    if not safe:
        safe = "download"
    return f"{safe}.{ext}"


@dataclass
class QueueItem:
    id: str
    url: str
    format: str = "mp4"
    quality: str = "1080"
    title: Optional[str] = None
    platform: str = "Web"
    status: str = "queued"  # queued | downloading | completed | error
    progress: float = 0.0
    speed: float = 0.0
    filename: Optional[str] = None
    error: Optional[str] = None


class QueueManager:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.save_dir = os.path.realpath(DEFAULT_SAVE_DIR)
        self.items: Dict[str, QueueItem] = {}
        self.external_task_store: Dict[str, Any] = {}
        self._subscribers: Set[asyncio.Queue] = set()
        self._running_jobs: Set[str] = set()
        self._cancel_events: Dict[str, asyncio.Event] = {}

    def set_max_concurrent(self, value: int):
        if value in (1, 2, 3, 5):
            self.max_concurrent = value
            self.start_worker()

    def set_save_dir(self, folder: str) -> bool:
        ok, _ = is_safe_save_dir(folder)
        if ok:
            self.save_dir = os.path.realpath(folder)
            return True
        return False

    def _cleanup_tmp_files(self, job_id: str):
        if not os.path.isdir(TMP_DIR):
            return
        prefix = f"{job_id}."
        for fname in os.listdir(TMP_DIR):
            if fname.startswith(prefix):
                try:
                    os.remove(os.path.join(TMP_DIR, fname))
                except OSError:
                    pass

    def add(
        self,
        url: str,
        fmt: str = "mp4",
        quality: str = "1080",
        title: Optional[str] = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        plat = _extract_platform(url).capitalize()
        item = QueueItem(
            id=job_id,
            url=url,
            format=fmt,
            quality=quality,
            title=title or url,
            platform=plat,
            status="queued",
            progress=0.0,
            speed=0.0,
        )
        self.items[job_id] = item
        self._cancel_events[job_id] = asyncio.Event()
        self.start_worker()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast())
        except RuntimeError:
            pass
        return job_id

    async def cancel(self, job_id: str) -> bool:
        ev = self._cancel_events.get(job_id)
        if ev:
            ev.set()
        existed = job_id in self.items
        self.items.pop(job_id, None)
        self._cleanup_tmp_files(job_id)
        await self.broadcast()
        return existed

    def start_worker(self):
        for jid, item in list(self.items.items()):
            if len(self._running_jobs) >= self.max_concurrent:
                break
            if item.status == "queued" and jid not in self._running_jobs:
                self._running_jobs.add(jid)
                asyncio.create_task(self._worker(jid))

    async def _worker(self, job_id: str):
        item = self.items.get(job_id)
        cancel_event = self._cancel_events.get(job_id)
        if not item or (cancel_event and cancel_event.is_set()):
            self._running_jobs.discard(job_id)
            self._cancel_events.pop(job_id, None)
            self.start_worker()
            return

        item.status = "downloading"
        item.progress = 0.0
        item.speed = 0.0
        await self.broadcast()

        tmp_store: Dict[str, Any] = {job_id: {"progress": 0.0, "speed": 0.0}}
        stop_polling = asyncio.Event()

        async def _poll_progress():
            while not stop_polling.is_set():
                if job_id in tmp_store and job_id in self.items:
                    item.progress = float(tmp_store[job_id].get("progress", 0.0))
                    item.speed = float(tmp_store[job_id].get("speed", 0.0))
                    await self.broadcast()
                try:
                    await asyncio.wait_for(stop_polling.wait(), timeout=0.4)
                except asyncio.TimeoutError:
                    pass

        poll_task = asyncio.create_task(_poll_progress())

        try:
            os.makedirs(TMP_DIR, exist_ok=True)
            filepath, extracted_title = await download_media(
                item.url, item.format, item.quality, TMP_DIR, tmp_store, job_id, cancel_event=cancel_event
            )
            if cancel_event and cancel_event.is_set():
                self._cleanup_tmp_files(job_id)
                return

            if not item.title or item.title == item.url:
                item.title = extracted_title

            # Move completed file into configured save_dir with clean filename
            os.makedirs(self.save_dir, exist_ok=True)
            ext = os.path.splitext(filepath)[1].lstrip(".") or item.format
            clean_name = safe_filename(item.title or "download", ext)
            dest_path = os.path.join(self.save_dir, clean_name)
            base_name, ext_dot = os.path.splitext(clean_name)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(self.save_dir, f"{base_name} ({counter}){ext_dot}")
                counter += 1
            shutil.move(filepath, dest_path)

            item.status = "completed"
            item.progress = 100.0
            item.speed = 0.0
            item.filename = dest_path
            item.error = None

            if self.external_task_store is not None:
                self.external_task_store[job_id] = {
                    "status": "done",
                    "progress": 100.0,
                    "filename": dest_path,
                    "title": item.title,
                    "format": item.format,
                    "error": None,
                }
        except Exception as e:
            if cancel_event and cancel_event.is_set():
                self.items.pop(job_id, None)
                self._cleanup_tmp_files(job_id)
            elif job_id in self.items:
                item.status = "error"
                item.speed = 0.0
                item.error = str(e)
                self._cleanup_tmp_files(job_id)
                if self.external_task_store is not None:
                    self.external_task_store[job_id] = {
                        "status": "error",
                        "progress": item.progress,
                        "filename": None,
                        "title": item.title,
                        "format": item.format,
                        "error": str(e),
                    }
        finally:
            stop_polling.set()
            await poll_task
            self._running_jobs.discard(job_id)
            self._cancel_events.pop(job_id, None)
            await self.broadcast()
            self.start_worker()

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
