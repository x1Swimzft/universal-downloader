"""Audio-gating matrix: music sources must never be turned into video.

Covers fmt x social_bypass x source, the audio-only presets, and
_find_output_file() extension preference. Fully offline: the yt-dlp
boundary and all network helpers are mocked.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services import extractor
from app.services.extractor import (
    _find_output_file,
    _normalize_preset,
    _preset_output_ext,
    download_media,
)

AUDIO_EXTS = (".mp3", ".m4a", ".opus", ".flac")
AUDIO_FMTS = ("mp3", "m4a", "opus")

# name -> (url, search_query passed by the caller)
SOURCES = {
    "spotify": ("https://open.spotify.com/track/abc", None),
    "apple": ("https://music.apple.com/us/album/song/1?i=2", None),
    "youtube-music": ("https://music.youtube.com/watch?v=abc", None),
    "search_query": ("https://www.youtube.com/watch?v=abc", "Artist - Song official audio"),
}

TRACK = {
    "platform": "spotify",
    "title": "Song",
    "artist": "Artist",
    "album": "Album",
    "thumbnail": None,
    "media_type": "track",
    "entries": [
        {
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "track_number": 1,
            "search_query": "Artist - Song official audio",
        }
    ],
}


class _RecordingYDL:
    """Stands in for yt_dlp.YoutubeDL and records the options it is given."""

    last_opts = None
    last_url = None

    def __init__(self, opts):
        type(self).last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=True):
        type(self).last_url = url
        return {"title": "Resolved"}


def _audio_postprocessor(opts):
    for pp in opts.get("postprocessors") or []:
        if pp.get("key") == "FFmpegExtractAudio":
            return pp
    return None


class _GatingHarness(unittest.IsolatedAsyncioTestCase):
    """Runs download_media against a temp dir with every network edge mocked."""

    async def _run(
        self,
        source,
        fmt,
        preset=None,
        social_bypass=False,
        downloaded_ext=None,
    ):
        url, search_query = SOURCES[source]
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        job_id = f"job-{source}-{fmt}-{int(social_bypass)}-{preset or 'none'}"

        # The file yt-dlp would have produced on disk.
        os.makedirs(tmp, exist_ok=True)
        with open(os.path.join(tmp, f"{job_id}.{downloaded_ext or fmt}"), "wb") as fh:
            fh.write(b"x")

        postprocess = MagicMock(side_effect=lambda path, name: path)
        with patch.object(extractor, "validate_url_not_private", return_value=True), patch.object(
            extractor, "resolve_music", AsyncMock(return_value=TRACK)
        ), patch.object(extractor.yt_dlp, "YoutubeDL", _RecordingYDL), patch.object(
            extractor, "_download_music_cover", AsyncMock(return_value=None)
        ), patch.object(
            extractor, "_embed_music_metadata", side_effect=lambda path, meta, cover: path
        ), patch.object(extractor, "_postprocess_file", postprocess):
            filepath, _title = await download_media(
                url,
                fmt,
                "320",
                tmp,
                {},
                job_id,
                preset=preset,
                social_bypass=social_bypass,
                search_query=search_query,
            )

        return filepath, _RecordingYDL.last_opts, _RecordingYDL.last_url, postprocess


class TestAudioGatingMatrix(_GatingHarness):
    async def test_audio_formats_stay_audio_for_every_source_and_bypass(self):
        for source in SOURCES:
            for fmt in AUDIO_FMTS:
                for bypass in (False, True):
                    with self.subTest(source=source, fmt=fmt, social_bypass=bypass):
                        filepath, opts, _url, postprocess = await self._run(
                            source, fmt, social_bypass=bypass
                        )
                        self.assertTrue(
                            filepath.lower().endswith(f".{fmt}"),
                            f"{source}/{fmt} produced {filepath}",
                        )
                        self.assertEqual(opts["format"], "bestaudio/best")
                        self.assertEqual(_audio_postprocessor(opts)["preferredcodec"], fmt)
                        self.assertIsNone(opts["merge_output_format"])
                        # Video-only presets must not run for audio jobs.
                        postprocess.assert_not_called()

    async def test_audio_only_presets_survive_social_bypass(self):
        for source in SOURCES:
            for bypass in (False, True):
                with self.subTest(source=source, preset="audio_lossless", social_bypass=bypass):
                    filepath, opts, _url, postprocess = await self._run(
                        source, "mp3", preset="audio_lossless", social_bypass=bypass
                    )
                    postprocess.assert_called_once()
                    self.assertEqual(postprocess.call_args.args[1], "audio_lossless")
                    self.assertTrue(filepath.lower().endswith(".mp3"))
                    self.assertEqual(_audio_postprocessor(opts)["preferredcodec"], "mp3")

                with self.subTest(source=source, preset="audio_norm", social_bypass=bypass):
                    _, _opts, _u, postprocess = await self._run(
                        source, "mp3", preset="audio_norm", social_bypass=bypass
                    )
                    postprocess.assert_called_once()
                    self.assertEqual(postprocess.call_args.args[1], "audio_norm")

    async def test_video_presets_are_ignored_for_audio_jobs(self):
        for source in SOURCES:
            for preset in ("edit_ready", "social_bypass"):
                with self.subTest(source=source, preset=preset):
                    filepath, _opts, _url, postprocess = await self._run(
                        source,
                        "mp3",
                        preset=preset,
                        social_bypass=(preset == "social_bypass"),
                    )
                    postprocess.assert_not_called()
                    self.assertTrue(filepath.lower().endswith(".mp3"))

    async def test_mp4_request_on_music_sources_becomes_mp3(self):
        for source in ("spotify", "apple", "search_query"):
            for bypass in (False, True):
                with self.subTest(source=source, social_bypass=bypass):
                    filepath, opts, url, postprocess = await self._run(
                        source, "mp4", social_bypass=bypass, downloaded_ext="mp3"
                    )
                    self.assertTrue(filepath.lower().endswith(".mp3"))
                    self.assertEqual(opts["format"], "bestaudio/best")
                    self.assertEqual(
                        _audio_postprocessor(opts)["preferredcodec"], "mp3"
                    )
                    self.assertTrue(url.startswith("ytsearch1:"))
                    self.assertNotIn("spotify.com", url)
                    postprocess.assert_not_called()

    async def test_youtube_music_url_is_not_a_music_source(self):
        # music.youtube.com is not matched by is_music_url(), so an explicit
        # video request stays video. Recorded as behavior, not asserted as desired.
        filepath, opts, url, postprocess = await self._run(
            "youtube-music", "mp4", downloaded_ext="mp4"
        )
        self.assertTrue(filepath.lower().endswith(".mp4"))
        self.assertIn("bestvideo", opts["format"])
        self.assertIsNone(_audio_postprocessor(opts))
        self.assertFalse(url.startswith("ytsearch1:"))
        postprocess.assert_not_called()


class TestFindOutputFilePreference(unittest.TestCase):
    def test_prefers_requested_audio_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ("mp4", "mp3", "m4a"):
                open(os.path.join(tmp, f"job1.{ext}"), "wb").close()
            self.assertTrue(
                _find_output_file(tmp, "job1", "mp3").lower().endswith(".mp3")
            )
            self.assertTrue(
                _find_output_file(tmp, "job1", "MP3").lower().endswith(".mp3")
            )
            self.assertTrue(
                _find_output_file(tmp, "job1", "m4a").lower().endswith(".m4a")
            )

    def test_ignores_partial_downloads_and_covers(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "job2.mp3"), "wb").close()
            open(os.path.join(tmp, "job2.mp4.part"), "wb").close()
            open(os.path.join(tmp, "job2.webm.ytdl"), "wb").close()
            open(os.path.join(tmp, "job2.cover.jpg"), "wb").close()
            self.assertTrue(_find_output_file(tmp, "job2").endswith("job2.mp3"))

    def test_missing_preferred_extension_falls_back_to_available_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "job3.opus"), "wb").close()
            self.assertTrue(_find_output_file(tmp, "job3", "mp3").endswith("job3.opus"))

    def test_raises_when_nothing_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                _find_output_file(tmp, "nope", "mp3")


class TestPresetNormalization(unittest.TestCase):
    def test_audio_jobs_never_get_video_presets(self):
        for preset in (None, "", "none"):
            self.assertIsNone(_normalize_preset(preset, True, audio=True))
        for preset in ("edit_ready", "audio_norm", "audio_lossless", "social_bypass"):
            self.assertEqual(_normalize_preset(preset, True, audio=True), preset)
        self.assertEqual(_normalize_preset("edit_ready", True, audio=False), "social_bypass")
        self.assertEqual(_normalize_preset(None, True, audio=False), "social_bypass")

    def test_non_audio_preset_names_map_to_expected_containers(self):
        self.assertEqual(_preset_output_ext("audio_norm"), ".m4a")
        self.assertEqual(_preset_output_ext("audio_lossless"), ".flac")
        self.assertEqual(_preset_output_ext("edit_ready"), ".mp4")
        self.assertEqual(_preset_output_ext("social_bypass"), ".mp4")

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            _normalize_preset("lossless_mp3", False, audio=True)


if __name__ == "__main__":
    unittest.main()
