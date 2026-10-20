import uuid
import asyncio
import os
import re
import shutil
from typing import Dict, Any, Optional

from urllib.parse import quote
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse

from pydantic import BaseModel
from app.models.schemas import (
    InfoRequest,
    DownloadRequest,
    MediaInfo,
    DownloadResponse,
    JobStatus,
    DownloadFormat,
)
from app.services.extractor import extract_info, download_media, get_direct_stream_url
from app.services.queue_manager import queue_mgr

router = APIRouter(prefix="/api")

# In-memory job store — replace with Redis for production
_jobs: Dict[str, Any] = {}
queue_mgr.external_task_store = _jobs

TMP_DIR = os.environ.get("TMP_DIR", os.path.join(os.path.dirname(__file__), "../../tmp"))


class QueueAddRequest(BaseModel):
    urls: Optional[list[str]] = None
    url: Optional[str] = None
    format: DownloadFormat = DownloadFormat.mp4
    quality: str = "720"


class QuickFetchRequest(BaseModel):
    url: str
    format: DownloadFormat = DownloadFormat.mp4
    quality: str = "1080"
    save_to_dir: Optional[str] = r"C:\Users\Dataria\Downloads\UniversalDownloader"


def _strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


@router.post("/info", response_model=MediaInfo)
async def get_info(body: InfoRequest):
    """Extract metadata (title, thumbnail, available formats) without downloading."""
    try:
        info = await extract_info(body.url)
        return info
    except Exception as e:
        clean_err = _strip_ansi(str(e))
        raise HTTPException(status_code=400, detail=clean_err)


def _safe_filename(title: str, ext: str) -> str:
    """Sanitize title for OS-safe filename and preserve Unicode characters."""
    safe = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    if not safe:
        safe = "download"
    return f"{safe}.{ext}"


@router.post("/download", response_model=DownloadResponse)
async def start_download(body: DownloadRequest, background_tasks: BackgroundTasks):
    """Queue a download job. Returns job_id for polling."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "progress": 0.0,
        "filename": None,
        "format": body.format.value,
        "title": body.title,
        "error": None,
    }

    background_tasks.add_task(
        _run_download,
        job_id,
        body.url,
        body.format.value,
        body.quality,
        body.title,
        body.save_to_dir,
    )
    return DownloadResponse(job_id=job_id, status="pending")


@router.get("/progress/{job_id}", response_model=JobStatus)
async def get_progress(job_id: str):
    """Poll job status and progress percentage."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(job_id=job_id, **job)


@router.get("/file/{job_id}")
async def download_file(job_id: str):
    """Stream the finished file to the client with music/video title."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=202, detail="Not ready yet")
    if not job["filename"] or not os.path.exists(job["filename"]):
        raise HTTPException(status_code=404, detail="File not found")

    ext = job.get("format", "mp4")
    title = job.get("title") or "download"
    download_filename = _safe_filename(title, ext)

    return FileResponse(
        job["filename"],
        media_type="application/octet-stream",
        filename=download_filename,
    )


@router.get("/stream")
async def stream_media(url: str, quality: str = "720"):
    stream_info = await get_direct_stream_url(url, quality)
    if not stream_info:
        raise HTTPException(
            status_code=400,
            detail="Direct stream unavailable for this resolution (requires FFmpeg merge)."
        )

    safe_title = _safe_filename(stream_info["title"], "mp4")
    encoded_filename = quote(safe_title)

    client = httpx.AsyncClient(
        headers=stream_info.get("http_headers", {}),
        timeout=60.0,
        follow_redirects=True,
    )
    req = client.build_request("GET", stream_info["url"])
    resp = await client.send(req, stream=True)

    headers = {
        "Content-Disposition": f"attachment; filename=\"{safe_title}\"; filename*=utf-8''{encoded_filename}"
    }
    if stream_info.get("filesize"):
        headers["Content-Length"] = str(stream_info["filesize"])

    async def stream_generator():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_generator(),
        media_type="video/mp4",
        headers=headers,
    )


@router.post("/queue/add")
async def add_to_queue(body: QueueAddRequest):
    urls: list[str] = []
    if body.urls:
        urls.extend(body.urls)
    if body.url and body.url not in urls:
        urls.append(body.url)

    if not urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    fmt = body.format.value if hasattr(body.format, "value") else str(body.format)
    job_ids = []
    for raw_url in urls:
        clean = raw_url.strip()
        if clean:
            jid = queue_mgr.add(clean, fmt=fmt, quality=body.quality)
            job_ids.append(jid)

    return {"job_ids": job_ids, "count": len(job_ids)}


@router.get("/queue/stream")
async def get_queue_stream():
    return StreamingResponse(
        queue_mgr.subscribe(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/rio/quick-fetch")
async def rio_quick_fetch(body: QuickFetchRequest):
    """Fast headless download for RIO workflow saving directly to local folder."""
    save_dir = body.save_to_dir or r"C:\Users\Dataria\Downloads\UniversalDownloader"
    os.makedirs(save_dir, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)

    job_id = str(uuid.uuid4())
    fmt = body.format.value if hasattr(body.format, "value") else str(body.format)
    temp_store = {job_id: {"progress": 0.0}}

    try:
        tmp_filepath, extracted_title = await download_media(
            body.url, fmt, body.quality, TMP_DIR, temp_store, job_id
        )
        safe_name = _safe_filename(extracted_title, fmt)
        dest_path = os.path.join(save_dir, safe_name)

        base_name, ext = os.path.splitext(safe_name)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(save_dir, f"{base_name} ({counter}){ext}")
            counter += 1

        shutil.move(tmp_filepath, dest_path)
        return {
            "status": "completed",
            "title": extracted_title,
            "format": fmt,
            "quality": body.quality,
            "local_path": dest_path,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_download(
    job_id: str,
    url: str,
    fmt: str,
    quality: str,
    title: Optional[str] = None,
    save_to_dir: Optional[str] = None,
):
    """Background task: download, optionally save to custom dir, then update job store."""
    _jobs[job_id]["status"] = "processing"
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        filepath, extracted_title = await download_media(url, fmt, quality, TMP_DIR, _jobs, job_id)
        final_title = title or extracted_title or "download"

        if save_to_dir:
            os.makedirs(save_to_dir, exist_ok=True)
            safe_name = _safe_filename(final_title, fmt)
            dest_path = os.path.join(save_to_dir, safe_name)
            base_name, ext = os.path.splitext(safe_name)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(save_to_dir, f"{base_name} ({counter}){ext}")
                counter += 1
            shutil.move(filepath, dest_path)
            filepath = dest_path

        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["progress"] = 100.0
        _jobs[job_id]["filename"] = filepath
        if not _jobs[job_id].get("title"):
            _jobs[job_id]["title"] = final_title
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = str(e)
