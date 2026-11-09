import asyncio
import hashlib
import io
import os
import re
import shutil
import tempfile
import threading
import zipfile
from typing import Any, Callable, Dict, Optional

import httpx

from app.services import ytdlp_loader

yt_dlp = ytdlp_loader.import_ytdlp()
USER_EXTRACTOR_DIR = ytdlp_loader.USER_EXTRACTOR_DIR

PYPI_JSON_URL = "https://pypi.org/pypi/yt-dlp/json"
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
MAX_WHEEL_MEMBERS = 5000
MAX_UPDATE_SECONDS = 5 * 60


class ExtractorUpdateCancelled(Exception):
    pass


def _version_key(value: str) -> tuple:
    return tuple(int(part) for part in re.findall(r"\d+", str(value))) or (0,)


def _sha256_matches(data: bytes, expected: str) -> bool:
    """PyPI always publishes a digest; an absent one is not a pass."""
    return bool(expected) and hashlib.sha256(data).hexdigest() == expected.lower()


def _bundled_version() -> str:
    return yt_dlp.version.__version__


def _user_version() -> Optional[str]:
    version_file = USER_EXTRACTOR_DIR / "yt_dlp" / "version.py"
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    return match.group(1) if match else None


def get_extractor_status() -> Dict[str, Any]:
    active = _bundled_version()
    user = _user_version()
    return {
        "active_version": active,
        "user_version": user,
        "source": "user" if user == active else "bundled",
        "location": str(USER_EXTRACTOR_DIR),
        "restart_required": bool(user and user != active),
    }


async def _fetch_pypi_release() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(PYPI_JSON_URL)
        response.raise_for_status()
        return response.json()


def _install_wheel(
    data: bytes, cancelled: Optional[Callable[[], bool]] = None
) -> str:
    if cancelled and cancelled():
        raise ExtractorUpdateCancelled("yt-dlp update cancelled")

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Downloaded yt-dlp package is not a valid wheel") from exc

    members = archive.infolist()
    if len(members) > MAX_WHEEL_MEMBERS:
        raise ValueError("Downloaded yt-dlp package has too many files")
    if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("Downloaded yt-dlp package is too large")

    user_dir = USER_EXTRACTOR_DIR
    user_dir.mkdir(parents=True, exist_ok=True)
    ytdlp_loader.recover_backup(user_dir)
    target_package = user_dir / "yt_dlp"
    backup = user_dir / "yt_dlp.backup"
    if backup.exists():
        if not target_package.exists():
            raise ValueError("Could not recover the previous yt-dlp package")
        shutil.rmtree(backup, ignore_errors=True)

    staging = tempfile.mkdtemp(prefix=".ytdlp-update-", dir=str(user_dir))
    staging_package = os.path.join(staging, "yt_dlp")
    try:
        for member in members:
            name = member.filename
            if not name.startswith("yt_dlp/"):
                continue
            parts = name.split("/")
            if name.startswith("/") or ".." in parts or not parts[1:]:
                raise ValueError("Downloaded yt-dlp package contains an unsafe path")
            target = os.path.join(staging, *parts)
            real_target = os.path.realpath(target)
            if not real_target.startswith(os.path.realpath(staging) + os.sep):
                raise ValueError("Downloaded yt-dlp package contains an unsafe path")
            if member.is_dir():
                os.makedirs(real_target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(real_target), exist_ok=True)
            with archive.open(member) as source, open(real_target, "wb") as out:
                shutil.copyfileobj(source, out)

        if not os.path.isfile(os.path.join(staging_package, "__init__.py")):
            raise ValueError("Downloaded yt-dlp package is incomplete")

        if cancelled and cancelled():
            raise ExtractorUpdateCancelled("yt-dlp update cancelled")
        if target_package.exists():
            os.replace(target_package, backup)
        if cancelled and cancelled():
            if backup.exists() and not target_package.exists():
                os.replace(backup, target_package)
            raise ExtractorUpdateCancelled("yt-dlp update cancelled")
        try:
            os.replace(staging_package, target_package)
        except Exception:
            if backup.exists() and not target_package.exists():
                os.replace(backup, target_package)
            raise
        if cancelled and cancelled():
            shutil.rmtree(target_package, ignore_errors=True)
            if backup.exists():
                os.replace(backup, target_package)
            raise ExtractorUpdateCancelled("yt-dlp update cancelled")
        shutil.rmtree(backup, ignore_errors=True)
        return str(target_package)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def _update_extractor(
    cancel_event: Optional[asyncio.Event],
    cancel_flag: threading.Event,
) -> Dict[str, Any]:
    if cancel_event and cancel_event.is_set():
        cancel_flag.set()
        raise ExtractorUpdateCancelled("yt-dlp update cancelled")
    before = get_extractor_status()
    release = await _fetch_pypi_release()
    info = release.get("info") or {}
    latest = str(info.get("version") or "")
    if not latest:
        raise ValueError("PyPI did not return a yt-dlp version")

    if _version_key(latest) <= _version_key(before["active_version"]):
        return {
            **before,
            "updated": False,
            "latest_version": latest,
            "message": "yt-dlp is already up to date",
        }

    wheel = next(
        (
            item
            for item in release.get("urls") or []
            if item.get("packagetype") == "bdist_wheel"
            and str(item.get("filename", "")).startswith("yt_dlp-")
            and item.get("url")
        ),
        None,
    )
    wheel_url = wheel.get("url") if wheel else None
    if not wheel_url:
        raise ValueError("PyPI did not return a yt-dlp wheel")
    expected_sha256 = str(((wheel or {}).get("digests") or {}).get("sha256") or "").lower()

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        async with client.stream("GET", wheel_url) as response:
            response.raise_for_status()
            chunks = []
            total = 0
            async for chunk in response.aiter_bytes(64 * 1024):
                if cancel_event and cancel_event.is_set():
                    cancel_flag.set()
                    raise ExtractorUpdateCancelled("yt-dlp update cancelled")
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError("yt-dlp package download exceeded the 40 MB limit")
                chunks.append(chunk)
    data = b"".join(chunks)

    if not _sha256_matches(data, expected_sha256):
        raise ValueError("Downloaded yt-dlp package failed its SHA-256 check")

    if cancel_event and cancel_event.is_set():
        cancel_flag.set()
        raise ExtractorUpdateCancelled("yt-dlp update cancelled")
    await asyncio.to_thread(_install_wheel, data, cancel_flag.is_set)
    return {
        **before,
        "updated": True,
        "previous_version": before["active_version"],
        "latest_version": latest,
        "user_version": latest,
        "restart_required": True,
        "message": "yt-dlp updated. Restart the app to use the new extractor.",
    }


async def update_extractor(
    cancel_event: Optional[asyncio.Event] = None,
    total_timeout: float = MAX_UPDATE_SECONDS,
) -> Dict[str, Any]:
    """Download and install the wheel; cancel_event aborts before the live swap."""
    cancel_flag = threading.Event()
    try:
        return await asyncio.wait_for(
            _update_extractor(cancel_event, cancel_flag), total_timeout
        )
    except asyncio.TimeoutError as exc:
        cancel_flag.set()
        raise TimeoutError("yt-dlp update timed out") from exc
    except asyncio.CancelledError:
        cancel_flag.set()
        raise
