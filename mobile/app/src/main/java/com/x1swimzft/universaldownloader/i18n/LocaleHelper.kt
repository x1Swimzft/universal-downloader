package com.x1swimzft.universaldownloader.i18n

import android.content.Context
import android.content.res.Configuration
import java.util.Locale

/**
 * Wraps the base context with the language picked in Settings. Deliberately AppCompat-free:
 * createConfigurationContext works on every supported API and survives process restarts.
 */
object LocaleHelper {
    private const val FILE = "settings"
    private const val KEY = "language"

    fun currentTag(context: Context): String =
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).getString(KEY, "system") ?: "system"

    fun wrap(base: Context): Context {
        val tag = currentTag(base)
        if (tag == "system") return base
        val locale = Locale.forLanguageTag(tag)
        Locale.setDefault(locale)
        val config = Configuration(base.resources.configuration)
        config.setLocale(locale)
        return base.createConfigurationContext(config)
    }
}
