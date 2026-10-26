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
from app.services import queue_manager as queue_module
from app.services.extractor import (
    AUDIO_FILENAME_TEMPLATES,
    _build_ydl_opts,
    classify_error,
    diagnostic_message,
)
from app.services.queue_manager import QueueItem, QueueManager, queue_mgr
from app.services.storage import cleanup_old_files


class TestTempCleanup(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_keeps_part_files_for_resume(self):
        with tempfile.TemporaryDirectory(prefix="ud_cleanup_") as tmp_dir:
            part_path = os.path.join(tmp_dir, "job.mp4.part")
            stale_path = os.path.join(tmp_dir, "other.mp4")
            for path in (part_path, stale_path):
                with open(path, "wb") as f:
                    f.write(b"x")
                os.utime(path, (0, 0))

            await cleanup_old_files(tmp_dir, max_age_minutes=15)

            self.assertTrue(os.path.exists(part_path))
            self.assertFalse(os.path.exists(stale_path))


class TestErrorDiagnostics(unittest.TestCase):
    def test_403_maps_to_auth_code_with_settings_hint(self):
        message = "ERROR: unable to download video: HTTP Error 403: Forbidden"
        self.assertEqual(classify_error(message), "AUTH_403")
        code, user_message = diagnostic_message(message)
        self.assertEqual(code, "AUTH_403")
        self.assertIn("Browser Cookies", user_message)
        self.assertIn("Settings", user_message)

    def test_cookie_and_private_hints_map_to_cookie_required(self):
        for message in (
            "Sign in to confirm your age",
            "This video is private",
            "Use cookies to access this post",
        ):
            with self.subTest(message=message):
                self.assertEqual(classify_error(message), "COOKIE_REQUIRED")

    def test_rate_limit_maps_to_rate_limit(self):
        self.assertEqual(classify_error("HTTP Error 429: Too Many Requests"), "RATE_LIMIT")
        self.assertEqual(classify_error("rate limit exceeded"), "RATE_LIMIT")

    def test_transient_network_failures(self):
        for message in (
            "Read timed out",
            "connection reset by peer",
            "HTTP Error 502: Bad Gateway",
            "Temporary failure in name resolution",
        ):
            with self.subTest(message=message):
                self.assertEqual(classify_error(message), "NETWORK_TRANSIENT")

    def test_unsupported_url(self):
        self.assertEqual(classify_error("Unsupported URL: https://example.com"), "UNSUPPORTED_URL")
        self.assertEqual(classify_error("No video formats found!"), "UNSUPPORTED_URL")

    def test_unknown_keeps_cleaned_message(self):
        code, user_message = diagnostic_message("ERROR: something odd happened")
        self.assertEqual(code, "UNKNOWN")
        self.assertEqual(user_message, "something odd happened")


class TestResumeOptions(unittest.TestCase):
    def test_ydl_opts_continue_partial_download(self):
        opts = _build_ydl_opts("mp4", "1080", "%(id)s.%(ext)s", lambda _d: None)
        self.assertTrue(opts["continuedl"])


class TestQueueConcurrency(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ud_queue_conc_")
        self.tmp_patch = unittest.mock.patch.object(queue_module, "TMP_DIR", self.temp_dir)
        self.tmp_patch.start()
        self.history_patch = unittest.mock.patch.object(queue_module.history_store, "add")
        self.history_patch.start()
        self.queue = QueueManager(max_concurrent=2)
        self.queue.save_dir = self.temp_dir

    def tearDown(self):
        self.history_patch.stop()
        self.tmp_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_set_max_concurrent_accepts_every_value_from_one_to_five(self):
        for value in range(1, 6):
            with self.subTest(value=value):
                self.queue.set_max_concurrent(value)
                self.assertEqual(self.queue.max_concurrent, value)

    def test_set_max_concurrent_rejects_out_of_range(self):
        self.queue.set_max_concurrent(2)
        for value in (0, 6, -1):
            with self.subTest(value=value):
                self.queue.set_max_concurrent(value)
                self.assertEqual(self.queue.max_concurrent, 2)

    async def test_semaphore_limits_active_downloads(self):
        release = asyncio.Event()
        running = 0
        peak = 0

        async def fake_download(*args, **kwargs):
            nonlocal running, peak
            job_id = args[5]
            running += 1
            peak = max(peak, running)
            await release.wait()
            running -= 1
            path = os.path.join(self.temp_dir, f"{job_id}.mp4")
            with open(path, "wb") as f:
                f.write(b"video")
            return path, "Clip"

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=fake_download
        ):
            for index in range(3):
                self.queue.add(f"https://example.com/video/{index}", title=f"Clip {index}")

            await self._wait_until(lambda: running == 2)
            await asyncio.sleep(0.05)
            self.assertEqual(running, 2)
            self.assertEqual(peak, 2)
            self.assertEqual(
                sum(1 for item in self.queue.items.values() if item.status == "downloading"),
                2,
            )

            release.set()
            await self._wait_until(
                lambda: all(item.status == "completed" for item in self.queue.items.values())
            )

        self.assertEqual(peak, 2)

    async def _wait_until(self, predicate, timeout=3.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() > deadline:
                raise AssertionError("Timed out waiting for queue condition")
            await asyncio.sleep(0.01)


class TestQueueLifecycle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ud_queue_life_")
        self.tmp_patch = unittest.mock.patch.object(queue_module, "TMP_DIR", self.temp_dir)
        self.tmp_patch.start()
        self.queue = QueueManager(max_concurrent=2)
        self.queue.save_dir = self.temp_dir

    def tearDown(self):
        self.tmp_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def add_item(self, status="queued", **overrides):
        item = QueueItem(
            id=overrides.pop("id", "job-1"),
            url="https://example.com/video",
            title="Clip",
            status=status,
            **overrides,
        )
        self.queue.items[item.id] = item
        self.queue._cancel_events[item.id] = asyncio.Event()
        return item

    async def test_pause_queued_sets_paused_and_resume_requeues(self):
        item = self.add_item(status="queued")

        self.assertFalse(await self.queue.pause("missing"))
        self.assertTrue(await self.queue.pause(item.id))
        self.assertEqual(item.status, "paused")

        with unittest.mock.patch.object(self.queue, "start_worker") as start_worker:
            self.assertFalse(await self.queue.resume("missing"))
            self.assertTrue(await self.queue.resume(item.id))

        self.assertEqual(item.status, "queued")
        self.assertIsNone(item.error)
        self.assertIsNone(item.error_code)
        self.assertIsInstance(self.queue._cancel_events[item.id], asyncio.Event)
        start_worker.assert_called_once()

    async def test_pause_downloading_keeps_part_file(self):
        item = self.add_item(status="queued")
        started = asyncio.Event()
        part_path = os.path.join(self.temp_dir, f"{item.id}.mp4.part")

        async def fake_download(*args, **kwargs):
            with open(part_path, "wb") as f:
                f.write(b"partial")
            started.set()
            cancel_event = kwargs["cancel_event"]
            while not cancel_event.is_set():
                await asyncio.sleep(0.01)
            raise RuntimeError("Cancelled by user")

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=fake_download
        ):
            task = asyncio.create_task(self.queue._worker(item.id))
            await asyncio.wait_for(started.wait(), timeout=2)
            self.assertTrue(await self.queue.pause(item.id))
            await asyncio.wait_for(task, timeout=2)

        self.assertEqual(item.status, "paused")
        self.assertEqual(item.speed, 0)
        self.assertIsNone(item.error)
        self.assertIsNone(item.error_code)
        self.assertIn(item.id, self.queue.items)
        self.assertTrue(os.path.exists(part_path))
        self.assertNotIn(item.id, self.queue._pause_requests)

    async def test_pause_wins_over_transient_retry(self):
        item = self.add_item(status="queued")
        attempts = 0
        started = asyncio.Event()

        async def fake_download(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            started.set()
            while not kwargs["cancel_event"].is_set():
                await asyncio.sleep(0.01)
            raise RuntimeError("HTTP Error 502: Bad Gateway")

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=fake_download
        ):
            task = asyncio.create_task(self.queue._worker(item.id))
            await asyncio.wait_for(started.wait(), timeout=2)
            self.assertTrue(await self.queue.pause(item.id))
            await asyncio.wait_for(task, timeout=2)

        self.assertEqual(item.status, "paused")
        self.assertEqual(attempts, 1)
        self.assertEqual(item.retry_count, 0)

    async def test_retry_only_from_error_resets_state(self):
        item = self.add_item(
            status="error",
            progress=42.0,
            filename="C:\\Downloads\\old.mp4",
            error="403 Forbidden",
            error_code="AUTH_403",
            retry_count=2,
        )

        with unittest.mock.patch.object(self.queue, "start_worker") as start_worker:
            self.assertFalse(await self.queue.retry("missing"))
            self.assertTrue(await self.queue.retry(item.id))

        self.assertEqual(item.status, "queued")
        self.assertEqual(item.progress, 0.0)
        self.assertIsNone(item.filename)
        self.assertIsNone(item.error)
        self.assertIsNone(item.error_code)
        self.assertEqual(item.retry_count, 0)
        self.assertIsInstance(self.queue._cancel_events[item.id], asyncio.Event)
        start_worker.assert_called_once()

    async def test_clear_finished_removes_completed_and_done_only(self):
        self.add_item(status="completed", id="completed")
        self.add_item(status="done", id="done")
        self.add_item(status="error", id="error")
        self.add_item(status="queued", id="queued")
        self.add_item(status="paused", id="paused")

        cleared = await self.queue.clear_finished()

        self.assertEqual(cleared, 2)
        self.assertEqual(set(self.queue.items), {"error", "queued", "paused"})

    async def test_transient_error_retries_twice_then_fails(self):
        item = self.add_item(status="queued")
        attempts = 0

        async def fake_download(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("HTTP Error 502: Bad Gateway")

        async def fast_sleep(_delay):
            return None

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=fake_download
        ), unittest.mock.patch.object(queue_module.asyncio, "sleep", side_effect=fast_sleep):
            await asyncio.wait_for(self.queue._worker(item.id), timeout=3)

        self.assertEqual(attempts, 3)
        self.assertEqual(item.status, "error")
        self.assertEqual(item.error_code, "NETWORK_TRANSIENT")
        self.assertEqual(item.retry_count, 2)
        self.assertIn("Network problem", item.error)

    async def test_transient_error_succeeds_on_retry(self):
        item = self.add_item(status="queued")
        attempts = 0

        async def fake_download(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("Read timed out")
            path = os.path.join(self.temp_dir, f"{item.id}.mp4")
            with open(path, "wb") as f:
                f.write(b"video")
            return path, "Clip"

        async def fast_sleep(_delay):
            return None

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=fake_download
        ), unittest.mock.patch.object(queue_module.asyncio, "sleep", side_effect=fast_sleep), \
                unittest.mock.patch.object(queue_module.history_store, "add"):
            await asyncio.wait_for(self.queue._worker(item.id), timeout=3)

        self.assertEqual(attempts, 2)
        self.assertEqual(item.status, "completed")
        self.assertEqual(item.retry_count, 1)
        self.assertIsNone(item.error_code)


class TestQueueDefaults(unittest.TestCase):
    def test_default_concurrency_is_three(self):
        self.assertEqual(QueueManager().max_concurrent, 3)


class TestQueueAudioDestinations(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ud_queue_audio_")
        self.tmp_patch = unittest.mock.patch.object(
            queue_module, "TMP_DIR", self.temp_dir
        )
        self.tmp_patch.start()
        self.history_patch = unittest.mock.patch.object(queue_module.history_store, "add")
        self.history_patch.start()
        self.queue = QueueManager()
        self.queue.save_dir = self.temp_dir
        self.calls = []

    def tearDown(self):
        self.history_patch.stop()
        self.tmp_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def add_audio_item(self, **overrides):
        values = {
            "id": "job-audio",
            "url": "https://open.spotify.com/track/abc",
            "format": "mp3",
            "quality": "320",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "playlist_title": "Road Trip: 2026",
            "track_number": 1,
            "search_query": "Artist - Song official audio",
            "thumbnail": "https://example.com/cover.jpg",
        }
        values.update(overrides)
        item = QueueItem(**values)
        self.queue.items[item.id] = item
        self.queue._cancel_events[item.id] = asyncio.Event()
        return item

    def fake_download(self, job_id: str):
        async def fake(*args, **kwargs):
            self.calls.append(kwargs)
            path = os.path.join(self.temp_dir, f"{job_id}.mp3")
            with open(path, "wb") as f:
                f.write(b"audio")
            return path, "Matched video title"

        return fake

    async def test_playlist_item_lands_in_sanitized_subfolder(self):
        item = self.add_audio_item()

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=self.fake_download(item.id)
        ):
            await self.queue._worker(item.id)

        expected = os.path.join(
            self.temp_dir, "Road Trip 2026", "01 - Artist - Song.mp3"
        )
        self.assertEqual(item.status, "completed")
        self.assertEqual(item.filename, expected)
        self.assertTrue(os.path.exists(expected))

    async def test_save_in_subfolder_false_writes_directly_to_save_dir(self):
        item = self.add_audio_item(save_in_subfolder=False)

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=self.fake_download(item.id)
        ):
            await self.queue._worker(item.id)

        expected = os.path.join(self.temp_dir, "01 - Artist - Song.mp3")
        self.assertEqual(item.filename, expected)
        self.assertTrue(os.path.exists(expected))
        self.assertFalse(os.path.isdir(os.path.join(self.temp_dir, "Road Trip 2026")))

    async def test_music_metadata_and_search_query_reach_download_media(self):
        item = self.add_audio_item(playlist_title=None, save_in_subfolder=False)

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=self.fake_download(item.id)
        ):
            await self.queue._worker(item.id)

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["search_query"], "Artist - Song official audio")
        metadata = self.calls[0]["music_metadata"]
        self.assertEqual(metadata["title"], "Song")
        self.assertEqual(metadata["artist"], "Artist")
        self.assertEqual(metadata["album"], "Album")
        self.assertEqual(metadata["track_number"], 1)
        self.assertEqual(metadata["thumbnail"], "https://example.com/cover.jpg")


    async def test_thumbnail_only_does_not_tag_video_jobs(self):
        item = self.add_audio_item(
            format="mp4",
            title="Video",
            artist=None,
            album=None,
            search_query=None,
            playlist_title=None,
            thumbnail="https://example.com/thumb.jpg",
        )

        with unittest.mock.patch.object(
            queue_module, "download_media", side_effect=self.fake_download(item.id)
        ):
            await self.queue._worker(item.id)

        self.assertIsNone(self.calls[0]["music_metadata"])
        self.assertIsNone(self.calls[0]["search_query"])


class TestQueueApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_token = "queue-session-token-12345"
        self.old_token = os.environ.get("APP_SESSION_TOKEN")
        os.environ["APP_SESSION_TOKEN"] = self.test_token

        self.old_save_dir = queue_mgr.save_dir
        queue_mgr.save_dir = tempfile.mkdtemp(prefix="ud_queue_api_")
        self.old_max_concurrent = queue_mgr.max_concurrent
        self.old_audio_filename_template = queue_mgr.audio_filename_template
        self.old_items = queue_mgr.items
        self.old_events = queue_mgr._cancel_events
        self.old_tasks = queue_mgr._worker_tasks
        queue_mgr.items = {}
        queue_mgr._cancel_events = {}
        queue_mgr._worker_tasks = {}

    def tearDown(self):
        if self.old_token is not None:
            os.environ["APP_SESSION_TOKEN"] = self.old_token
        else:
            os.environ.pop("APP_SESSION_TOKEN", None)
        shutil.rmtree(queue_mgr.save_dir, ignore_errors=True)
        queue_mgr.save_dir = self.old_save_dir
        queue_mgr.max_concurrent = self.old_max_concurrent
        queue_mgr.audio_filename_template = self.old_audio_filename_template
        queue_mgr._semaphore = asyncio.Semaphore(self.old_max_concurrent)
        queue_mgr.items = self.old_items
        queue_mgr._cancel_events = self.old_events
        queue_mgr._worker_tasks = self.old_tasks

    def _item(self, job_id: str, status: str) -> QueueItem:
        item = QueueItem(id=job_id, url="https://example.com/video", status=status)
        queue_mgr.items[job_id] = item
        queue_mgr._cancel_events[job_id] = asyncio.Event()
        return item

    async def test_pause_resume_retry_and_clear_finished_routes(self):
        paused_item = self._item("pause-me", "queued")
        failed_item = self._item("retry-me", "error")
        self._item("clear-me", "completed")

        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        with unittest.mock.patch.object(queue_mgr, "start_worker"):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8000"
            ) as client:
                r_pause = await client.post("/api/queue/pause-me/pause", headers=headers)
                self.assertEqual(r_pause.status_code, 200)
                self.assertEqual(r_pause.json(), {"paused": True, "job_id": "pause-me"})
                self.assertEqual(paused_item.status, "paused")

                r_resume = await client.post("/api/queue/pause-me/resume", headers=headers)
                self.assertEqual(r_resume.status_code, 200)
                self.assertEqual(r_resume.json(), {"resumed": True, "job_id": "pause-me"})
                self.assertEqual(paused_item.status, "queued")

                r_retry = await client.post("/api/queue/retry-me/retry", headers=headers)
                self.assertEqual(r_retry.status_code, 200)
                self.assertEqual(r_retry.json(), {"retried": True, "job_id": "retry-me"})
                self.assertEqual(failed_item.status, "queued")

                r_clear = await client.post("/api/queue/clear-finished", headers=headers)
                self.assertEqual(r_clear.status_code, 200)
                self.assertEqual(r_clear.json(), {"cleared": 1})

                for action in ("pause", "resume", "retry"):
                    with self.subTest(action=action):
                        r_missing = await client.post(
                            f"/api/queue/missing/{action}", headers=headers
                        )
                        self.assertEqual(r_missing.status_code, 404)

    async def test_settings_accepts_every_concurrency_from_one_to_five(self):
        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            for value in range(1, 6):
                with self.subTest(value=value):
                    r = await client.post(
                        "/api/settings",
                        json={"max_concurrent": value},
                        headers=headers,
                    )
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(r.json()["max_concurrent"], value)

            for value in (0, 6):
                with self.subTest(value=value):
                    r_bad = await client.post(
                        "/api/settings",
                        json={"max_concurrent": value},
                        headers=headers,
                    )
                    self.assertEqual(r_bad.status_code, 400)

    async def test_audio_filename_template_roundtrip_and_validation(self):
        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        queue_mgr.audio_filename_template = "{artist} - {title}"
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            r_default = await client.get("/api/settings")
            self.assertEqual(r_default.status_code, 200)
            self.assertEqual(
                r_default.json()["audio_filename_template"], "{artist} - {title}"
            )

            chosen = AUDIO_FILENAME_TEMPLATES[3]
            r_ok = await client.post(
                "/api/settings",
                json={"audio_filename_template": chosen},
                headers=headers,
            )
            self.assertEqual(r_ok.status_code, 200)
            self.assertEqual(r_ok.json()["audio_filename_template"], chosen)

            r_get = await client.get("/api/settings")
            self.assertEqual(r_get.json()["audio_filename_template"], chosen)

            r_bad = await client.post(
                "/api/settings",
                json={"audio_filename_template": "{unknown}"},
                headers=headers,
            )
            self.assertEqual(r_bad.status_code, 400)
            self.assertEqual(queue_mgr.audio_filename_template, chosen)


if __name__ == "__main__":
    unittest.main()
