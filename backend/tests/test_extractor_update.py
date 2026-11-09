import asyncio
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services import extractor_update, ytdlp_loader


def _write_package(root, version="2099.1.1", body=None):
    package = os.path.join(root, "yt_dlp")
    os.makedirs(package, exist_ok=True)
    with open(os.path.join(package, "__init__.py"), "w", encoding="utf-8") as fh:
        fh.write("from . import version\n")
    with open(os.path.join(package, "version.py"), "w", encoding="utf-8") as fh:
        fh.write(body if body is not None else f"__version__ = {version!r}\n")
    return package


class TestUserCopyActivation(unittest.TestCase):
    def setUp(self):
        # The module-level import_ytdlp() activates the real user copy.
        ytdlp_loader.deactivate()

    def tearDown(self):
        ytdlp_loader.deactivate()

    def test_sound_user_copy_is_activated(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            ytdlp_loader, "USER_EXTRACTOR_DIR", ytdlp_loader.Path(tmp)
        ):
            _write_package(tmp)
            self.assertEqual(ytdlp_loader.activate(), "user")
            self.assertTrue(
                any(
                    isinstance(finder, ytdlp_loader._UserYtDlpFinder)
                    for finder in sys.meta_path
                )
            )

    def test_broken_user_copy_is_quarantined_and_ignored(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            ytdlp_loader, "USER_EXTRACTOR_DIR", ytdlp_loader.Path(tmp)
        ):
            package = _write_package(tmp, body="def broken(:\n")
            self.assertEqual(ytdlp_loader.activate(), "bundled")
            self.assertFalse(os.path.exists(package))
            self.assertEqual(
                len([n for n in os.listdir(tmp) if n.startswith("yt_dlp.broken-") and os.path.isdir(os.path.join(tmp, n))]), 1
            )
            self.assertFalse(
                any(
                    isinstance(finder, ytdlp_loader._UserYtDlpFinder)
                    for finder in sys.meta_path
                )
            )

    def test_missing_version_file_is_treated_as_broken(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            ytdlp_loader, "USER_EXTRACTOR_DIR", ytdlp_loader.Path(tmp)
        ):
            package = os.path.join(tmp, "yt_dlp")
            os.makedirs(package)
            open(os.path.join(package, "__init__.py"), "w").close()

            self.assertEqual(ytdlp_loader.activate(), "bundled")
            self.assertFalse(os.path.exists(package))

    def test_finder_is_installed_before_yt_dlp_is_imported(self):
        # The original bug: importing extractor_update first reported the bundled
        # version even with a newer user copy on disk. Run in a clean process.
        with tempfile.TemporaryDirectory() as tmp:
            _write_package(os.path.join(tmp, "UniversalDownloader", "bin"), version="2099.9.9")
            env = dict(os.environ, LOCALAPPDATA=tmp, PYTHONPATH=BACKEND_DIR)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from app.services import extractor_update as e;"
                    "print(e._bundled_version())",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2099.9.9")


class TestWheelDigest(unittest.TestCase):
    def test_matching_digest_is_accepted(self):
        import hashlib

        data = b"wheel-bytes"
        expected = hashlib.sha256(data).hexdigest()
        self.assertTrue(extractor_update._sha256_matches(data, expected))
        self.assertTrue(extractor_update._sha256_matches(data, expected.upper()))

    def test_mismatch_and_missing_digest_are_rejected(self):
        self.assertFalse(extractor_update._sha256_matches(b"wheel-bytes", "0" * 64))
        self.assertFalse(extractor_update._sha256_matches(b"wheel-bytes", ""))


def _wheel_bytes(version="9999.1.1"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("yt_dlp/__init__.py", "from . import version\n")
        archive.writestr("yt_dlp/version.py", f"__version__ = {version!r}\n")
    return buffer.getvalue()


def _read_version(package):
    with open(os.path.join(package, "version.py"), encoding="utf-8") as handle:
        return handle.read()


class _SlowResponse:
    def __init__(self, cancel_event=None, delay=0.0):
        self.cancel_event = cancel_event
        self.delay = delay

    def raise_for_status(self):
        pass

    async def aiter_bytes(self, size):
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.delay:
            await asyncio.sleep(self.delay)
        yield b"x" * 1024


def _fake_client(response):
    class Stream:
        async def __aenter__(self):
            return response

        async def __aexit__(self, *args):
            return False

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url):
            return Stream()

    return Client()


class TestBackupRecovery(unittest.TestCase):
    def setUp(self):
        ytdlp_loader.deactivate()

    def tearDown(self):
        ytdlp_loader.deactivate()

    def test_missing_live_copy_restores_backup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            ytdlp_loader, "USER_EXTRACTOR_DIR", Path(tmp)
        ):
            _write_package(tmp, version="2099.2.2")
            os.replace(
                os.path.join(tmp, "yt_dlp"), os.path.join(tmp, "yt_dlp.backup")
            )

            self.assertEqual(ytdlp_loader.activate(), "user")
            self.assertIn("2099.2.2", _read_version(os.path.join(tmp, "yt_dlp")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "yt_dlp.backup")))

    def test_broken_live_copy_is_replaced_by_backup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            ytdlp_loader, "USER_EXTRACTOR_DIR", Path(tmp)
        ):
            _write_package(tmp, body="def broken(:\n")
            backup_src = os.path.join(tmp, "backup-src")
            _write_package(backup_src, version="2099.3.3")
            os.replace(
                os.path.join(backup_src, "yt_dlp"),
                os.path.join(tmp, "yt_dlp.backup"),
            )

            self.assertEqual(ytdlp_loader.activate(), "user")
            self.assertIn("2099.3.3", _read_version(os.path.join(tmp, "yt_dlp")))
            self.assertEqual(
                len(
                    [
                        name
                        for name in os.listdir(tmp)
                        if name.startswith("yt_dlp.broken-")
                        and os.path.isdir(os.path.join(tmp, name))
                    ]
                ),
                1,
            )

    def test_sane_live_copy_discards_stale_backup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            ytdlp_loader, "USER_EXTRACTOR_DIR", Path(tmp)
        ):
            _write_package(tmp, version="2099.4.4")
            backup_src = os.path.join(tmp, "backup-src")
            _write_package(backup_src, version="2099.4.5")
            os.replace(
                os.path.join(backup_src, "yt_dlp"),
                os.path.join(tmp, "yt_dlp.backup"),
            )

            self.assertEqual(ytdlp_loader.activate(), "user")
            self.assertIn("2099.4.4", _read_version(os.path.join(tmp, "yt_dlp")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "yt_dlp.backup")))


class TestWheelCancellation(unittest.TestCase):
    def test_cancel_after_staging_leaves_live_copy(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            extractor_update, "USER_EXTRACTOR_DIR", Path(tmp)
        ):
            _write_package(tmp, version="2099.5.5")
            calls = {"count": 0}

            def cancelled():
                calls["count"] += 1
                return calls["count"] >= 2

            with self.assertRaises(extractor_update.ExtractorUpdateCancelled):
                extractor_update._install_wheel(
                    _wheel_bytes("9999.1.1"), cancelled=cancelled
                )

            self.assertIn("2099.5.5", _read_version(os.path.join(tmp, "yt_dlp")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "yt_dlp.backup")))


class TestWheelInstallRecovery(unittest.TestCase):
    def test_install_recovers_backup_before_replacing_it(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            extractor_update, "USER_EXTRACTOR_DIR", Path(tmp)
        ):
            _write_package(tmp, version="2099.8.8")
            os.replace(
                os.path.join(tmp, "yt_dlp"), os.path.join(tmp, "yt_dlp.backup")
            )

            extractor_update._install_wheel(_wheel_bytes("9999.1.1"))

            self.assertIn("9999.1.1", _read_version(os.path.join(tmp, "yt_dlp")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "yt_dlp.backup")))


class TestWheelUpdateGuards(unittest.IsolatedAsyncioTestCase):
    def _release(self):
        return {
            "info": {"version": "9999.1.1"},
            "urls": [
                {
                    "packagetype": "bdist_wheel",
                    "filename": "yt_dlp-9999.1.1-py3-none-any.whl",
                    "url": "https://example.invalid/wheel",
                    "digests": {"sha256": "0" * 64},
                }
            ],
        }

    async def test_total_timeout_leaves_live_copy(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            extractor_update, "USER_EXTRACTOR_DIR", Path(tmp)
        ), patch.object(
            extractor_update,
            "_fetch_pypi_release",
            AsyncMock(return_value=self._release()),
        ):
            _write_package(tmp, version="2099.7.7")
            response = _SlowResponse(delay=0.5)
            with patch.object(
                extractor_update.httpx,
                "AsyncClient",
                lambda *args, **kwargs: _fake_client(response),
            ):
                with self.assertRaises(TimeoutError):
                    await extractor_update.update_extractor(total_timeout=0.05)

            self.assertIn("2099.7.7", _read_version(os.path.join(tmp, "yt_dlp")))

    async def test_cancel_event_leaves_live_copy(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            extractor_update, "USER_EXTRACTOR_DIR", Path(tmp)
        ), patch.object(
            extractor_update,
            "_fetch_pypi_release",
            AsyncMock(return_value=self._release()),
        ):
            _write_package(tmp, version="2099.7.7")
            cancel_event = asyncio.Event()
            response = _SlowResponse(cancel_event=cancel_event)
            with patch.object(
                extractor_update.httpx,
                "AsyncClient",
                lambda *args, **kwargs: _fake_client(response),
            ):
                with self.assertRaises(extractor_update.ExtractorUpdateCancelled):
                    await extractor_update.update_extractor(cancel_event=cancel_event)

            self.assertIn("2099.7.7", _read_version(os.path.join(tmp, "yt_dlp")))


if __name__ == "__main__":
    unittest.main()
