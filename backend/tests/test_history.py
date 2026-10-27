import os
import sys
import asyncio
import shutil
import tempfile
import unittest
import unittest.mock

import httpx

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.main import app
from app.services.history_store import HistoryStore, history_store
from app.services.queue_manager import QueueItem, QueueManager


def make_entry(item_id: str, **overrides) -> dict:
    entry = {
        "id": item_id,
        "url": f"https://www.youtube.com/watch?v={item_id}",
        "title": f"Video {item_id}",
        "format": "mp4",
        "quality": "1080",
        "platform": "Youtube",
        "filename": f"C:\\Downloads\\{item_id}.mp4",
        "completedAt": 1700000000000,
        "start_time": None,
        "end_time": None,
        "preset": None,
        "social_bypass": False,
    }
    entry.update(overrides)
    return entry


class TestHistoryStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ud_history_")
        self.history_file = os.path.join(self.temp_dir, "history.json")
        self.old_file = os.environ.get("UD_HISTORY_FILE")
        os.environ["UD_HISTORY_FILE"] = self.history_file

    def tearDown(self):
        if self.old_file is not None:
            os.environ["UD_HISTORY_FILE"] = self.old_file
        else:
            os.environ.pop("UD_HISTORY_FILE", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_list_delete_clear_round_trip(self):
        store = HistoryStore()
        self.assertEqual(store.count(), 0)

        store.add(make_entry("a"))
        store.add(make_entry("b"))

        self.assertEqual([item["id"] for item in store.list()], ["b", "a"])
        self.assertEqual(store.count(), 2)

        self.assertTrue(store.delete("a"))
        self.assertFalse(store.delete("missing"))
        self.assertEqual([item["id"] for item in store.list()], ["b"])

        self.assertEqual(store.clear(), 1)
        self.assertEqual(store.list(), [])
        self.assertEqual(store.count(), 0)

    def test_persists_across_new_store_instance(self):
        HistoryStore().add(make_entry("persisted"))

        self.assertEqual([item["id"] for item in HistoryStore().list()], ["persisted"])

    def test_corrupt_file_is_tolerated_and_entries_are_capped(self):
        with open(self.history_file, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        store = HistoryStore()
        self.assertEqual(store.list(), [])

        for i in range(205):
            store.add(make_entry(f"id-{i}"))

        self.assertEqual(store.count(), 200)
        self.assertEqual(len(store.list()), 200)


class TestHistoryApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_token = "history-session-token-12345"
        self.old_token = os.environ.get("APP_SESSION_TOKEN")
        os.environ["APP_SESSION_TOKEN"] = self.test_token

        self.temp_dir = tempfile.mkdtemp(prefix="ud_history_api_")
        self.old_file = os.environ.get("UD_HISTORY_FILE")
        os.environ["UD_HISTORY_FILE"] = os.path.join(self.temp_dir, "history.json")
        history_store.clear()

    def tearDown(self):
        if self.old_token is not None:
            os.environ["APP_SESSION_TOKEN"] = self.old_token
        else:
            os.environ.pop("APP_SESSION_TOKEN", None)

        if self.old_file is not None:
            os.environ["UD_HISTORY_FILE"] = self.old_file
        else:
            os.environ.pop("UD_HISTORY_FILE", None)

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_get_delete_and_clear_history(self):
        history_store.add(make_entry("one", platform="YouTube"))
        history_store.add(make_entry("two", platform="Twitter", format="mp3"))

        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            r_get = await client.get("/api/history", headers=headers)
            self.assertEqual(r_get.status_code, 200)
            self.assertEqual([item["id"] for item in r_get.json()["items"]], ["two", "one"])

            r_delete = await client.delete("/api/history/two", headers=headers)
            self.assertEqual(r_delete.status_code, 200)
            self.assertEqual(r_delete.json(), {"deleted": True, "id": "two"})

            r_missing = await client.delete("/api/history/two", headers=headers)
            self.assertEqual(r_missing.status_code, 404)
            self.assertEqual(r_missing.json()["detail"], "History item not found")

            r_clear = await client.delete("/api/history", headers=headers)
            self.assertEqual(r_clear.status_code, 200)
            self.assertEqual(r_clear.json(), {"cleared": 1})

            r_empty = await client.get("/api/history", headers=headers)
            self.assertEqual(r_empty.json(), {"items": []})

    async def test_delete_without_token_is_forbidden(self):
        history_store.add(make_entry("protected"))

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            r = await client.delete("/api/history/protected")
            self.assertEqual(r.status_code, 403)
            self.assertEqual(history_store.count(), 1)


class TestQueueHistoryRecording(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ud_queue_history_")
        self.old_file = os.environ.get("UD_HISTORY_FILE")
        os.environ["UD_HISTORY_FILE"] = os.path.join(self.temp_dir, "history.json")
        history_store.clear()
        self.queue = QueueManager()
        self.queue.save_dir = self.temp_dir

    def tearDown(self):
        if self.old_file is not None:
            os.environ["UD_HISTORY_FILE"] = self.old_file
        else:
            os.environ.pop("UD_HISTORY_FILE", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_completed_download_is_recorded(self):
        item = QueueItem(
            id="job-1",
            url="https://www.youtube.com/watch?v=abc",
            format="mp4",
            quality="1080",
            title="Clip",
            platform="Youtube",
            preset="best",
            social_bypass=True,
        )
        self.queue.items[item.id] = item
        self.queue._cancel_events[item.id] = asyncio.Event()
        temp_file = os.path.join(self.temp_dir, "partial.mp4")
        with open(temp_file, "wb") as f:
            f.write(b"video")

        async def fake_download(*args, **kwargs):
            return temp_file, "Clip"

        with unittest.mock.patch(
            "app.services.queue_manager.download_media", side_effect=fake_download
        ):
            await self.queue._worker(item.id)

        self.assertEqual(item.status, "completed")
        records = history_store.list()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["id"], item.id)
        self.assertEqual(record["title"], "Clip")
        self.assertEqual(record["platform"], "Youtube")
        self.assertEqual(record["filename"], os.path.join(self.temp_dir, "Clip.mp4"))
        self.assertIsInstance(record["completedAt"], int)
        self.assertTrue(record["social_bypass"])
        self.assertEqual(record["preset"], "best")

    async def test_failed_download_is_recorded_without_a_filename(self):
        item = QueueItem(
            id="job-fail",
            url="https://www.instagram.com/p/gated/",
            format="mp4",
            quality="1080",
            title="Gated post",
            platform="Instagram",
        )
        self.queue.items[item.id] = item
        self.queue._cancel_events[item.id] = asyncio.Event()

        async def fake_download(*args, **kwargs):
            raise ValueError("ERROR: 403 Forbidden")

        with unittest.mock.patch(
            "app.services.queue_manager.download_media", side_effect=fake_download
        ):
            await self.queue._worker(item.id)

        self.assertEqual(item.status, "error")
        records = history_store.list()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error_code"], "AUTH_403")
        self.assertIsNone(record["filename"])

    async def test_deleting_a_history_record_never_deletes_the_file(self):
        library_file = os.path.join(self.temp_dir, "keep-me.mp4")
        with open(library_file, "wb") as fh:
            fh.write(b"still here")
        history_store.add(
            {
                "id": "job-keep",
                "url": "https://example.com/v",
                "title": "Keep",
                "format": "mp4",
                "quality": "1080",
                "filename": library_file,
                "completedAt": 1,
                "status": "completed",
            }
        )

        self.assertTrue(history_store.delete("job-keep"))

        self.assertEqual(history_store.list(), [])
        self.assertTrue(os.path.isfile(library_file))
