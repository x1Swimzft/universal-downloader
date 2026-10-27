import os
import sys
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.api import health_platforms
from app.services import diagnostics


class TestRedaction(unittest.TestCase):
    def test_signed_query_values_are_redacted(self):
        url = "https://cdn.example/v.mp4?token=abc123&x-amz-signature=deadbeef&stp=keep"
        redacted = diagnostics.redact(url)

        self.assertNotIn("abc123", redacted)
        self.assertNotIn("deadbeef", redacted)
        self.assertIn("REDACTED", redacted)
        self.assertIn("stp=", redacted)  # parameter name survives

    def test_home_directory_becomes_a_placeholder(self):
        home = os.path.expanduser("~")
        if home in ("~", ""):
            self.skipTest("no home directory on this platform")

        redacted = diagnostics.redact(os.path.join(home, "Music", "song.mp3"))

        self.assertIn("%USERPROFILE%", redacted)
        self.assertNotIn(home, redacted)

    def test_token_headers_are_redacted(self):
        self.assertEqual(
            diagnostics.redact("X-App-Token: 0123456789abcdef"),
            "X-App-Token=REDACTED",
        )

    def test_non_strings_pass_through(self):
        self.assertEqual(diagnostics.redact(5), 5)
        self.assertIsNone(diagnostics.redact(None))


class TestCollect(unittest.TestCase):
    def test_snapshot_has_no_secrets_and_reports_the_last_health_error(self):
        health_platforms.LAST_RESULT = [
            {"platform": "tiktok", "ok": False, "error_code": "PLATFORM_CHANGED", "duration_ms": 12},
            {"platform": "youtube", "ok": True, "duration_ms": 30},
        ]
        try:
            snapshot = diagnostics.collect("0.8.0")
        finally:
            health_platforms.LAST_RESULT = []

        self.assertEqual(snapshot["app_version"], "0.8.0")
        self.assertEqual(snapshot["last_error_code"], "PLATFORM_CHANGED")
        self.assertEqual(len(snapshot["platform_health"]), 2)
        self.assertIn("os", snapshot)
        self.assertNotIn("token", str(snapshot).lower().replace("last_error_code", ""))


if __name__ == "__main__":
    unittest.main()
