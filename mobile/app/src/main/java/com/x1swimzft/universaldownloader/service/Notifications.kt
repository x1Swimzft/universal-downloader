package com.x1swimzft.universaldownloader.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.x1swimzft.universaldownloader.MainActivity
import com.x1swimzft.universaldownloader.R
import com.x1swimzft.universaldownloader.core.Job

object Notifications {
    const val CHANNEL = "downloads"
    const val ID = 1001
    private const val RESULT_ID = 1002
    private var lastProgressKey = ""

    fun ensureChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL,
                    context.getString(R.string.notif_channel_name),
                    NotificationManager.IMPORTANCE_LOW
                ).apply {
                    description = context.getString(R.string.notif_channel_desc)
                    setShowBadge(false)
                }
            )
        }
    }

    fun build(context: Context, jobs: List<Job>): Notification {
        val active = jobs.filter { it.status.isActive }
        val percent = active.maxOfOrNull { it.progress } ?: 0
        val title = if (active.isEmpty()) context.getString(R.string.app_name)
        else context.getString(R.string.notif_progress_title, active.size)
        val text = active.firstOrNull()
            ?.let { context.getString(R.string.notif_progress_text, percent, it.title) }
            .orEmpty()
        val builder = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(active.isNotEmpty())
            .setOnlyAlertOnce(true)
            .setContentIntent(openApp(context))
            .addAction(0, context.getString(R.string.notif_cancel_all), cancelAll(context))
        if (active.isNotEmpty()) {
            builder.setProgress(100, percent, active.any { it.progress == 0 })
        }
        return builder.build()
    }

    fun update(context: Context, jobs: List<Job>) {
        val active = jobs.filter { it.status.isActive }
        val percent = active.maxOfOrNull { it.progress } ?: 0
        val key = "${active.size}:$percent:${active.firstOrNull()?.title}"
        if (key == lastProgressKey) return
        lastProgressKey = key
        post(context, ID, build(context, jobs))
    }

    fun done(context: Context, title: String, fileUri: String, mime: String) {
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(context.getString(R.string.notif_done_title))
            .setContentText(title)
            .setAutoCancel(true)
            .setContentIntent(openFile(context, fileUri, mime) ?: openApp(context))
            .build()
        post(context, RESULT_ID, notification)
    }

    fun failed(context: Context, title: String) {
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(context.getString(R.string.notif_failed_title))
            .setContentText(title)
            .setAutoCancel(true)
            .setContentIntent(openApp(context))
            .build()
        post(context, RESULT_ID, notification)
    }

    private fun post(context: Context, id: Int, notification: Notification) {
        val manager = NotificationManagerCompat.from(context)
        if (!manager.areNotificationsEnabled()) return
        runCatching { manager.notify(id, notification) }
    }

    private fun openFile(context: Context, fileUri: String, mime: String): PendingIntent? {
        val view = Intent(Intent.ACTION_VIEW)
            .setDataAndType(android.net.Uri.parse(fileUri), mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return PendingIntent.getActivity(
            context,
            2,
            view,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
    }

    private fun openApp(context: Context): PendingIntent = PendingIntent.getActivity(
        context,
        0,
        Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
    )

    private fun cancelAll(context: Context): PendingIntent = PendingIntent.getService(
        context,
        1,
        Intent(context, DownloadService::class.java).setAction(DownloadService.ACTION_CANCEL_ALL),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
    )
}
