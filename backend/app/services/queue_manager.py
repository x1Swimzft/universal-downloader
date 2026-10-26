import os
import re
import json
import time
import uuid
import shutil
import asyncio
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Set

from app.services.extractor import download_media, _extract_platform, diagnostic_message
from app.services.history_store import history_store

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
    status: str = "queued"  # queued | downloading | paused | completed | error
    progress: float = 0.0
    speed: float = 0.0
    filename: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    retry_count: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    preset: Optional[str] = None
    social_bypass: bool = False


class QueueManager:
    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self.save_dir = os.path.realpath(DEFAULT_SAVE_DIR)
        self.items: Dict[str, QueueItem] = {}
        self.external_task_store: Dict[str, Any] = {}
        self._subscribers: Set[asyncio.Queue] = set()
        self._running_jobs: Set[str] = set()
        self._worker_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._pause_requests: Set[str] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def set_max_concurrent(self, value: int):
        if 1 <= value <= 5:
            self.max_concurrent = value
            # A new semaphore bounds new starts; downloads already running finish.
            self._semaphore = asyncio.Semaphore(value)
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
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        preset: Optional[str] = None,
        social_bypass: bool = False,
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
            start_time=start_time,
            end_time=end_time,
            preset=preset,
            social_bypass=social_bypass,
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

    async def pause(self, job_id: str) -> bool:
        item = self.items.get(job_id)
        if not item:
            return False
        if item.status == "queued":
            item.status = "paused"
            item.speed = 0.0
            await self.broadcast()
            return True
        if item.status == "downloading":
            self._pause_requests.add(job_id)
            ev = self._cancel_events.get(job_id)
            if ev:
                ev.set()
            return True
        return False

    async def resume(self, job_id: str) -> bool:
        item = self.items.get(job_id)
        if not item or item.status != "paused":
            return False
        item.status = "queued"
        item.speed = 0.0
        item.error = None
        item.error_code = None
        self._pause_requests.discard(job_id)
        self._cancel_events[job_id] = asyncio.Event()
        self.start_worker()
        await self.broadcast()
        return True

    async def retry(self, job_id: str) -> bool:
        item = self.items.get(job_id)
        if not item or item.status != "error":
            return False
        item.status = "queued"
        item.progress = 0.0
        item.speed = 0.0
        item.filename = None
        item.error = None
        item.error_code = None
        item.retry_count = 0
        self._cancel_events[job_id] = asyncio.Event()
        self.start_worker()
        await self.broadcast()
        return True

    async def clear_finished(self) -> int:
        finished = [
            jid
            for jid, item in self.items.items()
            if item.status in ("completed", "done")
        ]
        for jid in finished:
            self.items.pop(jid, None)
        if finished:
            await self.broadcast()
        return len(finished)

    def start_worker(self):
        for jid, item in list(self.items.items()):
            if item.status != "queued" or jid in self._worker_tasks:
                continue
            self._running_jobs.add(jid)
            self._worker_tasks[jid] = asyncio.create_task(self._worker(jid))

    async def _worker(self, job_id: str):
        task = asyncio.current_task()
        cancel_event: Optional[asyncio.Event] = None
        try:
            async with self._semaphore:
                item = self.items.get(job_id)
                cancel_event = self._cancel_events.get(job_id)
                if (
                    not item
                    or item.status != "queued"
                    or (cancel_event and cancel_event.is_set())
                ):
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
                    while True:
                        try:
                            os.makedirs(TMP_DIR, exist_ok=True)
                            filepath, extracted_title = await download_media(
                                item.url,
                                item.format,
                                item.quality,
                                TMP_DIR,
                                tmp_store,
                                job_id,
                                cancel_event=cancel_event,
                                start_time=item.start_time,
                                end_time=item.end_time,
                                preset=item.preset,
                                social_bypass=item.social_bypass,
                            )
                            if cancel_event and cancel_event.is_set():
                                if job_id in self._pause_requests:
                                    item.status = "paused"
                                    item.speed = 0.0
                                    item.error = None
                                    item.error_code = None
                                else:
                                    self.items.pop(job_id, None)
                                    self._cleanup_tmp_files(job_id)
                                break

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
                            item.error_code = None

                            try:
                                history_store.add(
                                    {
                                        "id": item.id,
                                        "url": item.url,
                                        "title": item.title,
                                        "format": item.format,
                                        "quality": item.quality,
                                        "platform": item.platform,
                                        "filename": item.filename,
                                        "completedAt": int(time.time() * 1000),
                                        "start_time": item.start_time,
                                        "end_time": item.end_time,
                                        "preset": item.preset,
                                        "social_bypass": item.social_bypass,
                                    }
                                )
                            except Exception:
                                # History is best-effort and must not turn a finished download into an error.
                                pass

                            if self.external_task_store is not None:
                                self.external_task_store[job_id] = {
                                    "status": "done",
                                    "progress": 100.0,
                                    "filename": dest_path,
                                    "title": item.title,
                                    "format": item.format,
                                    "error": None,
                                }
                            break
                        except Exception as e:
                            if job_id in self._pause_requests:
                                item.status = "paused"
                                item.speed = 0.0
                                item.error = None
                                item.error_code = None
                                break
                            if cancel_event and cancel_event.is_set():
                                self.items.pop(job_id, None)
                                self._cleanup_tmp_files(job_id)
                                break

                            error_code, user_message = diagnostic_message(
                                str(e), item.url
                            )
                            if error_code == "NETWORK_TRANSIENT" and item.retry_count < 2:
                                item.retry_count += 1
                                item.speed = 0.0
                                item.error = user_message
                                item.error_code = error_code
                                await self.broadcast()
                                await asyncio.sleep(2 ** (item.retry_count - 1))
                                if job_id in self._pause_requests:
                                    item.status = "paused"
                                    item.speed = 0.0
                                    item.error = None
                                    item.error_code = None
                                    break
                                if cancel_event and cancel_event.is_set():
                                    self.items.pop(job_id, None)
                                    self._cleanup_tmp_files(job_id)
                                    break
                                continue

                            item.status = "error"
                            item.speed = 0.0
                            item.error = user_message
                            item.error_code = error_code
                            self._cleanup_tmp_files(job_id)
                            if self.external_task_store is not None:
                                self.external_task_store[job_id] = {
                                    "status": "error",
                                    "progress": item.progress,
                                    "filename": None,
                                    "title": item.title,
                                    "format": item.format,
                                    "error": user_message,
                                }
                            break
                finally:
                    stop_polling.set()
                    await poll_task
                    self._running_jobs.discard(job_id)
        finally:
            self._pause_requests.discard(job_id)
            if self._worker_tasks.get(job_id) is task:
                self._worker_tasks.pop(job_id, None)
            if cancel_event is not None and self._cancel_events.get(job_id) is cancel_event:
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


queue_mgr = QueueManager(max_concurrent=2)
