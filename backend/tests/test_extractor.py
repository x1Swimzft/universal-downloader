import os
import sys
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.models.schemas import MediaInfo
from app.services.extractor import _clean_url


class TestExtractor(unittest.TestCase):
    def test_mediainfo_fractional_duration(self):
        info_float = MediaInfo(title="Facebook Reel", duration=28.92)
        self.assertEqual(info_float.duration, 28.92)

        info_int = MediaInfo(title="Normal Video", duration=30)
        self.assertEqual(info_int.duration, 30)

        info_none = MediaInfo(title="No Duration", duration=None)
        self.assertIsNone(info_none.duration)

    def test_tiktok_photo_url_clean(self):
        photo_url = "https://www.tiktok.com/@untilliforgetyou/photo/7693279726596558100?is_from_webapp=1&sender_device=pc"
        cleaned = _clean_url(photo_url)
        self.assertEqual(
            cleaned,
            "https://www.tiktok.com/@untilliforgetyou/video/7693279726596558100?is_from_webapp=1&sender_device=pc",
        )

    def test_youtube_url_clean(self):
        yt_url = "https://youtu.be/dQw4w9WgXcQ?si=abc"
        cleaned = _clean_url(yt_url)
        self.assertEqual(cleaned, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")


if __name__ == "__main__":
    unittest.main()
