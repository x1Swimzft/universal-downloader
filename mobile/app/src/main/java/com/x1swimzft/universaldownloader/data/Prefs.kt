package com.x1swimzft.universaldownloader.data

import android.content.Context
import com.x1swimzft.universaldownloader.core.MediaFormat

/** Small settings surface; no DataStore/Room for six values. */
object Prefs {
    private const val FILE = "settings"
    private lateinit var sp: android.content.SharedPreferences

    fun init(context: Context) {
        if (::sp.isInitialized) return
        sp = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    }

    fun language(): String = sp.getString("language", "system") ?: "system"
    fun setLanguage(tag: String) = sp.edit().putString("language", tag).apply()

    fun defaultFormat(): MediaFormat =
        runCatching { MediaFormat.valueOf(sp.getString("format", MediaFormat.MP4.name)!!) }
            .getOrDefault(MediaFormat.MP4)

    fun setDefaultFormat(format: MediaFormat) = sp.edit().putString("format", format.name).apply()

    fun videoQuality(): String = sp.getString("video_quality", "1080") ?: "1080"
    fun setVideoQuality(q: String) = sp.edit().putString("video_quality", q).apply()

    fun audioQuality(): String = sp.getString("audio_quality", "320") ?: "320"
    fun setAudioQuality(q: String) = sp.edit().putString("audio_quality", q).apply()

    fun maxConcurrent(): Int = (sp.getInt("concurrent", 1)).coerceIn(1, 3)
    fun setMaxConcurrent(n: Int) = sp.edit().putInt("concurrent", n.coerceIn(1, 3)).apply()

    fun clipboardOnOpen(): Boolean = sp.getBoolean("clipboard", true)
    fun setClipboardOnOpen(on: Boolean) = sp.edit().putBoolean("clipboard", on).apply()

    fun cookiesPath(): String? = sp.getString("cookies_path", null)
    fun setCookiesPath(path: String?) = sp.edit().putString("cookies_path", path).apply()

    fun engineCheckedAt(): Long = sp.getLong("engine_checked_at", 0L)
    fun setEngineCheckedAt(at: Long) = sp.edit().putLong("engine_checked_at", at).apply()
}
