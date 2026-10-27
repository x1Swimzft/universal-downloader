"""Diagnostics endpoint: a copyable snapshot with secrets and paths redacted."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import diagnostics

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/diagnostics")
async def get_diagnostics(app_version: str = Query("unknown")) -> dict:
    return diagnostics.collect(app_version)
