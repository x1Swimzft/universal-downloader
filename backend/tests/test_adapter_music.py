import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services import extractor
from app.services.adapters import music

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TRACK_URL = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"


def _fixture(*parts):
    with open(os.path.join(FIXTURES, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestSpotifyCoverSelection(unittest.TestCase):
    def test_visual_identity_is_used_when_cover_art_is_absent(self):
        # Regression: live embed entities carry no coverArt, only visualIdentity.
        entity = {
            "visualIdentity": {
                "image": [
                    {"url": "https://image-cdn-ak.spotifycdn.com/image/small", "maxWidth": 64, "maxHeight": 64},
                    {"url": "https://image-cdn-ak.spotifycdn.com/image/big", "maxWidth": 640, "maxHeight": 640},
                ]
            }
        }

        self.assertEqual(
            music._spotify_cover(entity),
            "https://image-cdn-ak.spotifycdn.com/image/big",
        )

    def test_cover_art_still_wins_when_present(self):
        entity = {
            "coverArt": {
                "sources": [
                    {"url": "https://i.scdn.co/image/legacy", "width": 300, "height": 300}
                ]
            },
            "visualIdentity": {
                "image": [
                    {"url": "https://image-cdn-ak.spotifycdn.com/image/other", "maxWidth": 640, "maxHeight": 640}
                ]
            },
        }

        self.assertEqual(music._spotify_cover(entity), "https://i.scdn.co/image/legacy")

    def test_no_cover_at_all_returns_none(self):
        self.assertIsNone(music._spotify_cover({"visualIdentity": {}}))
        self.assertIsNone(music._spotify_cover({}))


class TestCapturedSpotifyCover(unittest.IsolatedAsyncioTestCase):
    async def test_captured_track_resolves_a_cover(self):
        html = _fixture("spotify", "track_embed.html")
        with patch.object(extractor, "_get_text", AsyncMock(return_value=html)):
            data = await extractor._resolve_spotify(TRACK_URL)

        self.assertEqual(data["title"], "Never Gonna Give You Up")
        self.assertTrue(
            (data["thumbnail"] or "").startswith("https://image-cdn-ak.spotifycdn.com/"),
            f"expected a cover URL, got {data['thumbnail']!r}",
        )
        self.assertEqual(data["entries"][0]["thumbnail"], data["thumbnail"])


if __name__ == "__main__":
    unittest.main()
