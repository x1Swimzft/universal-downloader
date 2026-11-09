package com.x1swimzft.universaldownloader.service

import android.app.Service
import android.content.Intent
import android.os.IBinder
import com.x1swimzft.universaldownloader.Downloads
import com.x1swimzft.universaldownloader.core.DownloadError
import com.x1swimzft.universaldownloader.core.Formats
import com.x1swimzft.universaldownloader.core.Job
import com.x1swimzft.universaldownloader.core.JobStatus
import com.x1swimzft.universaldownloader.core.UrlTools
import com.x1swimzft.universaldownloader.data.HistoryDb
import com.x1swimzft.universaldownloader.data.Prefs
import com.x1swimzft.universaldownloader.engine.DownloadEngine
import com.x1swimzft.universaldownloader.engine.EngineCanceled
import com.x1swimzft.universaldownloader.engine.EngineException
import com.x1swimzft.universaldownloader.media.MediaStoreSaver
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var scheduler: kotlinx.coroutines.Job? = null
    private var notifier: kotlinx.coroutines.Job? = null

    override fun attachBaseContext(newBase: android.content.Context) {
        super.attachBaseContext(com.x1swimzft.universaldownloader.i18n.LocaleHelper.wrap(newBase))
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Notifications.ensureChannel(this)
        if (intent?.action == ACTION_CANCEL_ALL) Downloads.cancelAll(this)

        startForeground(Notifications.ID, Notifications.build(this, Downloads.jobs.value))

        if (notifier == null) {
            notifier = scope.launch {
                Downloads.jobs.collect { jobs ->
                    if (jobs.any { it.status.isActive }) Notifications.update(this@DownloadService, jobs)
                }
            }
        }
        ensureScheduler()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun ensureScheduler() {
        if (scheduler?.isActive == true) return
        scheduler = scope.launch {
            while (isActive) {
                val limit = Prefs.maxConcurrent()
                if (Downloads.activeCount() < limit) {
                    val next = Downloads.claimNext()
                    if (next != null) {
                        launch { runJob(next) }
                        continue
                    }
                }
                if (Downloads.activeCount() == 0 && !Downloads.hasQueued()) break
                delay(300)
            }
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private suspend fun runJob(job: Job) {
        var refreshedEngine = false
        while (true) {
            var temp: java.io.File? = null
            try {
                temp = DownloadEngine.download(this, job) { percent, eta ->
                    Downloads.progress(job.id, percent, eta)
                }
                val displayName = UrlTools.displayName(job.title, job.format)
                val uri = MediaStoreSaver.save(this, temp, displayName, Formats.mimeType(job.format))
                val size = temp.length()
                Downloads.markDone(job.id, uri.toString(), size)
                Downloads.get(job.id)?.let { HistoryDb.add(this, it) }
                Notifications.done(this, job.title, uri.toString(), Formats.mimeType(job.format))
                return
            } catch (e: EngineCanceled) {
                Downloads.markCanceled(job.id)
                return
            } catch (e: Exception) {
                if (Downloads.status(job.id) == JobStatus.CANCELED) {
                    Downloads.markCanceled(job.id)
                    return
                }
                // A stale extractor is the usual cause of 403/extractor errors; self-heal once.
                if (!refreshedEngine && DownloadEngine.isOnline(this) &&
                    DownloadEngine.isRetryableEngineFailure(e)
                ) {
                    refreshedEngine = true
                    val updated = runCatching { DownloadEngine.update(this) }.isSuccess
                    if (updated) {
                        Downloads.progress(job.id, 0, null)
                        continue
                    }
                }
                val error = (e as? EngineException)?.error ?: DownloadError.fromMessage(e.message)
                Downloads.markFailed(job.id, error)
                Downloads.get(job.id)?.let { HistoryDb.add(this, it) }
                Notifications.failed(this, job.title)
                return
            } finally {
                temp?.parentFile?.deleteRecursively()
            }
        }
    }

    companion object {
        const val ACTION_CANCEL_ALL = "com.x1swimzft.universaldownloader.action.CANCEL_ALL"
    }
}
