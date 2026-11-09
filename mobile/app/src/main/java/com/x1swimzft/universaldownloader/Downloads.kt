package com.x1swimzft.universaldownloader

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.x1swimzft.universaldownloader.core.DownloadError
import com.x1swimzft.universaldownloader.core.Job
import com.x1swimzft.universaldownloader.core.JobStatus
import com.x1swimzft.universaldownloader.engine.DownloadEngine
import com.x1swimzft.universaldownloader.service.DownloadService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/** In-memory queue; the service drains it. Process death drops queued work, which is fine for v1. */
object Downloads {
    private val _jobs = MutableStateFlow<List<Job>>(emptyList())
    val jobs: StateFlow<List<Job>> = _jobs.asStateFlow()

    fun enqueue(context: Context, job: Job) {
        _jobs.update { it + job }
        start(context)
    }

    fun retry(context: Context, id: String) {
        _jobs.update { list ->
            list.map {
                if (it.id == id && it.status.isFinished) it.copy(
                    status = JobStatus.QUEUED,
                    progress = 0,
                    etaSec = null,
                    error = null,
                    fileUri = null,
                    sizeBytes = null,
                    finishedAt = null
                ) else it
            }
        }
        start(context)
    }

    fun cancel(context: Context, id: String) {
        _jobs.update { list ->
            list.map {
                if (it.id == id && !it.status.isFinished) it.copy(
                    status = JobStatus.CANCELED,
                    finishedAt = System.currentTimeMillis()
                ) else it
            }
        }
        DownloadEngine.cancel(id)
    }

    fun cancelAll(context: Context) {
        _jobs.value.filter { !it.status.isFinished }.forEach { job ->
            DownloadEngine.cancel(job.id)
        }
        _jobs.update { list ->
            list.map {
                if (!it.status.isFinished) it.copy(
                    status = JobStatus.CANCELED,
                    finishedAt = System.currentTimeMillis()
                ) else it
            }
        }
    }

    fun remove(id: String) {
        _jobs.update { list -> list.filterNot { it.id == id && it.status.isFinished } }
    }

    fun clearFinished() {
        _jobs.update { list -> list.filterNot { it.status.isFinished } }
    }

    fun get(id: String): Job? = _jobs.value.firstOrNull { it.id == id }

    fun status(id: String): JobStatus? = get(id)?.status

    internal fun hasQueued(): Boolean = _jobs.value.any { it.status == JobStatus.QUEUED }

    internal fun activeCount(): Int = _jobs.value.count { it.status.isActive }

    @Synchronized
    internal fun claimNext(): Job? {
        val next = _jobs.value.firstOrNull { it.status == JobStatus.QUEUED } ?: return null
        val claimed = next.copy(status = JobStatus.DOWNLOADING)
        _jobs.update { list -> list.map { if (it.id == next.id) claimed else it } }
        return claimed
    }

    internal fun progress(id: String, percent: Int, etaSec: Long?) {
        _jobs.update { list ->
            list.map {
                if (it.id == id && it.status.isActive) it.copy(progress = percent, etaSec = etaSec) else it
            }
        }
    }

    internal fun markDone(id: String, fileUri: String, sizeBytes: Long) {
        _jobs.update { list ->
            list.map {
                if (it.id == id) it.copy(
                    status = JobStatus.DONE,
                    progress = 100,
                    etaSec = null,
                    fileUri = fileUri,
                    sizeBytes = sizeBytes,
                    finishedAt = System.currentTimeMillis()
                ) else it
            }
        }
    }

    internal fun markCanceled(id: String) {
        _jobs.update { list ->
            list.map {
                if (it.id == id && !it.status.isFinished) it.copy(
                    status = JobStatus.CANCELED,
                    etaSec = null,
                    finishedAt = System.currentTimeMillis()
                ) else it
            }
        }
    }

    internal fun markFailed(id: String, error: DownloadError) {
        _jobs.update { list ->
            list.map {
                if (it.id == id) it.copy(
                    status = JobStatus.FAILED,
                    error = error.name,
                    etaSec = null,
                    finishedAt = System.currentTimeMillis()
                ) else it
            }
        }
    }

    private fun start(context: Context) {
        if (!hasQueued()) return
        ContextCompat.startForegroundService(
            context,
            Intent(context, DownloadService::class.java)
        )
    }
}
