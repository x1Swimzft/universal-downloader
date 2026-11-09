package com.x1swimzft.universaldownloader.core

import java.util.UUID

enum class MediaFormat(val id: String) {
    MP4("mp4"),
    MP3("mp3"),
    M4A("m4a");

    val isAudio: Boolean get() = this != MP4
}

/** Quality token: "best" | "1080" | "720" ... for video, "320" | "192" | "128" for mp3. */
data class MediaInfo(
    val url: String,
    val title: String,
    val uploader: String?,
    val durationSec: Int?,
    val thumbnail: String?,
    val platform: String,
    val audioOnly: Boolean = false
)

enum class JobStatus {
    QUEUED, DOWNLOADING, PROCESSING, DONE, FAILED, CANCELED;

    val isActive: Boolean get() = this == DOWNLOADING || this == PROCESSING
    val isFinished: Boolean get() = this == DONE || this == FAILED || this == CANCELED
}

data class Job(
    val id: String = UUID.randomUUID().toString(),
    val url: String,
    val title: String,
    val platform: String,
    val thumbnail: String? = null,
    val durationSec: Int? = null,
    val format: MediaFormat,
    val quality: String,
    val status: JobStatus = JobStatus.QUEUED,
    val progress: Int = 0,
    val etaSec: Long? = null,
    val fileUri: String? = null,
    val sizeBytes: Long? = null,
    val error: String? = null,
    val createdAt: Long = System.currentTimeMillis(),
    val finishedAt: Long? = null
)

enum class DownloadError {
    NETWORK, LOGIN, PRIVATE, UNAVAILABLE, PLAYLIST, COOKIES, STORAGE, FORBIDDEN, UNSUPPORTED,
    CANCELED, UNKNOWN;

    companion object {
        fun fromMessage(raw: String?): DownloadError {
            val m = raw?.lowercase().orEmpty()
            return when {
                "cancel" in m -> CANCELED
                "sign in" in m || "login" in m || "log in" in m || "bot" in m -> LOGIN
                "private" in m || "members-only" in m || "members only" in m -> PRIVATE
                "cookie" in m -> COOKIES
                "unsupported url" in m -> UNSUPPORTED
                "403" in m || "forbidden" in m -> FORBIDDEN
                "unavailable" in m || "not available" in m || "removed" in m || "no video formats" in m -> UNAVAILABLE
                "playlist" in m -> PLAYLIST
                "timed out" in m || "timeout" in m || "network" in m || "connection" in m ||
                    "unable to download" in m || "http error" in m || "ssl" in m -> NETWORK
                "no space" in m || "enospc" in m || "permission" in m || "storage" in m -> STORAGE
                else -> UNKNOWN
            }
        }
    }
}
