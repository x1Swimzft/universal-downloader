"""Redacted diagnostics snapshot. Nothing is ever sent anywhere automatically."""

from __future__ import annotations

import os
import platform
import re
import sys
from typing import Any, Dict

# Query parameters that authenticate or expire a URL.
_SIGNED_QUERY = re.compile(
    r"([?&](?:token|sig|signature|expires|expire|x-amz-[^=]+|stp|_nc_[^=]+|oh|oe)=)[^&\s\"']+",
    re.IGNORECASE,
)
_SECRET_HEADER = re.compile(
    r"(?i)\b(x-app-token|authorization|cookie)\b\s*[:=]\s*\S+"
)


def redact(value: Any) -> Any:
    """Strip tokens, signed-query values and the Windows username from paths."""
    if not isinstance(value, str):
        return value
    text = _SIGNED_QUERY.sub(r"\1REDACTED", value)
    text = _SECRET_HEADER.sub(r"\1=REDACTED", text)
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, "%USERPROFILE%")
    return text


def collect(app_version: str = "unknown") -> Dict[str, Any]:
    from app.services.extractor_update import get_extractor_status

    try:
        extractor = get_extractor_status()
    except Exception:
        extractor = {"error": "unavailable"}

    from app.api import health_platforms

    last_health = health_platforms.LAST_RESULT or []
    last_error = next(
        (item.get("error_code") for item in last_health if item.get("error_code")),
        None,
    )

    return {
        "app_version": redact(app_version),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "extractor": {key: redact(value) for key, value in extractor.items()},
        "last_error_code": last_error,
        "platform_health": [
            {
                "platform": item.get("platform"),
                "ok": item.get("ok"),
                "error_code": item.get("error_code"),
                "duration_ms": item.get("duration_ms"),
            }
            for item in last_health
        ],
    }
