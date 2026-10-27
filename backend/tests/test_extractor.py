import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.models.schemas import MediaInfo
from app.services import extractor
from app.services.extractor import (
    AUDIO_FILENAME_TEMPLATES,
    _build_ydl_opts,
    _clean_url,
    _collect_images,
    _extract_platform,
    _find_output_file,
    _flat_info,
    _friendly_error,
    _get_base_opts,
    _IG_EMBED_UA,
    _instagram_embed_info,
    _instagram_shortcode,
    _music_ffmpeg_args,
    _normalize_preset,
    _parse_tiktok_photo_html,
    _photo_referer,
    _preset_ffmpeg_args,
    _upgrade_pinterest_image,
    _download_music_cover,
    classify_error,
    diagnostic_message,
    download_media,
    error_action,
    extract_info,
    format_audio_filename,
    inspect_entries,
    is_music_url,
    parse_timestamp,
    resolve_music,
    sanitize_name,
    set_cookie_preferences,
    validate_clip_range,
)
from app.services.extractor_update import _version_key


def _script_html(script_id, payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return (
        '<html><head></head><body>'
        f'<script id="{script_id}" type="application/json">{body}</script>'
        '</body></html>'
    )


class _FakeResponse:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code
        self.headers = {}
        self.is_redirect = False


class _FakeAsyncClient:
    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        self.requested.append(url)
        for marker, response in self.routes.items():
            if marker in url:
                return response
        raise AssertionError(f"Unexpected HTTP request: {url}")


def _fake_http(routes):
    return patch.object(
        extractor.httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(routes)
    )


SPOTIFY_PLAYLIST_PAYLOAD = {
    "props": {
        "pageProps": {
            "data": {
                "entity": {
                    "type": "playlist",
                    "name": "Road Trip",
                    "subtitle": "DJ Mix",
                    "coverArt": {
                        "sources": [
                            {"url": "https://i.scdn.co/image/small", "width": 64, "height": 64},
                            {"url": "https://i.scdn.co/image/big", "width": 640, "height": 640},
                        ]
                    },
                    "trackList": [
                        {
                            "uri": "spotify:track:trackone",
                            "title": "One",
                            "subtitle": "Artist A",
                            "duration": 185000,
                        },
                        {
                            "uri": "spotify:track:tracktwo",
                            "title": "Two",
                            "subtitle": "Artist B",
                            "duration": 210600,
                        },
                    ],
                }
            }
        }
    }
}

SPOTIFY_TRACK_PAYLOAD = {
    "props": {
        "pageProps": {
            "data": {
                "entity": {
                    "type": "track",
                    "name": "Single",
                    "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
                    "duration": 201000,
                    "coverArt": {
                        "sources": [{"url": "https://i.scdn.co/image/track", "width": 640, "height": 640}]
                    },
                }
            }
        }
    }
}


class TestMusicResolver(unittest.IsolatedAsyncioTestCase):
    async def test_spotify_playlist_embed_parsing(self):
        html = _script_html("__NEXT_DATA__", SPOTIFY_PLAYLIST_PAYLOAD)
        with _fake_http({"open.spotify.com/embed/playlist/pl1": _FakeResponse(html)}):
            data = await resolve_music("https://open.spotify.com/playlist/pl1?si=test")

        self.assertEqual(data["platform"], "spotify")
        self.assertEqual(data["title"], "Road Trip")
        self.assertEqual(data["media_type"], "playlist")
        self.assertEqual(data["thumbnail"], "https://i.scdn.co/image/big")
        self.assertEqual(len(data["entries"]), 2)
        first = data["entries"][0]
        self.assertEqual(first["url"], "https://open.spotify.com/track/trackone")
        self.assertEqual(first["title"], "One")
        self.assertEqual(first["artist"], "Artist A")
        self.assertEqual(first["duration"], 185)
        self.assertEqual(first["track_number"], 1)
        self.assertEqual(first["platform"], "spotify")
        self.assertEqual(first["media_type"], "audio")
        self.assertEqual(first["search_query"], "Artist A - One official audio")
        self.assertEqual(data["entries"][1]["duration"], 211)

    async def test_spotify_track_embed_parsing(self):
        html = _script_html("__NEXT_DATA__", SPOTIFY_TRACK_PAYLOAD)
        with _fake_http({"open.spotify.com/embed/track/track1": _FakeResponse(html)}):
            data = await resolve_music("https://open.spotify.com/track/track1")

        self.assertEqual(data["media_type"], "track")
        self.assertEqual(data["artist"], "Artist A, Artist B")
        self.assertEqual(data["thumbnail"], "https://i.scdn.co/image/track")
        entry = data["entries"][0]
        self.assertEqual(entry["url"], "https://open.spotify.com/track/track1")
        self.assertEqual(entry["artist"], "Artist A, Artist B")
        self.assertEqual(entry["duration"], 201)
        self.assertEqual(entry["search_query"], "Artist A, Artist B - Single official audio")

    async def test_spotify_oembed_fallback_for_track(self):
        oembed = json.dumps(
            {
                "title": "Fallback Song",
                "author_name": "Fallback Artist",
                "thumbnail_url": "https://i.scdn.co/image/fallback",
            }
        )
        routes = {
            "open.spotify.com/embed/track/track2": _FakeResponse("<html></html>"),
            "open.spotify.com/oembed": _FakeResponse(oembed),
        }
        with _fake_http(routes):
            data = await resolve_music("https://open.spotify.com/track/track2")

        self.assertEqual(data["media_type"], "track")
        self.assertEqual(data["title"], "Fallback Song")
        self.assertEqual(data["artist"], "Fallback Artist")
        self.assertEqual(data["entries"][0]["search_query"], "Fallback Artist - Fallback Song official audio")

    async def test_spotify_album_without_tracklist_fails_cleanly(self):
        payload = {"props": {"pageProps": {"data": {"entity": {"type": "album", "name": "Empty"}}}}}
        html = _script_html("__NEXT_DATA__", payload)
        with _fake_http({"open.spotify.com/embed/album/empty": _FakeResponse(html)}):
            with self.assertRaises(ValueError) as raised:
                await resolve_music("https://open.spotify.com/album/empty")
        self.assertIn("track list", str(raised.exception).lower())

    async def test_apple_playlist_unique_urls_and_queries(self):
        payload = {
            "data": [
                {
                    "sections": [
                        {
                            "items": [
                                {
                                    "title": "First",
                                    "artistName": "Artist A",
                                    "durationInMillis": 181000,
                                    "url": "https://music.apple.com/us/album/first/100?i=1",
                                    "artwork": {
                                        "url": "https://is1.mzstatic.com/image/thumb/x/{w}x{h}bb.jpg"
                                    },
                                },
                                {
                                    "title": "Second",
                                    "artistName": "Artist B",
                                    "duration": 182000,
                                    "url": "",
                                },
                            ]
                        }
                    ]
                }
            ]
        }
        html = (
            '<html><head>'
            '<meta property="og:title" content="Road Apple">'
            '<meta property="og:image" content="https://is1.mzstatic.com/og.jpg">'
            '</head><body>'
            + _script_html("serialized-server-data", payload)
            + "</body></html>"
        )
        with _fake_http({"embed.music.apple.com": _FakeResponse(html)}):
            data = await resolve_music("https://music.apple.com/us/playlist/road/pl.123")

        self.assertEqual(data["platform"], "apple")
        self.assertEqual(data["title"], "Road Apple")
        self.assertEqual(data["media_type"], "playlist")
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(data["entries"][0]["url"], "https://music.apple.com/us/album/first/100?i=1")
        self.assertEqual(
            data["entries"][1]["url"],
            "https://music.apple.com/us/playlist/road/pl.123#track-2",
        )
        self.assertNotIn("{w}", data["entries"][0]["thumbnail"])
        self.assertEqual(data["entries"][0]["search_query"], "Artist A - First official audio")
        self.assertEqual(data["entries"][1]["duration"], 182)
        self.assertEqual(data["entries"][1]["track_number"], 2)

    async def test_apple_duplicate_urls_become_unique_anchors(self):
        payload = {
            "items": [
                {"title": "Same", "artistName": "Artist", "durationInMillis": 100000, "url": ""},
                {"title": "Same 2", "artistName": "Artist", "durationInMillis": 100000, "url": ""},
            ]
        }
        html = _script_html("serialized-server-data", payload)
        with _fake_http({"embed.music.apple.com": _FakeResponse(html)}):
            data = await resolve_music("https://music.apple.com/us/playlist/x/pl.9")
        urls = [entry["url"] for entry in data["entries"]]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(urls[0], "https://music.apple.com/us/playlist/x/pl.9#track-1")
        self.assertEqual(urls[1], "https://music.apple.com/us/playlist/x/pl.9#track-2")

    async def test_apple_single_song_open_graph_fallback(self):
        html = (
            '<html><head>'
            '<meta property="og:title" content="Lonely Song">'
            '<meta property="og:image" content="https://is1.mzstatic.com/cover.jpg">'
            '</head></html>'
        )
        with _fake_http({"embed.music.apple.com": _FakeResponse(html)}):
            data = await resolve_music("https://music.apple.com/us/album/lonely/1?i=42")
        self.assertEqual(data["media_type"], "track")
        self.assertEqual(data["title"], "Lonely Song")
        self.assertEqual(data["thumbnail"], "https://is1.mzstatic.com/cover.jpg")
        self.assertEqual(data["entries"][0]["url"], "https://music.apple.com/us/album/lonely/1?i=42")
        self.assertEqual(data["entries"][0]["search_query"], "Lonely Song official audio")

    async def test_music_url_detection(self):
        self.assertTrue(is_music_url("https://open.spotify.com/track/abc"))
        self.assertTrue(is_music_url("https://open.spotify.com/album/abc?si=x"))
        self.assertTrue(is_music_url("https://music.apple.com/us/playlist/x/pl.1"))
        self.assertFalse(is_music_url("https://example.com/track/abc"))
        self.assertFalse(is_music_url("https://open.spotify.com/user/abc"))


class TestMusicInfo(unittest.IsolatedAsyncioTestCase):
    async def test_extract_info_for_music_playlist(self):
        resolved = {
            "platform": "spotify",
            "title": "Road Trip",
            "artist": "DJ Mix",
            "album": None,
            "thumbnail": "https://i.scdn.co/image/big",
            "media_type": "playlist",
            "entries": [
                {
                    "url": "https://open.spotify.com/track/trackone",
                    "title": "One",
                    "artist": "Artist A",
                    "album": None,
                    "track_number": 1,
                    "duration": 185,
                    "thumbnail": "https://i.scdn.co/image/big",
                    "platform": "spotify",
                    "media_type": "audio",
                    "search_query": "Artist A - One official audio",
                }
            ],
        }
        with patch.object(extractor, "validate_url_not_private", return_value=True), patch.object(
            extractor, "resolve_music", AsyncMock(return_value=resolved)
        ):
            info = await extract_info("https://open.spotify.com/playlist/pl1")

        self.assertEqual(info.media_type, "playlist")
        self.assertEqual(info.title, "Road Trip")
        self.assertEqual(info.entries[0].search_query, "Artist A - One official audio")
        self.assertEqual(info.entries[0].media_type, "audio")

    async def test_extract_info_for_single_music_track(self):
        resolved = {
            "platform": "apple",
            "title": "Single",
            "artist": "Artist A",
            "album": "Album",
            "thumbnail": "https://is1.mzstatic.com/cover.jpg",
            "media_type": "track",
            "entries": [
                {
                    "url": "https://music.apple.com/us/album/x/1?i=2",
                    "title": "Single",
                    "artist": "Artist A",
                    "album": "Album",
                    "track_number": 4,
                    "duration": 200,
                    "thumbnail": "https://is1.mzstatic.com/cover.jpg",
                    "platform": "apple",
                    "media_type": "audio",
                    "search_query": "Artist A - Single official audio",
                }
            ],
        }
        with patch.object(extractor, "validate_url_not_private", return_value=True), patch.object(
            extractor, "resolve_music", AsyncMock(return_value=resolved)
        ):
            info = await extract_info("https://music.apple.com/us/album/x/1?i=2")

        self.assertEqual(info.media_type, "video")
        self.assertEqual(info.platform, "apple")
        self.assertEqual(info.uploader, "Artist A")
        self.assertEqual(info.artist, "Artist A")
        self.assertEqual(info.album, "Album")
        self.assertEqual(info.track_number, 4)
        self.assertEqual(info.search_query, "Artist A - Single official audio")
        self.assertEqual(info.formats, [])

    async def test_inspect_entries_returns_music_entries(self):
        resolved = {
            "platform": "spotify",
            "title": "Track",
            "artist": "Artist",
            "album": None,
            "thumbnail": None,
            "media_type": "track",
            "entries": [
                {
                    "url": "https://open.spotify.com/track/t1",
                    "title": "Track",
                    "artist": "Artist",
                    "album": None,
                    "track_number": 1,
                    "duration": 100,
                    "thumbnail": None,
                    "platform": "spotify",
                    "media_type": "audio",
                    "search_query": "Artist - Track official audio",
                }
            ],
        }
        with patch.object(extractor, "validate_url_not_private", return_value=True), patch.object(
            extractor, "resolve_music", AsyncMock(return_value=resolved)
        ):
            entries = await inspect_entries("https://open.spotify.com/track/t1")
        self.assertEqual(entries[0]["media_type"], "audio")
        self.assertEqual(entries[0]["search_query"], "Artist - Track official audio")


class _FakeYoutubeDL:
    last_opts = None
    last_url = None

    def __init__(self, opts):
        _FakeYoutubeDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=True):
        _FakeYoutubeDL.last_url = url
        return {"title": "Resolved Video"}


class TestMusicDownload(unittest.IsolatedAsyncioTestCase):
    async def test_search_query_downloads_bestaudio_and_forces_mp3(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_id = "abc123"
            audio_path = os.path.join(tmp, f"{job_id}.mp3")
            with open(audio_path, "wb") as handle:
                handle.write(b"x")

            with patch.object(
                extractor.yt_dlp, "YoutubeDL", _FakeYoutubeDL
            ), patch.object(
                extractor, "_download_music_cover", AsyncMock(return_value=None)
            ), patch.object(
                extractor, "_embed_music_metadata", side_effect=lambda path, meta, cover: path
            ):
                filepath, title = await download_media(
                    "https://www.youtube.com/watch?v=abc",
                    "mp4",
                    "320",
                    tmp,
                    {},
                    job_id,
                    search_query="Artist - Song official audio",
                    music_metadata={"title": "Song", "artist": "Artist"},
                )

        self.assertEqual(filepath, audio_path)
        self.assertEqual(title, "Resolved Video")
        self.assertEqual(_FakeYoutubeDL.last_url, "ytsearch1:Artist - Song official audio")
        self.assertIn("bestaudio", _FakeYoutubeDL.last_opts["format"])
        postprocessor = _FakeYoutubeDL.last_opts["postprocessors"][0]
        self.assertEqual(postprocessor["key"], "FFmpegExtractAudio")
        self.assertEqual(postprocessor["preferredcodec"], "mp3")

    async def test_social_bypass_does_not_convert_audio_to_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_id = "spotify-social"
            audio_path = os.path.join(tmp, f"{job_id}.mp3")
            with open(audio_path, "wb") as handle:
                handle.write(b"x")

            postprocess = MagicMock()
            with patch.object(
                extractor.yt_dlp, "YoutubeDL", _FakeYoutubeDL
            ), patch.object(
                extractor, "_postprocess_file", postprocess
            ), patch.object(
                extractor, "_download_music_cover", AsyncMock(return_value=None)
            ), patch.object(
                extractor, "_embed_music_metadata", side_effect=lambda path, meta, cover: path
            ):
                filepath, _ = await download_media(
                    "https://open.spotify.com/track/abc",
                    "mp3",
                    "320",
                    tmp,
                    {},
                    job_id,
                    search_query="Artist - Song official audio",
                    social_bypass=True,
                )

        self.assertEqual(filepath, audio_path)
        self.assertTrue(filepath.endswith(".mp3"))
        postprocess.assert_not_called()

    def test_audio_preset_normalization_ignores_social_bypass(self):
        self.assertIsNone(_normalize_preset(None, True, audio=True))
        self.assertEqual(
            _normalize_preset("audio_lossless", True, audio=True),
            "audio_lossless",
        )
        self.assertEqual(_normalize_preset(None, True, audio=False), "social_bypass")
        self.assertEqual(
            _normalize_preset("edit_ready", True, audio=False), "social_bypass"
        )

    async def test_music_track_url_resolves_to_search_not_raw_url(self):
        resolved = {
            "platform": "spotify",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "thumbnail": "https://i.scdn.co/image/cover",
            "media_type": "track",
            "entries": [
                {
                    "url": "https://open.spotify.com/track/t1",
                    "title": "Song",
                    "artist": "Artist",
                    "album": "Album",
                    "track_number": 2,
                    "duration": 180,
                    "thumbnail": "https://i.scdn.co/image/cover",
                    "platform": "spotify",
                    "media_type": "audio",
                    "search_query": "Artist - Song official audio",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            job_id = "trackjob"
            with open(os.path.join(tmp, f"{job_id}.mp3"), "wb") as handle:
                handle.write(b"x")
            with patch.object(
                extractor, "validate_url_not_private", return_value=True
            ), patch.object(
                extractor, "resolve_music", AsyncMock(return_value=resolved)
            ), patch.object(
                extractor.yt_dlp, "YoutubeDL", _FakeYoutubeDL
            ), patch.object(
                extractor, "_download_music_cover", AsyncMock(return_value=None)
            ), patch.object(
                extractor, "_embed_music_metadata", side_effect=lambda path, meta, cover: path
            ):
                await download_media(
                    "https://open.spotify.com/track/t1", "mp3", "320", tmp, {}, job_id
                )

        self.assertTrue(_FakeYoutubeDL.last_url.startswith("ytsearch1:"))
        self.assertNotIn("open.spotify.com", _FakeYoutubeDL.last_url)

    async def test_music_album_download_requires_track_selection(self):
        resolved = {
            "platform": "spotify",
            "title": "Album",
            "artist": "Artist",
            "album": "Album",
            "thumbnail": None,
            "media_type": "album",
            "entries": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                extractor, "validate_url_not_private", return_value=True
            ), patch.object(
                extractor, "resolve_music", AsyncMock(return_value=resolved)
            ), patch.object(
                extractor.yt_dlp, "YoutubeDL", MagicMock(side_effect=_FakeYoutubeDL)
            ) as ydl:
                with self.assertRaises(ValueError) as raised:
                    await download_media(
                        "https://open.spotify.com/album/a1", "mp3", "320", tmp, {}, "j1"
                    )
        self.assertIn("select individual tracks", str(raised.exception).lower())
        self.assertFalse(ydl.called)


class TestAudioFilenames(unittest.TestCase):
    def test_supported_templates_and_order(self):
        self.assertEqual(
            AUDIO_FILENAME_TEMPLATES,
            (
                "{track} - {artist} - {title}",
                "{artist} - {title}",
                "{title} ({artist})",
                "{title}",
            ),
        )

    def test_four_presets_render(self):
        metadata = {"title": "Song", "artist": "Artist", "track_number": 3}
        self.assertEqual(
            format_audio_filename(AUDIO_FILENAME_TEMPLATES[0], metadata, "mp3"),
            "03 - Artist - Song.mp3",
        )
        self.assertEqual(
            format_audio_filename(AUDIO_FILENAME_TEMPLATES[1], metadata, "mp3"),
            "Artist - Song.mp3",
        )
        self.assertEqual(
            format_audio_filename(AUDIO_FILENAME_TEMPLATES[2], metadata, "mp3"),
            "Song (Artist).mp3",
        )
        self.assertEqual(
            format_audio_filename(AUDIO_FILENAME_TEMPLATES[3], metadata, ".mp3"),
            "Song.mp3",
        )

    def test_missing_tokens_collapse_separators_and_brackets(self):
        metadata = {"title": "Song", "track_number": 3}
        self.assertEqual(
            format_audio_filename(AUDIO_FILENAME_TEMPLATES[0], metadata, "mp3"),
            "03 - Song.mp3",
        )
        self.assertEqual(
            format_audio_filename(AUDIO_FILENAME_TEMPLATES[1], metadata, "mp3"),
            "Song.mp3",
        )
        self.assertEqual(
            format_audio_filename(AUDIO_FILENAME_TEMPLATES[2], metadata, "mp3"),
            "Song.mp3",
        )
        self.assertEqual(
            format_audio_filename(
                AUDIO_FILENAME_TEMPLATES[0],
                {"title": "Song", "artist": "Artist"},
                "mp3",
            ),
            "Artist - Song.mp3",
        )

    def test_illegal_characters_are_stripped(self):
        self.assertEqual(
            format_audio_filename(
                AUDIO_FILENAME_TEMPLATES[1],
                {"title": "Back: In Black?", "artist": "AC/DC"},
                "mp3",
            ),
            "ACDC - Back In Black.mp3",
        )
        self.assertEqual(sanitize_name("  Bad<Name>.  "), "BadName")

    def test_playlist_track_prefix(self):
        self.assertEqual(
            format_audio_filename(
                AUDIO_FILENAME_TEMPLATES[3],
                {"title": "Song", "track_number": 2},
                "mp3",
                playlist=True,
            ),
            "02 - Song.mp3",
        )
        self.assertEqual(
            format_audio_filename(
                AUDIO_FILENAME_TEMPLATES[0],
                {"title": "Song", "artist": "Artist", "track_number": 2},
                "mp3",
                playlist=True,
            ),
            "02 - Artist - Song.mp3",
        )
        self.assertEqual(
            format_audio_filename(
                AUDIO_FILENAME_TEMPLATES[3], {"title": "Song"}, "mp3", playlist=True
            ),
            "Song.mp3",
        )

    def test_album_token_renders(self):
        self.assertEqual(
            format_audio_filename(
                "{album} - {track} - {title}",
                {"title": "Song", "album": "Album", "track_number": 2},
                "flac",
            ),
            "Album - 02 - Song.flac",
        )

    def test_unknown_tokens_removed_and_unknown_template_falls_back(self):
        self.assertEqual(
            format_audio_filename(
                "{album} - {title}", {"title": "Song", "album": "Album"}, "mp3"
            ),
            "Album - Song.mp3",
        )
        self.assertEqual(
            format_audio_filename("{nope}", {"title": "Song"}, "mp3"),
            "Song.mp3",
        )


class TestPlatformDetection(unittest.TestCase):
    def test_all_supported_platforms(self):
        cases = {
            "https://www.youtube.com/watch?v=1": "youtube",
            "https://youtu.be/1": "youtube",
            "https://www.tiktok.com/@a/video/1": "tiktok",
            "https://www.instagram.com/p/abc/": "instagram",
            "https://twitter.com/a/status/1": "twitter",
            "https://x.com/a/status/1": "twitter",
            "https://www.facebook.com/watch/1": "facebook",
            "https://fb.watch/abc/": "facebook",
            "https://open.spotify.com/track/abc": "spotify",
            "https://music.apple.com/us/album/a/1": "apple",
            "https://www.twitch.tv/videos/1": "twitch",
            "https://clips.twitch.tv/abc": "twitch",
            "https://kick.com/someone": "kick",
            "https://www.bilibili.com/video/BV1": "bilibili",
            "https://www.reddit.com/r/a/comments/b/": "reddit",
            "https://www.pinterest.com/pin/1/": "pinterest",
            "https://pin.it/abc": "pinterest",
            "https://vimeo.com/1": "vimeo",
            "https://soundcloud.com/a/b": "soundcloud",
            "https://artist.bandcamp.com/track/song": "bandcamp",
        }
        for url, platform in cases.items():
            with self.subTest(url=url):
                self.assertEqual(_extract_platform(url), platform)


class TestPinterestFallback(unittest.IsolatedAsyncioTestCase):
    def test_original_image_upgrade(self):
        self.assertEqual(
            _upgrade_pinterest_image("https://i.pinimg.com/236x/ab/cd/image.jpg"),
            "https://i.pinimg.com/originals/ab/cd/image.jpg",
        )
        self.assertEqual(
            _upgrade_pinterest_image("https://i.pinimg.com/originals/ab/cd/image.jpg"),
            "https://i.pinimg.com/originals/ab/cd/image.jpg",
        )
        self.assertIsNone(_upgrade_pinterest_image(None))

    async def test_image_fallback_when_ytdlp_fails(self):
        pin = "https://www.pinterest.com/pin/123/"
        image = "https://i.pinimg.com/originals/ab/cd/image.jpg"
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor.yt_dlp, "YoutubeDL", side_effect=RuntimeError("no video")
        ), patch.object(
            extractor,
            "_fetch_pinterest_image",
            AsyncMock(return_value=(image, "Pin title", False)),
        ):
            info = await extract_info(pin)
        self.assertEqual(info.media_type, "image")
        self.assertEqual(info.images, [image])
        self.assertEqual(info.thumbnail, image)
        self.assertEqual(info.title, "Pin title")

    async def test_video_pin_reraises_ytdlp_error(self):
        pin = "https://www.pinterest.com/pin/123/"
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor.yt_dlp, "YoutubeDL", side_effect=RuntimeError("no video")
        ), patch.object(
            extractor,
            "_fetch_pinterest_image",
            AsyncMock(return_value=(None, "Pin title", True)),
        ):
            with self.assertRaises(RuntimeError):
                await extract_info(pin)

    async def test_image_fallback_when_no_video_formats(self):
        pin = "https://www.pinterest.com/pin/123/"
        image = "https://i.pinimg.com/originals/ab/cd/image.jpg"

        class _NoFormatYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {"formats": [], "title": "Pin", "thumbnails": []}

        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor.yt_dlp, "YoutubeDL", _NoFormatYDL
        ), patch.object(
            extractor,
            "_fetch_pinterest_image",
            AsyncMock(return_value=(image, "Pin title", False)),
        ):
            info = await extract_info(pin)
        self.assertEqual(info.media_type, "image")
        self.assertEqual(info.images, [image])

    async def test_image_fallback_when_formats_are_not_playable(self):
        pin = "https://www.pinterest.com/pin/123/"
        image = "https://i.pinimg.com/originals/ab/cd/image.jpg"

        class _ImageFormatYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                return {
                    "formats": [{"ext": "jpg", "vcodec": "none", "acodec": "none"}],
                    "title": "Pin",
                    "thumbnails": [],
                }

        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor.yt_dlp, "YoutubeDL", _ImageFormatYDL
        ), patch.object(
            extractor,
            "_fetch_pinterest_image",
            AsyncMock(return_value=(image, "Pin title", False)),
        ):
            info = await extract_info(pin)
        self.assertEqual(info.media_type, "image")
        self.assertEqual(info.images, [image])

    def test_pinterest_photo_referer(self):
        self.assertEqual(
            _photo_referer("https://www.pinterest.com/pin/1/"),
            "https://www.pinterest.com/",
        )
        self.assertEqual(
            _photo_referer("https://www.tiktok.com/@a/photo/1"),
            "https://www.tiktok.com/",
        )


class TestMusicTagging(unittest.TestCase):
    def test_ffmpeg_args_include_tags_and_cover(self):
        args = _music_ffmpeg_args(
            "in.mp3",
            "out.mp3",
            {
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
                "track_number": 3,
            },
            "cover.jpg",
        )
        self.assertIn("cover.jpg", args)
        self.assertIn("1:v", args)
        self.assertIn("title=Song", args)
        self.assertIn("artist=Artist", args)
        self.assertIn("album=Album", args)
        self.assertIn("track=3", args)
        self.assertIn("attached_pic", args)

    def test_ffmpeg_args_without_cover(self):
        args = _music_ffmpeg_args(
            "in.flac",
            "out.flac",
            {"title": "Song", "artist": "Artist"},
            None,
        )
        self.assertIn("-map_metadata", args)
        self.assertNotIn("attached_pic", args)

    def test_find_output_file_skips_cover_art(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "job1.cover.jpg"), "wb") as handle:
                handle.write(b"image")
            with open(os.path.join(tmp, "job1.part"), "wb") as handle:
                handle.write(b"part")
            audio = os.path.join(tmp, "job1.mp3")
            with open(audio, "wb") as handle:
                handle.write(b"audio")
            self.assertEqual(_find_output_file(tmp, "job1"), audio)

    def test_cover_rejects_private_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(extractor, "validate_url_not_private", return_value=False):
                result = asyncio.run(
                    _download_music_cover("http://127.0.0.1/x.jpg", tmp, "job")
                )
            self.assertIsNone(result)


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


class TestInstagramEmbedFallback(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_cookie_preferences(cookies_from_browser="none", cookies_file="")

    def tearDown(self):
        set_cookie_preferences(cookies_from_browser="none", cookies_file="")

    def _context_html(self, media):
        context = {"context": json.dumps({"media": media})}
        payload = {"contextJSON": json.dumps(context)}
        return (
            "<html><head></head><body>"
            f"<script type=\"application/json\">{json.dumps(payload)}</script>"
            "</body></html>"
        )

    async def test_gql_data_object_parses(self):
        gql = {
            "graphql": {
                "shortcode_media": {
                    "display_url": "https://scontent.cdninstagram.com/v/gql.jpg",
                    "edge_media_to_caption": {"edges": [{"node": {"text": "GQL post"}}]},
                    "owner": {"username": "gqluser"},
                }
            }
        }
        html = (
            "<html><body><script>"
            f'window.__additionalDataLoaded("/p/GQL1/", {json.dumps(gql)});'
            "</script></body></html>"
        )
        with _fake_http(
            {"instagram.com/p/GQL1/embed/captioned": _FakeResponse(html)}
        ):
            info = await _instagram_embed_info("https://www.instagram.com/p/GQL1/")

        self.assertIsNotNone(info)
        self.assertEqual(info.title, "GQL post")
        self.assertEqual(info.uploader, "gqluser")
        self.assertEqual(info.images, ["https://scontent.cdninstagram.com/v/gql.jpg"])

    def test_embed_fetch_uses_crawler_user_agent(self):
        # Browser UAs receive the login shell with no contextJSON.
        self.assertIn("facebookexternalhit", _IG_EMBED_UA.lower())

    def test_shortcode_parsing(self):
        self.assertEqual(
            _instagram_shortcode("https://www.instagram.com/p/ABC123/?img_index=1"),
            ("p", "ABC123"),
        )
        self.assertEqual(
            _instagram_shortcode("instagram.com/reel/Reel_9/"), ("reel", "Reel_9")
        )
        self.assertEqual(
            _instagram_shortcode("https://www.instagram.com/de/tv/TV42/"),
            ("tv", "TV42"),
        )
        self.assertEqual(
            _instagram_shortcode("https://instagram.com/reels/abc"), ("reels", "abc")
        )
        self.assertIsNone(_instagram_shortcode("https://example.com/p/abc"))
        self.assertIsNone(_instagram_shortcode("https://notinstagram.com/reel/abc"))
        self.assertIsNone(_instagram_shortcode("https://www.instagram.com/stories/abc"))

    async def test_context_json_image_post(self):
        media = {
            "shortcode_media": {
                "is_video": False,
                "display_url": "https://scontent.cdninstagram.com/v/low.jpg",
                "display_resources": [
                    {
                        "src": "https://scontent.cdninstagram.com/v/mid.jpg",
                        "config_width": 640,
                        "config_height": 640,
                    },
                    {
                        "src": "https://scontent.cdninstagram.com/v/high.jpg",
                        "config_width": 1080,
                        "config_height": 1080,
                    },
                ],
                "edge_media_to_caption": {
                    "edges": [{"node": {"text": "Golden hour\nSecond line"}}]
                },
                "owner": {"username": "shutterbug"},
            }
        }
        html = self._context_html(media)
        with _fake_http(
            {"instagram.com/p/ABC123/embed/captioned": _FakeResponse(html)}
        ):
            info = await _instagram_embed_info("https://www.instagram.com/p/ABC123/")

        self.assertIsNotNone(info)
        self.assertEqual(info.title, "Golden hour")
        self.assertEqual(info.uploader, "shutterbug")
        self.assertEqual(info.media_type, "image")
        self.assertEqual(info.images, ["https://scontent.cdninstagram.com/v/high.jpg"])
        self.assertEqual(info.thumbnail, "https://scontent.cdninstagram.com/v/high.jpg")

    async def test_context_json_carousel(self):
        media = {
            "carousel_media": [
                {
                    "display_url": "https://scontent.cdninstagram.com/v/one.jpg",
                    "image_versions2": {
                        "candidates": [
                            {
                                "url": "https://scontent.cdninstagram.com/v/one-big.jpg",
                                "width": 1080,
                                "height": 1080,
                            },
                            {
                                "url": "https://scontent.cdninstagram.com/v/one-small.jpg",
                                "width": 320,
                                "height": 320,
                            },
                        ]
                    },
                },
                {"display_url": "https://scontent.cdninstagram.com/v/two.jpg"},
            ],
            "caption": {"text": "Two photos"},
            "owner": {"username": "two"},
        }
        html = self._context_html(media)
        with _fake_http(
            {"instagram.com/p/CARO/embed/captioned": _FakeResponse(html)}
        ):
            info = await _instagram_embed_info("https://www.instagram.com/p/CARO/")

        self.assertIsNotNone(info)
        self.assertEqual(info.media_type, "carousel")
        self.assertEqual(
            info.images,
            [
                "https://scontent.cdninstagram.com/v/one-big.jpg",
                "https://scontent.cdninstagram.com/v/two.jpg",
            ],
        )
        self.assertEqual(info.title, "Two photos")
        self.assertEqual(info.uploader, "two")

    async def test_mixed_carousel_prefers_images(self):
        media = {
            "carousel_media": [
                {"display_url": "https://scontent.cdninstagram.com/v/still.jpg"},
                {
                    "is_video": True,
                    "video_url": "https://scontent.cdninstagram.com/v/clip.mp4",
                    "display_url": "https://scontent.cdninstagram.com/v/poster.jpg",
                },
            ]
        }
        with _fake_http(
            {"instagram.com/p/MIXED/embed/captioned": _FakeResponse(self._context_html(media))}
        ):
            info = await _instagram_embed_info("https://www.instagram.com/p/MIXED/")

        self.assertIsNotNone(info)
        self.assertEqual(info.media_type, "carousel")
        self.assertEqual(
            info.images, ["https://scontent.cdninstagram.com/v/still.jpg"]
        )

    async def test_reel_uses_kind_embed_when_canonical_has_no_media(self):
        media = {
            "shortcode_media": {
                "display_url": "https://scontent.cdninstagram.com/v/reel.jpg"
            }
        }
        routes = {
            "instagram.com/p/REEL1/embed/captioned": _FakeResponse("<html></html>"),
            "instagram.com/reel/REEL1/embed/captioned": _FakeResponse(
                self._context_html(media)
            ),
        }
        with _fake_http(routes):
            info = await _instagram_embed_info("https://www.instagram.com/reel/REEL1/")

        self.assertIsNotNone(info)
        self.assertEqual(info.images, ["https://scontent.cdninstagram.com/v/reel.jpg"])

    async def test_open_graph_only_fallback(self):
        html = (
            "<html><head>"
            '<meta property="og:title" content="Sunset on Instagram: &quot;Golden hour&quot;">'
            '<meta property="og:image" content="https://scontent.cdninstagram.com/v/og.jpg">'
            '<meta property="og:description" content="fallback">'
            "</head><body></body></html>"
        )
        with _fake_http(
            {"instagram.com/p/OG1/embed/captioned": _FakeResponse(html)}
        ):
            info = await _instagram_embed_info("https://www.instagram.com/p/OG1/")

        self.assertIsNotNone(info)
        self.assertEqual(info.title, "Golden hour")
        self.assertEqual(info.media_type, "image")
        self.assertEqual(info.images, ["https://scontent.cdninstagram.com/v/og.jpg"])
        self.assertEqual(info.thumbnail, "https://scontent.cdninstagram.com/v/og.jpg")

    async def test_video_post_has_thumbnail_but_no_playable_formats(self):
        media = {
            "shortcode_media": {
                "is_video": True,
                "video_duration": 12.5,
                "video_url": "https://scontent.cdninstagram.com/v/clip.mp4",
                "display_url": "https://scontent.cdninstagram.com/v/poster.jpg",
                "owner": {"username": "filmer"},
            }
        }
        with _fake_http(
            {"instagram.com/p/VID1/embed/captioned": _FakeResponse(self._context_html(media))}
        ):
            info = await _instagram_embed_info("https://www.instagram.com/p/VID1/")

        self.assertIsNotNone(info)
        self.assertEqual(info.media_type, "video")
        self.assertEqual(info.duration, 12.5)
        self.assertEqual(info.thumbnail, "https://scontent.cdninstagram.com/v/poster.jpg")
        self.assertEqual(info.formats, [])
        self.assertEqual(info.images, [])

    async def test_extract_info_uses_embed_without_cookies(self):
        fallback = MediaInfo(
            title="Public post",
            thumbnail="https://scontent.cdninstagram.com/v/1.jpg",
            platform="instagram",
            images=["https://scontent.cdninstagram.com/v/1.jpg"],
            media_type="image",
        )
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor, "_instagram_embed_info", AsyncMock(return_value=fallback)
        ), patch.object(
            extractor.yt_dlp, "YoutubeDL", MagicMock()
        ) as ydl:
            info = await extract_info("https://www.instagram.com/p/PUBLIC/")

        self.assertEqual(info.title, "Public post")
        self.assertEqual(info.media_type, "image")
        ydl.assert_not_called()

    async def test_extract_info_embed_fallback_after_login_redirect_with_cookies(self):
        set_cookie_preferences(cookies_from_browser="chrome")
        fallback = MediaInfo(
            title="Locked browser post",
            thumbnail="https://scontent.cdninstagram.com/v/2.jpg",
            platform="instagram",
            images=["https://scontent.cdninstagram.com/v/2.jpg"],
            media_type="image",
        )
        login_error = RuntimeError(
            "ERROR: The webpage request was redirected to the login page. "
            "Use --cookies-from-browser or --cookies to access this content."
        )
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor.yt_dlp, "YoutubeDL", MagicMock(side_effect=login_error)
        ), patch.object(
            extractor, "_instagram_embed_info", AsyncMock(return_value=fallback)
        ) as embed:
            info = await extract_info("https://www.instagram.com/reel/LOCKED/")

        self.assertEqual(info.title, "Locked browser post")
        embed.assert_awaited()

    async def test_extract_info_raises_clean_error_when_embed_also_fails(self):
        login_error = RuntimeError(
            "ERROR: The webpage request was redirected to the login page. "
            "Use --cookies-from-browser or --cookies to access this content."
        )
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor.yt_dlp, "YoutubeDL", MagicMock(side_effect=login_error)
        ), patch.object(
            extractor, "_instagram_embed_info", AsyncMock(return_value=None)
        ):
            with self.assertRaises(ValueError) as raised:
                await extract_info("https://www.instagram.com/p/NOPE/")

        message = str(raised.exception)
        self.assertNotIn("--cookies", message)
        self.assertIn("Sign-in required", message)

    async def test_inspect_entries_uses_embed_without_cookies(self):
        fallback = MediaInfo(
            title="Preview post",
            thumbnail="https://scontent.cdninstagram.com/v/3.jpg",
            platform="instagram",
            images=["https://scontent.cdninstagram.com/v/3.jpg"],
            media_type="image",
        )
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor, "_instagram_embed_info", AsyncMock(return_value=fallback)
        ), patch.object(
            extractor, "_flat_info", MagicMock()
        ) as flat:
            entries = await inspect_entries("https://www.instagram.com/p/PREVIEW/")

        flat.assert_not_called()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["url"], "https://www.instagram.com/p/PREVIEW/")
        self.assertEqual(entries[0]["title"], "Preview post")
        self.assertEqual(entries[0]["platform"], "instagram")
        self.assertEqual(entries[0]["media_type"], "image")
        self.assertEqual(
            entries[0]["thumbnail"], "https://scontent.cdninstagram.com/v/3.jpg"
        )

    async def test_inspect_entries_embed_fallback_after_ytdlp_failure(self):
        set_cookie_preferences(cookies_from_browser="chrome")
        fallback = MediaInfo(
            title="Fallback preview",
            platform="instagram",
            images=["https://scontent.cdninstagram.com/v/4.jpg"],
            media_type="image",
        )
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor, "_flat_info", MagicMock(side_effect=RuntimeError("login page"))
        ), patch.object(
            extractor, "_instagram_embed_info", AsyncMock(return_value=fallback)
        ):
            entries = await inspect_entries("https://www.instagram.com/reel/FALL/")

        self.assertEqual(entries[0]["url"], "https://www.instagram.com/reel/FALL/")
        self.assertEqual(entries[0]["media_type"], "image")


class TestTikTokPhoto(unittest.IsolatedAsyncioTestCase):
    PHOTO_URL = "https://www.tiktok.com/@lucasvisual/photo/7508048429776407830"
    IMAGES = [f"https://cdn.example/{i}.jpg" for i in range(1, 4)]

    def _mobile_html(self, images=None, title="Mobile title"):
        payload = {
            "imagePost": {
                "title": title,
                "images": [
                    {"imageURL": {"urlList": [url, url + "?mirror=1"]}}
                    for url in (images or self.IMAGES)
                ],
            }
        }
        return f"<html><body><script>window.__X = {json.dumps(payload)};</script></body></html>"

    def _embed_html(self, images=None):
        payload = {
            "imagePostInfo": {
                "title": "Embed title",
                "displayImages": [
                    {"urlList": [url, url + "?mirror=1"]}
                    for url in (images or self.IMAGES)
                ],
            }
        }
        return f"<html><body><script>window.__X = {json.dumps(payload)};</script></body></html>"

    def test_parser_embed_shape(self):
        images, title = _parse_tiktok_photo_html(self._embed_html())
        self.assertEqual(images, self.IMAGES)
        self.assertEqual(title, "Embed title")

    def test_parser_mobile_shape(self):
        images, title = _parse_tiktok_photo_html(self._mobile_html())
        self.assertEqual(images, self.IMAGES)
        self.assertEqual(title, "Mobile title")

    def test_parser_keeps_url_list_order_without_duplicates(self):
        html = self._mobile_html(images=self.IMAGES + [self.IMAGES[0]])
        images, _ = _parse_tiktok_photo_html(html)
        self.assertEqual(images, self.IMAGES)

    async def test_fetch_falls_back_to_mobile_page(self):
        routes = {
            "is_from_webapp": _FakeResponse(self._mobile_html()),
            "tiktok.com/@lucasvisual/photo/": _FakeResponse("<html></html>"),
        }
        with patch.object(extractor, "validate_url_not_private", return_value=True):
            with _fake_http(routes):
                images, title = await extractor._fetch_tiktok_photos(self.PHOTO_URL)
        self.assertEqual(images, self.IMAGES)
        self.assertEqual(title, "Mobile title")

    async def test_fetch_falls_back_to_embed_page(self):
        routes = {
            "is_from_webapp": _FakeResponse("<html></html>"),
            "embed/v2/7508048429776407830": _FakeResponse(self._embed_html()),
            "tiktok.com/@lucasvisual/photo/": _FakeResponse("<html></html>"),
        }
        with patch.object(extractor, "validate_url_not_private", return_value=True):
            with _fake_http(routes):
                images, title = await extractor._fetch_tiktok_photos(self.PHOTO_URL)
        self.assertEqual(images, self.IMAGES)
        self.assertEqual(title, "Embed title")

    async def test_extract_info_audio_only_format_is_not_video(self):
        class _AudioOnlyYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                self.url = url
                return {
                    "title": "Audio title",
                    "duration": 16,
                    "formats": [
                        {
                            "format_id": "audio-1",
                            "ext": "m4a",
                            "vcodec": "none",
                            "acodec": "aac",
                            "abr": 128,
                            "filesize": 512000,
                        }
                    ],
                }

        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor,
            "_fetch_tiktok_photos",
            AsyncMock(return_value=(self.IMAGES, "Photo title")),
        ), patch.object(
            extractor.yt_dlp, "YoutubeDL", _AudioOnlyYDL
        ):
            info = await extract_info(self.PHOTO_URL)

        self.assertEqual(info.media_type, "carousel")
        self.assertNotIn(info.media_type, ("video", "audio"))
        self.assertEqual(info.images, self.IMAGES)
        self.assertEqual(info.thumbnail, self.IMAGES[0])
        self.assertEqual(info.title, "Photo title")
        self.assertEqual(info.platform, "tiktok")
        self.assertIsNone(info.duration)
        self.assertEqual(len(info.formats), 1)
        self.assertEqual(info.formats[0].resolution, "audio")
        self.assertEqual(info.formats[0].ext, "m4a")
        self.assertIn("128", info.formats[0].note)

    async def test_extract_info_returns_images_when_ytdlp_fails(self):
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor,
            "_fetch_tiktok_photos",
            AsyncMock(return_value=(self.IMAGES, "Photo title")),
        ), patch.object(
            extractor.yt_dlp,
            "YoutubeDL",
            MagicMock(side_effect=RuntimeError("Unsupported URL")),
        ):
            info = await extract_info(self.PHOTO_URL)

        self.assertEqual(info.media_type, "carousel")
        self.assertEqual(info.images, self.IMAGES)
        self.assertEqual(info.formats, [])
        self.assertIsNone(info.duration)

    async def test_inspect_entries_returns_photo_preview(self):
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(
            extractor,
            "_fetch_tiktok_photos",
            AsyncMock(return_value=(self.IMAGES, "Photo title")),
        ), patch.object(
            extractor, "_flat_info", MagicMock()
        ) as flat:
            entries = await inspect_entries(self.PHOTO_URL)

        flat.assert_not_called()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["url"], self.PHOTO_URL)
        self.assertEqual(entries[0]["title"], "Photo title")
        self.assertEqual(entries[0]["duration"], None)
        self.assertEqual(entries[0]["thumbnail"], self.IMAGES[0])
        self.assertEqual(entries[0]["platform"], "tiktok")
        self.assertEqual(entries[0]["media_type"], "carousel")

    async def test_download_audio_uses_ytdlp_not_photo_zip(self):
        class _DownloadYDL:
            last_url = None
            last_opts = None

            def __init__(self, opts):
                _DownloadYDL.last_opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=True):
                _DownloadYDL.last_url = url
                return {"title": "Audio title"}

        with tempfile.TemporaryDirectory() as tmp:
            job_id = "tiktok-audio"
            with open(os.path.join(tmp, f"{job_id}.mp3"), "wb") as handle:
                handle.write(b"x")
            photo_download = AsyncMock(return_value=("zip", "title"))
            with patch.object(
                extractor, "validate_url_not_private", return_value=True
            ), patch.object(
                extractor, "_download_photo_post", photo_download
            ), patch.object(
                extractor.yt_dlp, "YoutubeDL", _DownloadYDL
            ):
                filepath, _ = await download_media(
                    self.PHOTO_URL, "mp3", "320", tmp, {}, job_id
                )

        photo_download.assert_not_awaited()
        self.assertTrue(filepath.endswith(f"{job_id}.mp3"))
        self.assertEqual(
            _DownloadYDL.last_url,
            "https://www.tiktok.com/@lucasvisual/video/7508048429776407830",
        )
        self.assertIn("bestaudio", _DownloadYDL.last_opts["format"])

    async def test_download_images_uses_photo_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo_download = AsyncMock(return_value=("bundle.zip", "Photo title"))
            with patch.object(
                extractor, "validate_url_not_private", return_value=True
            ), patch.object(
                extractor, "_download_photo_post", photo_download
            ), patch.object(
                extractor.yt_dlp, "YoutubeDL", MagicMock()
            ) as ydl:
                filepath, title = await download_media(
                    self.PHOTO_URL, "images", "1080", tmp, {}, "tiktok-images"
                )

        ydl.assert_not_called()
        photo_download.assert_awaited_once()
        self.assertEqual(photo_download.await_args.args[0], self.PHOTO_URL)
        self.assertEqual((filepath, title), ("bundle.zip", "Photo title"))

    async def test_download_legacy_video_request_uses_photo_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo_download = AsyncMock(return_value=("bundle.zip", "Photo title"))
            with patch.object(
                extractor, "validate_url_not_private", return_value=True
            ), patch.object(
                extractor, "_download_photo_post", photo_download
            ), patch.object(
                extractor.yt_dlp, "YoutubeDL", MagicMock()
            ) as ydl:
                await download_media(
                    self.PHOTO_URL, "mp4", "1080", tmp, {}, "tiktok-legacy"
                )

        ydl.assert_not_called()
        photo_download.assert_awaited_once()


class TestCookieOptionInjection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_cookie_preferences(cookies_from_browser="none", cookies_file="")

    def tearDown(self):
        set_cookie_preferences(cookies_from_browser="none", cookies_file="")

    async def test_cookiefile_reaches_info_flat_and_download_options(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# Netscape HTTP Cookie File\n")
            set_cookie_preferences(cookies_from_browser="none", cookies_file=path)
            with patch.object(
                extractor, "validate_url_not_private", return_value=True
            ), patch.object(extractor.yt_dlp, "YoutubeDL", _FakeYoutubeDL):
                await extract_info("https://vimeo.com/1")
                self.assertEqual(
                    _FakeYoutubeDL.last_opts["cookiefile"], os.path.realpath(path)
                )
                self.assertNotIn("cookiesfrombrowser", _FakeYoutubeDL.last_opts)

                _flat_info("https://vimeo.com/1")
                self.assertEqual(
                    _FakeYoutubeDL.last_opts["cookiefile"], os.path.realpath(path)
                )

            opts = _build_ydl_opts(
                "mp4", "1080", "%(id)s.%(ext)s", lambda _d: None, "https://vimeo.com/1"
            )
            self.assertEqual(opts["cookiefile"], os.path.realpath(path))
        finally:
            set_cookie_preferences(cookies_from_browser="none", cookies_file="")
            os.remove(path)

    async def test_browser_cookies_reach_extract_info(self):
        set_cookie_preferences(cookies_from_browser="edge")
        with patch.object(
            extractor, "validate_url_not_private", return_value=True
        ), patch.object(extractor.yt_dlp, "YoutubeDL", _FakeYoutubeDL):
            await extract_info("https://vimeo.com/1")
        self.assertEqual(_FakeYoutubeDL.last_opts["cookiesfrombrowser"], ("edge",))
        self.assertNotIn("cookiefile", _FakeYoutubeDL.last_opts)


class TestErrorSanitization(unittest.TestCase):
    def test_cookie_lock_messages(self):
        for message in (
            "ERROR: Could not copy Chrome cookie database. Permission denied",
            "ERROR: cookie database is locked",
            "ERROR: database is locked while reading cookies",
            "ERROR: Permission denied opening Chrome cookies",
        ):
            with self.subTest(message=message):
                self.assertEqual(classify_error(message), "COOKIE_LOCKED")
                code, user_message = diagnostic_message(message)
                self.assertEqual(code, "COOKIE_LOCKED")
                self.assertIn("Close Chrome/Edge", user_message)
                self.assertEqual(error_action(code), "open_settings")

    def test_plain_permission_denied_is_not_cookie_locked(self):
        self.assertNotEqual(classify_error("Permission denied"), "COOKIE_LOCKED")

    def test_login_redirect_is_clean_cookie_required(self):
        message = (
            "ERROR: The webpage request was redirected to the login page. "
            "Use --cookies-from-browser or --cookies to access this content."
        )
        self.assertEqual(classify_error(message), "COOKIE_REQUIRED")
        code, user_message = diagnostic_message(message)
        self.assertEqual(code, "COOKIE_REQUIRED")
        self.assertNotIn("--cookies", user_message)
        self.assertIn("Browser Cookies", user_message)
        self.assertEqual(error_action(code), "open_settings")

    def test_error_actions(self):
        for code in ("AUTH_403", "COOKIE_REQUIRED", "COOKIE_LOCKED", "RATE_LIMIT"):
            with self.subTest(code=code):
                self.assertEqual(error_action(code), "open_settings")
        self.assertIsNone(error_action("UNSUPPORTED_URL"))
        self.assertIsNone(error_action("UNKNOWN"))


# Fixtures in tests/fixtures were captured 2026-10-27 from live public pages and then
# trimmed/sanitised (signed query values replaced with REDACTED). Known gaps: TikTok
# embed/v2/<id> answered 503 "overload-protect triggered" (that shape stays covered by
# TestTikTokPhoto above), and the desktop photo page now ships a shell without
# imagePost/api-data (covered by the desktop fixture plus the fetch fallback test below).
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture(*parts):
    with open(os.path.join(FIXTURES_DIR, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestCapturedTikTokFixtures(unittest.IsolatedAsyncioTestCase):
    PHOTO_TITLE = "Images The Photographer Couldn\u2019t Believe They Captured"

    def test_mobile_html_fixture(self):
        html = _fixture("tiktok", "photo_mobile.html")
        images, title = _parse_tiktok_photo_html(html)

        self.assertEqual(title, self.PHOTO_TITLE)
        self.assertEqual(len(images), 3)
        self.assertEqual(len(set(images)), 3)
        self.assertTrue(
            images[0].startswith(
                "https://p16-common-sign.tiktokcdn.com/tos-no1a-i-photomode-no/"
                "2ad7b76051ee4df1a900e884b6e3891e~tplv-photomode-image.jpeg?"
            )
        )
        # urlList keeps its order: the p19 mirror URL is never picked.
        self.assertNotIn("p19-common-sign", images[0])
        self.assertIn("x-signature=REDACTED", images[0])
        self.assertNotIn("J%2B", html)

    def test_desktop_html_fixture_is_a_shell(self):
        html = _fixture("tiktok", "photo_desktop.html")

        self.assertIn("__UNIVERSAL_DATA_FOR_REHYDRATION__", html)
        self.assertNotIn('"imagePost"', html)
        self.assertEqual(_parse_tiktok_photo_html(html), ([], None))

    async def test_fetch_falls_back_from_desktop_to_mobile_fixture(self):
        fetch = AsyncMock(
            side_effect=[
                _fixture("tiktok", "photo_desktop.html"),
                _fixture("tiktok", "photo_mobile.html"),
            ]
        )
        with patch.object(extractor, "_tiktok_fetch_html", fetch):
            images, title = await extractor._fetch_tiktok_photos(
                "https://www.tiktok.com/@lucasvisual/photo/7508048429776407830"
            )

        self.assertEqual(title, self.PHOTO_TITLE)
        self.assertEqual(len(images), 3)
        self.assertEqual(fetch.await_count, 2)
        desktop_url, desktop_ua = fetch.await_args_list[0].args
        mobile_url, mobile_ua = fetch.await_args_list[1].args
        self.assertNotIn("is_from_webapp", desktop_url)
        self.assertEqual(desktop_ua, extractor.TIKTOK_UA)
        self.assertIn("is_from_webapp=1", mobile_url)
        self.assertEqual(mobile_ua, extractor._TIKTOK_MOBILE_UA)


class TestCapturedInstagramFixtures(unittest.TestCase):
    def test_embed_captioned_fixture_parses_public_carousel(self):
        html = _fixture("instagram", "embed_captioned.html")

        info = extractor._instagram_media_info(html)

        # Captured with the facebookexternalhit crawler UA the app sends.
        # Re-capturing with a browser UA yields the login shell instead.
        self.assertIsNotNone(info)
        self.assertEqual(info.media_type, "carousel")
        self.assertEqual(len(info.images), 7)
        self.assertTrue(all(url.startswith("https://") for url in info.images))
        self.assertTrue(info.title)
        self.assertIn("=REDACTED", info.images[0])

    def test_gated_login_wall_fixture_has_no_media(self):
        html = _fixture("instagram", "gated_login_wall.html")

        self.assertIn("<title>Login", html)
        self.assertIsNone(extractor._meta_content(html, "og:image"))
        self.assertIsNone(extractor._instagram_media_info(html))


class TestCapturedSpotifyFixture(unittest.IsolatedAsyncioTestCase):
    async def test_track_embed_fixture_resolves_metadata(self):
        get_text = AsyncMock(return_value=_fixture("spotify", "track_embed.html"))
        with patch.object(extractor, "_get_text", get_text):
            data = await extractor._resolve_spotify(
                "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
            )

        self.assertEqual(data["platform"], "spotify")
        self.assertEqual(data["media_type"], "track")
        self.assertEqual(data["title"], "Never Gonna Give You Up")
        self.assertEqual(data["artist"], "Rick Astley")
        self.assertIsNone(data["album"])
        entry = data["entries"][0]
        self.assertEqual(
            entry["url"], "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
        )
        self.assertEqual(entry["duration"], 214)
        self.assertEqual(
            entry["search_query"], "Rick Astley - Never Gonna Give You Up official audio"
        )
        get_text.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
