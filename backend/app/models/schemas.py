from pydantic import BaseModel, HttpUrl
from typing import Optional, List, Union, Literal
from enum import Enum


class MediaFormat(str, Enum):
    mp3 = "mp3"
    mp4 = "mp4"
    m4a = "m4a"
    opus = "opus"
    images = "images"


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


class ClipOptions(BaseModel):
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    preset: Optional[Literal["edit_ready", "audio_norm", "audio_lossless"]] = None
    social_bypass: bool = False


class DownloadRequest(ClipOptions):
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


class PreviewEntry(BaseModel):
    url: str
    title: str = "Untitled"
    duration: Optional[Union[int, float]] = None
    thumbnail: Optional[str] = None
    platform: Optional[str] = None
    media_type: str = "video"
    artist: Optional[str] = None
    album: Optional[str] = None
    track_number: Optional[int] = None
    search_query: Optional[str] = None


class MediaInfo(BaseModel):
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[Union[int, float]] = None
    uploader: Optional[str] = None
    platform: Optional[str] = None
    formats: List[FormatOption] = []
    images: List[str] = []
    entries: List[PreviewEntry] = []
    media_type: str = "video"  # video | image | carousel | playlist
    artist: Optional[str] = None
    album: Optional[str] = None
    track_number: Optional[int] = None
    search_query: Optional[str] = None


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
