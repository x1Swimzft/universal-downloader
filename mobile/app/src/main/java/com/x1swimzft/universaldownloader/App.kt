package com.x1swimzft.universaldownloader

import android.app.Application
import android.content.Context
import com.x1swimzft.universaldownloader.data.HistoryDb
import com.x1swimzft.universaldownloader.data.Prefs
import com.x1swimzft.universaldownloader.engine.DownloadEngine
import com.x1swimzft.universaldownloader.i18n.LocaleHelper
import com.x1swimzft.universaldownloader.service.Notifications
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class App : Application() {
    private val background = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun attachBaseContext(base: Context) {
        super.attachBaseContext(LocaleHelper.wrap(base))
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        Prefs.init(this)
        HistoryDb.init(this)
        Notifications.ensureChannel(this)
        refreshEngineIfStale()
    }

    /**
     * YouTube breaks old yt-dlp builds constantly (403 on formats). The bundled extractor can be
     * months old, so refresh it in the background; a failed job would otherwise need a manual retry.
     */
    private fun refreshEngineIfStale() {
        background.launch {
            val age = System.currentTimeMillis() - Prefs.engineCheckedAt()
            if (age < ENGINE_CHECK_INTERVAL_MS) return@launch
            if (!DownloadEngine.isOnline(this@App)) return@launch
            runCatching { DownloadEngine.update(this@App) }
            Prefs.setEngineCheckedAt(System.currentTimeMillis())
        }
    }

    companion object {
        private const val ENGINE_CHECK_INTERVAL_MS = 12 * 60 * 60 * 1000L

        lateinit var instance: App
            private set
    }
}
