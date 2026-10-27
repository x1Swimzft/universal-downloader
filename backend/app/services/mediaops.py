"""Presets, ffmpeg arguments, post-processing, filenames and clip parsing."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Any, List, Optional


PRESET_CHOICES = ("edit_ready", "audio_norm", "audio_lossless", "social_bypass")


AUDIO_FILENAME_TEMPLATES = (
    "{track} - {artist} - {title}",
    "{artist} - {title}",
    "{title} ({artist})",
    "{title}",
)


_TIMESTAMP_RE = re.compile(r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\s*$")
_SECONDS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")


def parse_timestamp(value: Optional[Any]) -> Optional[float]:
    """Parse MM:SS, HH:MM:SS, or raw seconds into a non-negative number."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid timestamp")
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value)
        match = _TIMESTAMP_RE.match(text)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2))
            secs = int(match.group(3))
            fraction = match.group(4) or "0"
            if minutes > 59 or secs > 59:
                raise ValueError("Timestamp minutes and seconds must be below 60")
            seconds = hours * 3600 + minutes * 60 + secs + int(fraction.ljust(3, "0")) / 1000
        else:
            match = _SECONDS_RE.match(text)
            if not match:
                raise ValueError("Use MM:SS or HH:MM:SS for timestamps")
            seconds = float(match.group(1))
    if seconds < 0 or seconds > 86400:
        raise ValueError("Timestamp must be between 0:00 and 24:00:00")
    return round(seconds, 3)


def validate_clip_range(
    start_time: Optional[Any], end_time: Optional[Any]
) -> tuple[Optional[float], Optional[float]]:
    start = parse_timestamp(start_time)
    end = parse_timestamp(end_time)
    if start is None and end is None:
        return None, None
    if start is not None and end is not None and start >= end:
        raise ValueError("Start time must be before end time")
    return start, end


def _normalize_preset(
    preset: Optional[str],
    social_bypass: bool = False,
    audio: bool = False,
) -> Optional[str]:
    # Social bypass is a video container/encoder preset. It must never
    # override an audio download and turn it into an .mp4.
    if social_bypass and not audio:
        return "social_bypass"
    if preset in (None, "", "none"):
        return None
    if preset not in PRESET_CHOICES:
        raise ValueError("Unknown edit preset")
    return str(preset)


def _preset_output_ext(preset: str) -> str:
    return {
        "edit_ready": ".mp4",
        "audio_norm": ".m4a",
        "audio_lossless": ".flac",
        "social_bypass": ".mp4",
    }[preset]


def _preset_ffmpeg_args(preset: str, src: str, dst: str) -> List[str]:
    """Arguments after the ffmpeg executable. Kept pure so it is unit-testable."""
    if preset == "edit_ready":
        opts = [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
        ]
    elif preset == "audio_norm":
        opts = [
            "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:a", "aac", "-b:a", "192k",
        ]
    elif preset == "audio_lossless":
        opts = ["-vn", "-c:a", "flac"]
    elif preset == "social_bypass":
        opts = [
            "-vf", "fps=30", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-map_metadata", "-1",
        ]
    else:
        raise ValueError("Unknown edit preset")
    return ["-y", "-i", src, *opts, dst]


_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_name(text: str) -> str:
    """Strip characters Windows rejects and trim trailing dots/spaces."""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("", str(text or "")).strip()
    return cleaned.strip(" .")


def format_audio_filename(
    template: str,
    metadata: Dict[str, Any],
    ext: str,
    playlist: bool = False,
) -> str:
    """Render one of the supported audio filename presets."""
    metadata = metadata or {}
    chosen = (
        template.strip()
        if isinstance(template, str) and template.strip()
        else AUDIO_FILENAME_TEMPLATES[1]
    )
    title = str(metadata.get("title") or "").strip()
    artist = str(metadata.get("artist") or "").strip()
    album = str(metadata.get("album") or "").strip()
    raw_track = metadata.get("track_number")
    track = None
    if isinstance(raw_track, int) and not isinstance(raw_track, bool) and raw_track > 0:
        track = raw_track
    elif str(raw_track or "").strip().isdigit():
        track = int(str(raw_track).strip())

    name = chosen
    for token, value in (
        ("{track}", f"{track:02d}" if track else ""),
        ("{artist}", artist),
        ("{title}", title),
        ("{album}", album),
    ):
        name = name.replace(token, value)
    name = re.sub(r"\{[^{}]*\}", "", name)
    name = re.sub(r"\s*\(\s*\)", "", name)
    name = re.sub(r"\s*-\s*-\s*", " - ", name)
    name = re.sub(r"^(?:\s*-\s*)+|(?:\s*-\s*)+$", "", name)
    name = sanitize_name(name) or sanitize_name(title) or "Untitled"

    if playlist and track and "{track}" not in chosen:
        name = f"{track:02d} - {name}"

    extension = str(ext or "").strip()
    if extension and not extension.startswith("."):
        extension = "." + extension
    return name + extension


def _ffmpeg_executable() -> str:
    found = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
    if not found:
        raise ValueError("FFmpeg was not found. Reinstall the app or add FFmpeg to PATH.")
    return found


def _postprocess_file(path: str, preset: str) -> str:
    final_path = os.path.splitext(path)[0] + _preset_output_ext(preset)
    temp_path = f"{path}.preset{_preset_output_ext(preset)}"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [_ffmpeg_executable(), *_preset_ffmpeg_args(preset, path, temp_path)],
            capture_output=True,
            text=True,
            timeout=900,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("FFmpeg post-processing timed out") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise ValueError(f"FFmpeg post-processing failed: {detail[-1] if detail else 'unknown error'}")
    if not os.path.isfile(temp_path):
        raise ValueError("FFmpeg did not produce an output file")
    os.replace(temp_path, final_path)
    if os.path.abspath(path) != os.path.abspath(final_path):
        try:
            os.remove(path)
        except OSError:
            pass
    return final_path
