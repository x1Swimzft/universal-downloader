import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
