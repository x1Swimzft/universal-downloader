from pydantic import BaseModel, HttpUrl
from typing import Optional, List, Union
from enum import Enum


class MediaFormat(str, Enum):
    mp3 = "mp3"
    mp4 = "mp4"
    m4a = "m4a"
    opus = "opus"


DownloadFormat = MediaFormat


class AudioQuality(str, Enum):
    q320 = "320"
    q192 = "192"
    q128 = "128"


class VideoQuality(str, Enum):
    q1080 = "1080"
    q720 = "720"
    q480 = "480"
    q360 = "360"


class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format: MediaFormat
    quality: str  # "320", "192", "1080", "720", etc.
    title: Optional[str] = None
    save_to_dir: Optional[str] = None


class FormatOption(BaseModel):
    format_id: str
    ext: str
    resolution: Optional[str] = None
    filesize: Optional[int] = None
    note: Optional[str] = None


class MediaInfo(BaseModel):
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[Union[int, float]] = None
    uploader: Optional[str] = None
    platform: Optional[str] = None
    formats: List[FormatOption] = []


class DownloadResponse(BaseModel):
    job_id: str
    status: str


class JobStatus(BaseModel):
    job_id: str
    status: str  # "pending" | "processing" | "done" | "error"
    progress: float = 0.0
    filename: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None
