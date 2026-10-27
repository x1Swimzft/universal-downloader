"""Platform health check: probe one public sample per platform, never download."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from fastapi import APIRouter

from app.services import extractor

router = APIRouter(prefix="/api/health", tags=["health"])

# Reference assets from the Phase 1 work order. Probe only: extract_info never
# downloads media, it only resolves metadata.
SAMPLES: List[Dict[str, str]] = [
    {
        "platform": "tiktok",
        "url": "https://www.tiktok.com/@lucasvisual/photo/7508048429776407830",
    },
    {
        "platform": "instagram",
        "url": "https://www.instagram.com/p/DJFnRpMuuAm/",
    },
    {
        "platform": "youtube",
        "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    },
]

PROBE_TIMEOUT = 30.0
LAST_RESULT: List[Dict[str, Any]] = []


async def _probe(platform: str, url: str) -> Dict[str, Any]:
    started = time.perf_counter()
    result: Dict[str, Any] = {"platform": platform, "url": url, "ok": False}
    try:
        info = await asyncio.wait_for(extractor.extract_info(url), timeout=PROBE_TIMEOUT)
        result["ok"] = True
        result["media_type"] = info.media_type
        result["title"] = info.title
    except asyncio.TimeoutError:
        result["error_code"] = "NETWORK_TRANSIENT"
        result["detail"] = f"Probe timed out after {PROBE_TIMEOUT:.0f}s"
    except Exception as exc:  # classification stays in one place
        result["error_code"] = extractor.classify_error(str(exc), url)
        result["detail"] = extractor.diagnostic_message(str(exc), url)[1]
    result["duration_ms"] = round((time.perf_counter() - started) * 1000)
    return result


@router.get("/platforms")
async def platform_health() -> Dict[str, Any]:
    """Run every sample probe in parallel; one failure never hides the others."""
    global LAST_RESULT
    results = await asyncio.gather(
        *(_probe(sample["platform"], sample["url"]) for sample in SAMPLES)
    )
    LAST_RESULT = list(results)
    return {"results": LAST_RESULT}
