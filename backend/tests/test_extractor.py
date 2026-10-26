import os
import sys
import tempfile
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.models.schemas import MediaInfo
from app.services.extractor import (
    _build_ydl_opts,
    _clean_url,
    _collect_images,
    _friendly_error,
    _get_base_opts,
    _parse_tiktok_photo_html,
    _preset_ffmpeg_args,
    parse_timestamp,
    set_cookie_preferences,
    validate_clip_range,
)
from app.services.extractor_update import _version_key


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

    def test_instagram_url_clean(self):
        cleaned = _clean_url("https://www.instagram.com/p/ABC123/?img_index=1&igsh=xyz")
        self.assertEqual(cleaned, "https://www.instagram.com/p/ABC123/")

    def test_friendly_error(self):
        ig = "https://www.instagram.com/p/ABC123/"
        self.assertIn("only contains photos", _friendly_error("ERROR: No video formats found!", ig))
        tt = "https://www.tiktok.com/@a/video/1"
        self.assertIn("HTTP 403", _friendly_error("Unable to download webpage: HTTP Error 403: Forbidden", tt))
        self.assertIsNone(_friendly_error("some other error", tt))


class TestClipAndPresets(unittest.TestCase):
    def tearDown(self):
        set_cookie_preferences(cookies_from_browser="none", cookies_file="")

    def test_timestamp_parsing(self):
        self.assertEqual(parse_timestamp("1:02"), 62)
        self.assertEqual(parse_timestamp("01:02:03.5"), 3723.5)
        self.assertEqual(parse_timestamp(12.25), 12.25)
        self.assertIsNone(parse_timestamp(""))
        for bad in ("1:99", "abc", "-1:00", "25:00:00"):
            with self.assertRaises(ValueError):
                parse_timestamp(bad)

    def test_clip_range_validation(self):
        self.assertEqual(validate_clip_range(None, None), (None, None))
        self.assertEqual(validate_clip_range("0:10", None), (10, None))
        self.assertEqual(validate_clip_range(None, "0:10"), (None, 10))
        with self.assertRaises(ValueError):
            validate_clip_range("0:10", "0:10")
        with self.assertRaises(ValueError):
            validate_clip_range("0:20", "0:10")

    def test_download_range_options(self):
        opts = _build_ydl_opts(
            "mp4", "1080", "%(id)s.%(ext)s", lambda _d: None,
            "https://example.com/v", 5, 12,
        )
        self.assertIn("download_ranges", opts)
        self.assertTrue(opts["force_keyframes_at_cuts"])
        ranges = list(opts["download_ranges"]({"duration": 60}, None))
        self.assertEqual(ranges[0]["start_time"], 5)
        self.assertEqual(ranges[0]["end_time"], 12)

    def test_preset_arguments(self):
        edit = _preset_ffmpeg_args("edit_ready", "in.webm", "out.mp4")
        self.assertIn("libx264", edit)
        self.assertIn("aac", edit)
        norm = _preset_ffmpeg_args("audio_norm", "in.mp4", "out.m4a")
        self.assertIn("loudnorm=I=-14:TP=-1.5:LRA=11", norm)
        lossless = _preset_ffmpeg_args("audio_lossless", "in.mp4", "out.flac")
        self.assertEqual(lossless[-3:], ["-c:a", "flac", "out.flac"])
        social = _preset_ffmpeg_args("social_bypass", "in.mp4", "out.mp4")
        self.assertIn("fps=30", social)
        self.assertIn("-map_metadata", social)
        with self.assertRaises(ValueError):
            _preset_ffmpeg_args("unknown", "in", "out")

    def test_cookie_options(self):
        set_cookie_preferences(cookies_from_browser="chrome")
        opts = _get_base_opts()
        self.assertEqual(opts["cookiesfrombrowser"], ("chrome",))
        self.assertNotIn("cookiefile", opts)

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
            set_cookie_preferences(cookies_from_browser="none", cookies_file=path)
            opts = _get_base_opts()
            self.assertEqual(opts["cookiefile"], os.path.realpath(path))
            self.assertNotIn("cookiesfrombrowser", opts)
        finally:
            os.remove(path)

        with self.assertRaises(ValueError):
            set_cookie_preferences(cookies_from_browser="opera")
        with self.assertRaises(ValueError):
            set_cookie_preferences(cookies_file="relative/cookies.txt")

    def test_image_collection(self):
        single = {
            "formats": [],
            "thumbnails": [
                {"url": "https://img/small.jpg", "width": 100, "height": 100},
                {"url": "https://img/large.jpg", "width": 1080, "height": 1080},
            ],
        }
        self.assertEqual(_collect_images(single), ["https://img/large.jpg"])

        carousel = {
            "_type": "playlist",
            "entries": [
                {"formats": [], "thumbnail": "https://img/1.jpg"},
                {"formats": [], "thumbnails": [{"url": "https://img/2.jpg", "width": 800}]},
            ],
        }
        self.assertEqual(_collect_images(carousel), ["https://img/1.jpg", "https://img/2.jpg"])

        mixed = {
            "_type": "playlist",
            "entries": [
                {"formats": [{"url": "https://video"}], "thumbnail": "https://img/1.jpg"},
                {"formats": [], "thumbnail": "https://img/2.jpg"},
            ],
        }
        self.assertEqual(_collect_images(mixed), [])

    def test_tiktok_photo_parser(self):
        payload = {
            "webapp.video-detail": {
                "itemInfo": {
                    "itemStruct": {
                        "desc": "photo post",
                        "imagePost": {
                            "images": [
                                {"imageURL": {"urlList": ["https://cdn/1.jpg"]}},
                                {"displayImage": {"urlList": ["https://cdn/2.jpg"]}},
                            ]
                        },
                    }
                }
            }
        }
        import json as _json

        html = (
            '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" '
            f'type="application/json">{_json.dumps(payload)}</script>'
        )
        images, title = _parse_tiktok_photo_html(html)
        self.assertEqual(images, ["https://cdn/1.jpg", "https://cdn/2.jpg"])
        self.assertEqual(title, "photo post")
        self.assertEqual(_parse_tiktok_photo_html("<html></html>"), ([], None))

    def test_version_key_orders_releases(self):
        self.assertGreater(_version_key("2026.10.26"), _version_key("2026.8.19"))
        self.assertEqual(_version_key("2026.08.19"), (2026, 8, 19))


if __name__ == "__main__":
    unittest.main()
