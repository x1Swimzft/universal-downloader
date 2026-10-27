"""Load the user-installed yt-dlp copy safely, before the bundled one.

Two invariants:
  * the finder goes on sys.meta_path BEFORE yt_dlp is imported, otherwise a
    fresh user copy never takes effect until the next process;
  * a corrupt user copy can never shadow the bundled package - it is validated
    and quarantined instead, and the import falls back to the bundled copy.
"""

from __future__ import annotations

import os
import py_compile
import shutil
import sys
import time
from importlib.machinery import PathFinder
from pathlib import Path
from typing import Optional

USER_EXTRACTOR_DIR = Path(
    os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
) / "UniversalDownloader" / "bin"

# Files that must parse before the copy is trusted. Compiling the whole package
# on every start is too slow; __init__ + version catches a truncated or
# partially written wheel, and import_ytdlp() is the backstop for the rest.
_REQUIRED_FILES = ("__init__.py", "version.py")


class _UserYtDlpFinder:
    def __init__(self, root: Path):
        self.root = str(root)

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "yt_dlp" or fullname.startswith("yt_dlp."):
            return PathFinder.find_spec(
                fullname, path if path is not None else [self.root]
            )
        return None


_active_finder: Optional[_UserYtDlpFinder] = None


def user_package_dir() -> Path:
    return USER_EXTRACTOR_DIR / "yt_dlp"


def user_copy_present() -> bool:
    return (user_package_dir() / "__init__.py").is_file()


def user_copy_problem() -> Optional[str]:
    """Return why the user copy cannot be trusted, or None when it is sane."""
    package = user_package_dir()
    for name in _REQUIRED_FILES:
        if not (package / name).is_file():
            return f"missing {name}"
    for name in _REQUIRED_FILES:
        try:
            py_compile.compile(str(package / name), doraise=True)
        except (py_compile.PyCompileError, OSError) as exc:
            return str(exc).splitlines()[0]
    return None


def quarantine(reason: str = "") -> Optional[str]:
    """Rename the broken copy out of the way so it stops shadowing the bundle."""
    package = user_package_dir()
    if not package.exists():
        return None
    target = package.with_name(f"yt_dlp.broken-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.move(str(package), str(target))
    except OSError:
        return None
    if reason:
        try:
            (target.parent / (target.name + ".reason.txt")).write_text(
                reason, encoding="utf-8"
            )
        except OSError:
            pass
    return str(target)


def activate() -> str:
    """Install the finder if the user copy is sane. Returns 'user' or 'bundled'."""
    global _active_finder
    if _active_finder is not None:
        return "user"
    if not user_copy_present():
        return "bundled"
    problem = user_copy_problem()
    if problem:
        quarantine(problem)
        return "bundled"
    finder = _UserYtDlpFinder(USER_EXTRACTOR_DIR)
    sys.meta_path.insert(0, finder)
    _active_finder = finder
    return "user"


def deactivate() -> None:
    global _active_finder
    if _active_finder is None:
        return
    try:
        sys.meta_path.remove(_active_finder)
    except ValueError:
        pass
    _active_finder = None


def _drop_imported_modules() -> None:
    for name in [n for n in sys.modules if n == "yt_dlp" or n.startswith("yt_dlp.")]:
        del sys.modules[name]


def import_ytdlp():
    """Import yt_dlp with the user copy first, falling back to the bundled one."""
    activate()
    try:
        import yt_dlp

        return yt_dlp
    except Exception as exc:  # a half-written copy can fail at import time
        deactivate()
        _drop_imported_modules()
        quarantine(f"import failed: {exc}")
        import yt_dlp

        return yt_dlp
