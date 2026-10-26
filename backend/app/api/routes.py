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
    ClipOptions,
)
from app.services.extractor import (
    extract_info,
    download_media,
    get_direct_stream_url,
    validate_url_not_private,
    validate_clip_range,
    set_cookie_preferences,
    get_cookie_preferences,
)
from app.services.extractor_update import get_extractor_status, update_extractor
from app.services.queue_manager import (
    queue_mgr,
    is_allowed_path,
    safe_filename,
    is_safe_save_dir,
)

router = APIRouter(prefix="/api")

# In-memory job store — replace with Redis for production
_jobs: Dict[str, Any] = {}
queue_mgr.external_task_store = _jobs

TMP_DIR = os.environ.get("TMP_DIR", os.path.join(os.path.dirname(__file__), "../../tmp"))


class QueueAddRequest(ClipOptions):
    urls: Optional[list[str]] = None
    url: Optional[str] = None
    format: DownloadFormat = DownloadFormat.mp4
    quality: str = "1080"
    title: Optional[str] = None


class QuickFetchRequest(ClipOptions):
    url: str
    format: DownloadFormat = DownloadFormat.mp4
    quality: str = "1080"
    save_to_dir: Optional[str] = None


class SettingsSyncRequest(BaseModel):
    max_concurrent: Optional[int] = None
    save_folder: Optional[str] = None
    cookies_from_browser: Optional[str] = None
    cookies_file: Optional[str] = None


class OpenFolderRequest(BaseModel):
    path: Optional[str] = None


def _strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def _validate_save_dir(requested_dir: Optional[str]) -> str:
    if not requested_dir:
        return queue_mgr.save_dir
    ok, err = is_safe_save_dir(requested_dir)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    real = os.path.realpath(requested_dir)
    if not is_allowed_path(real, queue_mgr.save_dir):
        raise HTTPException(
            status_code=403,
            detail="Path is outside the configured save folder in Settings.",
        )
    return real


@router.post("/info", response_model=MediaInfo)
async def get_info(body: InfoRequest):
    """Extract metadata (title, thumbnail, available formats) without downloading."""
    if not validate_url_not_private(body.url):
        raise HTTPException(status_code=400, detail="Invalid or private URL not allowed")
    try:
        info = await extract_info(body.url)
        return info
    except Exception as e:
        clean_err = _strip_ansi(str(e))
        raise HTTPException(status_code=400, detail=clean_err)


def _safe_filename(title: str, ext: str) -> str:
    return safe_filename(title, ext)


@router.post("/download", response_model=DownloadResponse)
async def start_download(body: DownloadRequest, background_tasks: BackgroundTasks):
    """Queue a download job. Returns job_id for polling."""
    if not validate_url_not_private(body.url):
        raise HTTPException(status_code=400, detail="Invalid or private URL not allowed")
    try:
        validate_clip_range(body.start_time, body.end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    validated_dir = _validate_save_dir(body.save_to_dir) if body.save_to_dir else None
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
        validated_dir,
        body.start_time,
        body.end_time,
        body.preset,
        body.social_bypass,
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

    ext = os.path.splitext(job["filename"])[1].lstrip(".") or job.get("format", "mp4")
    title = job.get("title") or "download"
    download_filename = _safe_filename(title, ext)

    return FileResponse(
        job["filename"],
        media_type="application/octet-stream",
        filename=download_filename,
    )


@router.get("/stream")
async def stream_media(url: str, quality: str = "720"):
    if not validate_url_not_private(url):
        raise HTTPException(
            status_code=400,
            detail="Invalid or private URL not allowed"
        )
    stream_info = await get_direct_stream_url(url, quality)
    if not stream_info:
        raise HTTPException(
            status_code=400,
            detail="Direct stream unavailable for this resolution (requires FFmpeg merge)."
        )

    direct_url = stream_info.get("url", "")
    if not validate_url_not_private(direct_url):
        raise HTTPException(
            status_code=400,
            detail="Direct stream target points to invalid or private address."
        )

    safe_title = _safe_filename(stream_info["title"], "mp4")
    encoded_filename = quote(safe_title)

    async def check_redirect(response: httpx.Response):
        if response.is_redirect:
            location = response.headers.get("location")
            if location:
                redirect_url = str(response.url.join(location))
                if not validate_url_not_private(redirect_url):
                    raise HTTPException(
                        status_code=400,
                        detail="Redirect to private or loopback IP forbidden"
                    )

    client = httpx.AsyncClient(
        headers=stream_info.get("http_headers", {}),
        timeout=60.0,
        follow_redirects=True,
        event_hooks={"response": [check_redirect]},
    )
    try:
        req = client.build_request("GET", direct_url)
        resp = await client.send(req, stream=True)
    except HTTPException:
        await client.aclose()
        raise
    except Exception as e:
        await client.aclose()
        raise HTTPException(status_code=400, detail=str(e))

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

    try:
        validate_clip_range(body.start_time, body.end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    fmt = body.format.value if hasattr(body.format, "value") else str(body.format)
    job_ids = []
    for raw_url in urls:
        clean = raw_url.strip()
        if clean:
            if not validate_url_not_private(clean):
                raise HTTPException(status_code=400, detail=f"Invalid or private URL not allowed: {clean}")
            title = body.title if len(urls) == 1 else None
            jid = queue_mgr.add(
                clean,
                fmt=fmt,
                quality=body.quality,
                title=title,
                start_time=body.start_time,
                end_time=body.end_time,
                preset=body.preset,
                social_bypass=body.social_bypass,
            )
            job_ids.append(jid)

    return {"job_ids": job_ids, "count": len(job_ids)}


@router.delete("/queue/{job_id}")
async def delete_queue_item(job_id: str):
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id")
    existed = await queue_mgr.cancel(job_id)
    return {"cancelled": existed, "job_id": job_id}


@router.get("/queue/stream")
async def get_queue_stream():
    return StreamingResponse(
        queue_mgr.subscribe(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/settings")
async def get_backend_settings():
    cookies = get_cookie_preferences()
    return {
        "max_concurrent": queue_mgr.max_concurrent,
        "save_folder": queue_mgr.save_dir,
        "cookies_from_browser": cookies["cookies_from_browser"],
        "cookies_file": cookies["cookies_file"],
    }


@router.post("/settings")
async def update_backend_settings(body: SettingsSyncRequest):
    if body.max_concurrent is not None:
        if body.max_concurrent not in (1, 2, 3, 5):
            raise HTTPException(status_code=400, detail="max_concurrent must be 1, 2, 3, or 5")
        queue_mgr.set_max_concurrent(body.max_concurrent)
    if body.save_folder:
        ok, err = is_safe_save_dir(body.save_folder)
        if not ok:
            raise HTTPException(status_code=400, detail=err)
        queue_mgr.set_save_dir(body.save_folder)
    try:
        set_cookie_preferences(
            cookies_from_browser=body.cookies_from_browser,
            cookies_file=body.cookies_file,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cookies = get_cookie_preferences()
    return {
        "max_concurrent": queue_mgr.max_concurrent,
        "save_folder": queue_mgr.save_dir,
        "cookies_from_browser": cookies["cookies_from_browser"],
        "cookies_file": cookies["cookies_file"],
    }


@router.get("/system/extractor")
async def extractor_status():
    return get_extractor_status()


@router.post("/system/update-extractor")
async def update_extractor_endpoint():
    try:
        return await update_extractor()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach PyPI: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extractor update failed: {e}")


@router.post("/open-folder")
async def open_folder(body: OpenFolderRequest):
    target = body.path or queue_mgr.save_dir
    real_target = os.path.realpath(target)
    if not is_allowed_path(real_target, queue_mgr.save_dir):
        raise HTTPException(
            status_code=403,
            detail="Path is outside the configured save folder in Settings.",
        )
    if not os.path.isdir(real_target):
        raise HTTPException(
            status_code=400,
            detail="Target path is not a directory.",
        )

    os.makedirs(real_target, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(real_target)
    return {"opened": real_target}


@router.post("/rio/quick-fetch")
async def rio_quick_fetch(body: QuickFetchRequest):
    """Fast headless download for RIO workflow saving directly to local folder."""
    if not validate_url_not_private(body.url):
        raise HTTPException(status_code=400, detail="Invalid or private URL not allowed")
    save_dir = _validate_save_dir(body.save_to_dir)
    os.makedirs(save_dir, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)

    try:
        validate_clip_range(body.start_time, body.end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_id = str(uuid.uuid4())
    fmt = body.format.value if hasattr(body.format, "value") else str(body.format)
    temp_store = {job_id: {"progress": 0.0}}

    try:
        tmp_filepath, extracted_title = await download_media(
            body.url,
            fmt,
            body.quality,
            TMP_DIR,
            temp_store,
            job_id,
            start_time=body.start_time,
            end_time=body.end_time,
            preset=body.preset,
            social_bypass=body.social_bypass,
        )
        output_ext = os.path.splitext(tmp_filepath)[1].lstrip(".") or fmt
        safe_name = _safe_filename(extracted_title, output_ext)
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_download(
    job_id: str,
    url: str,
    fmt: str,
    quality: str,
    title: Optional[str] = None,
    save_to_dir: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    preset: Optional[str] = None,
    social_bypass: bool = False,
):
    """Background task: download, optionally save to custom dir, then update job store."""
    _jobs[job_id]["status"] = "processing"
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        filepath, extracted_title = await download_media(
            url,
            fmt,
            quality,
            TMP_DIR,
            _jobs,
            job_id,
            start_time=start_time,
            end_time=end_time,
            preset=preset,
            social_bypass=social_bypass,
        )
        final_title = title or extracted_title or "download"

        target_dir = save_to_dir or queue_mgr.save_dir
        if target_dir and is_allowed_path(target_dir, queue_mgr.save_dir):
            os.makedirs(target_dir, exist_ok=True)
            output_ext = os.path.splitext(filepath)[1].lstrip(".") or fmt
            safe_name = _safe_filename(final_title, output_ext)
            dest_path = os.path.join(target_dir, safe_name)
            base_name, ext = os.path.splitext(safe_name)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(target_dir, f"{base_name} ({counter}){ext}")
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
