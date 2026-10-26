import json
import os
import tempfile
import threading

MAX_ENTRIES = 200


def _default_path() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        return os.path.join(local_app_data, "UniversalDownloader", "history.json")
    return os.path.join(os.path.expanduser("~"), ".universal-downloader", "history.json")


def _history_path() -> str:
    return os.environ.get("UD_HISTORY_FILE") or _default_path()


class HistoryStore:
    """Small JSON-backed history file, newest entry first."""

    def __init__(self):
        self._lock = threading.Lock()

    def _read(self, path: str) -> list[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _write(self, path: str, items: list[dict]):
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".history-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def add(self, entry: dict):
        with self._lock:
            path = _history_path()
            items = [entry, *self._read(path)][:MAX_ENTRIES]
            self._write(path, items)

    def list(self) -> list[dict]:
        with self._lock:
            return self._read(_history_path())

    def delete(self, item_id: str) -> bool:
        with self._lock:
            path = _history_path()
            items = self._read(path)
            remaining = [item for item in items if item.get("id") != item_id]
            if len(remaining) == len(items):
                return False
            self._write(path, remaining)
            return True

    def clear(self) -> int:
        with self._lock:
            path = _history_path()
            items = self._read(path)
            if items:
                self._write(path, [])
            return len(items)

    def count(self) -> int:
        with self._lock:
            return len(self._read(_history_path()))


history_store = HistoryStore()
