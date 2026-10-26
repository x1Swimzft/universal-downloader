import os
import sys
import unittest
import unittest.mock

import httpx

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.main import app
from app.services import extractor as extractor_module
from app.services.extractor import _collect_entries, extract_info

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PL_TEST"
SINGLE_URL = "https://vimeo.com/12345"
BAD_URL = "https://example.com/bad"


def _yt_entry(video_id, title=None, duration=None, **extra):
    entry = {
        "ie_key": "Youtube",
        "url": video_id,
        "id": video_id,
        "title": title or f"Video {video_id}",
        "duration": duration,
    }
    entry.update(extra)
    return entry


def _patch_ytdlp(payload, captured=None):
    class FakeYDL:
        def __init__(self, opts):
            if captured is not None:
                captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, download=False):
            if isinstance(payload, Exception):
                raise payload
            if callable(payload):
                return payload(url)
            return payload

    return unittest.mock.patch.object(
        extractor_module.yt_dlp, "YoutubeDL", FakeYDL
    )


class TestCollectEntries(unittest.TestCase):
    def test_expands_playlist_and_rebuilds_youtube_urls(self):
        info = {
            "_type": "playlist",
            "extractor_key": "YoutubeTab",
            "entries": [
                _yt_entry("aaaaaaaaaaa", "First", 61),
                _yt_entry("bbbbbbbbbbb", "Second", 122),
                {
                    "webpage_url": "https://vimeo.com/999",
                    "title": "Vimeo clip",
                    "thumbnails": [
                        {"url": "https://img/small.jpg", "width": 10, "height": 10},
                        {"url": "https://img/large.jpg", "width": 800, "height": 450},
                    ],
                },
            ],
        }

        entries = _collect_entries(info)

        self.assertEqual(
            [entry["url"] for entry in entries],
            [
                "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                "https://www.youtube.com/watch?v=bbbbbbbbbbb",
                "https://vimeo.com/999",
            ],
        )
        self.assertEqual(entries[0]["title"], "First")
        self.assertEqual(entries[0]["duration"], 61)
        self.assertEqual(entries[0]["platform"], "youtube")
        self.assertEqual(entries[0]["media_type"], "video")
        self.assertEqual(entries[1]["platform"], "youtube")
        self.assertEqual(entries[2]["platform"], "vimeo")
        self.assertEqual(entries[2]["thumbnail"], "https://img/large.jpg")

    def test_uses_parent_extractor_key_for_youtube_ids(self):
        info = {
            "_type": "playlist",
            "extractor_key": "YoutubeTab",
            "entries": [{"url": "ccccccccccc", "title": "From parent"}],
        }

        entries = _collect_entries(info)

        self.assertEqual(
            entries[0]["url"], "https://www.youtube.com/watch?v=ccccccccccc"
        )

    def test_deduplicates_skips_invalid_and_preserves_order(self):
        info = {
            "entries": [
                _yt_entry("aaaaaaaaaaa", "First"),
                _yt_entry("aaaaaaaaaaa", "Duplicate"),
                {"webpage_url": "https://vimeo.com/1", "title": "Vimeo"},
                {"url": "not-a-url", "ie_key": "Vimeo", "title": "Bad"},
                {"url": "", "title": "Empty"},
                {"title": "No URL"},
                None,
                "not-a-dict",
                _yt_entry("bbbbbbbbbbb", "Second"),
            ]
        }

        entries = _collect_entries(info)

        self.assertEqual(
            [entry["url"] for entry in entries],
            [
                "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                "https://vimeo.com/1",
                "https://www.youtube.com/watch?v=bbbbbbbbbbb",
            ],
        )
        self.assertEqual(entries[0]["title"], "First")

    def test_caps_entries_at_limit(self):
        info = {
            "_type": "playlist",
            "entries": [
                _yt_entry(f"vid{index:08d}", f"Video {index}")
                for index in range(105)
            ],
        }

        self.assertEqual(len(_collect_entries(info)), 100)
        self.assertEqual(len(_collect_entries(info, limit=3)), 3)

    def test_non_playlist_info_without_entries_returns_empty(self):
        self.assertEqual(_collect_entries({"title": "Single video"}), [])


class TestPlaylistExtraction(unittest.IsolatedAsyncioTestCase):
    async def test_extract_info_returns_playlist_entries(self):
        payload = {
            "_type": "playlist",
            "title": "My Mix",
            "uploader": "Uploader",
            "extractor_key": "YoutubeTab",
            "entries": [
                _yt_entry("aaaaaaaaaaa", "First", 61),
                _yt_entry("bbbbbbbbbbb", "Second", 122),
            ],
        }
        captured = {}

        with unittest.mock.patch.object(
            extractor_module, "validate_url_not_private", return_value=True
        ), _patch_ytdlp(payload, captured):
            result = await extract_info(PLAYLIST_URL)

        self.assertEqual(result.media_type, "playlist")
        self.assertEqual(result.title, "My Mix")
        self.assertEqual(result.uploader, "Uploader")
        self.assertEqual(result.platform, "youtube")
        self.assertEqual(result.formats, [])
        self.assertEqual(result.images, [])
        self.assertEqual(len(result.entries), 2)
        self.assertEqual(result.entries[0].url, "https://www.youtube.com/watch?v=aaaaaaaaaaa")
        self.assertEqual(result.entries[1].title, "Second")
        self.assertEqual(captured["extract_flat"], "in_playlist")
        self.assertFalse(captured["noplaylist"])

    async def test_extract_info_keeps_single_video_behavior(self):
        payload = {
            "title": "Single clip",
            "duration": 30,
            "thumbnail": "https://img/thumb.jpg",
            "formats": [
                {
                    "format_id": "18",
                    "ext": "mp4",
                    "height": 360,
                    "vcodec": "avc1",
                    "acodec": "aac",
                }
            ],
        }
        captured = {}

        with unittest.mock.patch.object(
            extractor_module, "validate_url_not_private", return_value=True
        ), _patch_ytdlp(payload, captured):
            result = await extract_info(SINGLE_URL)

        self.assertEqual(result.media_type, "video")
        self.assertEqual(result.title, "Single clip")
        self.assertEqual(result.entries, [])
        self.assertEqual(len(result.formats), 1)
        self.assertEqual(result.formats[0].resolution, "360p")
        self.assertEqual(captured["extract_flat"], "in_playlist")


class TestPreviewApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_token = "playlist-session-token-12345"
        self.old_token = os.environ.get("APP_SESSION_TOKEN")
        os.environ["APP_SESSION_TOKEN"] = self.test_token
        self.headers = {"X-App-Token": self.test_token}

        def allow_public(url):
            return isinstance(url, str) and url.startswith("https://")

        self.url_patch = unittest.mock.patch(
            "app.api.routes.validate_url_not_private", side_effect=allow_public
        )
        self.extractor_url_patch = unittest.mock.patch.object(
            extractor_module, "validate_url_not_private", side_effect=allow_public
        )
        self.url_patch.start()
        self.extractor_url_patch.start()

    def tearDown(self):
        self.extractor_url_patch.stop()
        self.url_patch.stop()
        if self.old_token is not None:
            os.environ["APP_SESSION_TOKEN"] = self.old_token
        else:
            os.environ.pop("APP_SESSION_TOKEN", None)

    def _payload(self, url):
        if url == BAD_URL:
            raise RuntimeError("ERROR: Unsupported URL")
        if url == PLAYLIST_URL:
            return {
                "_type": "playlist",
                "title": "Preview playlist",
                "extractor_key": "YoutubeTab",
                "entries": [
                    _yt_entry("aaaaaaaaaaa", "First", 61),
                    _yt_entry("bbbbbbbbbbb", "Second", 122),
                ],
            }
        return {
            "title": "Single clip",
            "duration": 12,
            "thumbnail": "https://img/single.jpg",
            "webpage_url": url,
        }

    async def test_preview_returns_playlist_entries_and_skips_failed_url(self):
        transport = httpx.ASGITransport(app=app)
        with _patch_ytdlp(self._payload):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8000"
            ) as client:
                response = await client.post(
                    "/api/preview",
                    json={"urls": [PLAYLIST_URL, BAD_URL]},
                    headers=self.headers,
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(
            body["items"][0]["url"],
            "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        )
        self.assertEqual(body["items"][0]["platform"], "youtube")
        self.assertEqual(body["items"][1]["title"], "Second")
        self.assertEqual(body["failed"], [BAD_URL])

    async def test_preview_returns_single_entry_for_one_url(self):
        transport = httpx.ASGITransport(app=app)
        with _patch_ytdlp(self._payload):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8000"
            ) as client:
                response = await client.post(
                    "/api/preview",
                    json={"urls": [SINGLE_URL]},
                    headers=self.headers,
                )

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], SINGLE_URL)
        self.assertEqual(items[0]["title"], "Single clip")
        self.assertEqual(items[0]["duration"], 12)
        self.assertEqual(items[0]["thumbnail"], "https://img/single.jpg")
        self.assertEqual(items[0]["platform"], "vimeo")

    async def test_preview_returns_400_when_every_url_fails(self):
        transport = httpx.ASGITransport(app=app)
        with _patch_ytdlp(self._payload):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8000"
            ) as client:
                response = await client.post(
                    "/api/preview",
                    json={"urls": [BAD_URL]},
                    headers=self.headers,
                )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["detail"])

    async def test_preview_rejects_invalid_and_too_many_urls(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            invalid = await client.post(
                "/api/preview",
                json={"urls": ["ftp://example.com/file"]},
                headers=self.headers,
            )
            self.assertEqual(invalid.status_code, 400)

            too_many = await client.post(
                "/api/preview",
                json={"urls": [f"https://example.com/{index}" for index in range(11)]},
                headers=self.headers,
            )
            self.assertEqual(too_many.status_code, 400)

    async def test_preview_requires_session_token(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            response = await client.post(
                "/api/preview",
                json={"urls": [SINGLE_URL]},
            )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
