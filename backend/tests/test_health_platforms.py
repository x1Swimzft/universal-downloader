import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.api import health_platforms
from app.models.schemas import MediaInfo


def _info(title):
    return MediaInfo(title=title, platform="test", formats=[], media_type="video")


class TestPlatformHealth(unittest.IsolatedAsyncioTestCase):
    async def test_all_platforms_report_ok(self):
        probe = AsyncMock(side_effect=lambda url: _info(url.rsplit("/", 1)[-1]))
        with patch.object(health_platforms.extractor, "extract_info", probe):
            payload = await health_platforms.platform_health()

        self.assertEqual(
            [r["platform"] for r in payload["results"]],
            ["tiktok", "instagram", "youtube"],
        )
        self.assertTrue(all(r["ok"] for r in payload["results"]))
        self.assertTrue(all(isinstance(r["duration_ms"], int) for r in payload["results"]))

    async def test_failure_carries_a_code_without_hiding_other_results(self):
        calls = {"n": 0}

        async def flaky(url):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("ERROR: 403 Forbidden")
            return _info("fine")

        with patch.object(health_platforms.extractor, "extract_info", flaky):
            payload = await health_platforms.platform_health()

        by_platform = {r["platform"]: r for r in payload["results"]}
        self.assertFalse(by_platform["tiktok"]["ok"])
        self.assertEqual(by_platform["tiktok"]["error_code"], "AUTH_403")
        self.assertTrue(by_platform["instagram"]["ok"])
        self.assertTrue(by_platform["youtube"]["ok"])

    async def test_timeout_is_reported_as_network(self):
        async def slow(_url):
            return _info("never")

        async def fake_wait_for(coro, timeout):
            coro.close()  # avoid an un-awaited coroutine warning
            raise TimeoutError

        with patch.object(
            health_platforms.extractor, "extract_info", slow
        ), patch.object(health_platforms.asyncio, "wait_for", fake_wait_for):
            payload = await health_platforms.platform_health()

        self.assertTrue(all(r["error_code"] == "NETWORK_TRANSIENT" for r in payload["results"]))
        self.assertFalse(any(r["ok"] for r in payload["results"]))


if __name__ == "__main__":
    unittest.main()
