import os
import sys
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services import extractor


class _FakeYDL:
    """Returns one video format and one audio-only format, like YouTube."""

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        return {
            "title": "Clip",
            "duration": 10,
            "formats": [
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "height": 1080,
                    "vcodec": "avc1.640028",
                    "acodec": "none",
                },
                {
                    "format_id": "140",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "abr": 128,
                },
            ],
        }


class TestExtractInfoFormats(unittest.IsolatedAsyncioTestCase):
    async def test_audio_only_formats_are_listed(self):
        # Regression: _audio_format was missing from the facade after the move,
        # which broke every YouTube preview in the packaged 0.8.0 build.
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(extractor.yt_dlp, "YoutubeDL", _FakeYDL):
            info = await extractor.extract_info("https://www.youtube.com/watch?v=abc")

        self.assertEqual(info.media_type, "video")
        self.assertEqual(len(info.formats), 2)
        audio = [f for f in info.formats if f.ext in ("m4a", "mp3", "opus")]
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0].format_id, "140")


if __name__ == "__main__":
    unittest.main()
