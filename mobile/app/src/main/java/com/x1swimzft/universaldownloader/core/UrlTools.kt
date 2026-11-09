package com.x1swimzft.universaldownloader.core

import java.net.URL
import java.util.Locale

object UrlTools {
    private val URL_RE = Regex("""https?://[^\s<>"']+""")

    fun extractUrl(text: String?): String? =
        text?.let { URL_RE.find(it)?.value?.trimEnd('.', ',', ')', ']') }

    fun isValid(url: String): Boolean = runCatching {
        val parsed = URL(url)
        parsed.protocol in listOf("http", "https") && !parsed.host.isNullOrBlank()
    }.getOrDefault(false)

    /** v1 handles one link at a time; a bare channel/playlist link gets a clear message instead of a surprise. */
    fun looksLikePlaylist(url: String): Boolean = runCatching {
        val parsed = URL(url)
        val host = parsed.host.lowercase(Locale.ROOT)
        val path = parsed.path.orEmpty()
        val query = parsed.query.orEmpty()
        when {
            query.contains("list=") && !query.contains("v=") -> true
            path.startsWith("/playlist") -> true
            host.contains("youtube") && Regex("""^/@[^/]+/?$""").matches(path) -> true
            host.contains("youtube") && Regex("""^/(channel|c|user)/[^/]+/?$""").matches(path) -> true
            host.contains("soundcloud") && path.contains("/sets/") -> true
            host.contains("bilibili") && path.contains("/medialist/") -> true
            host.contains("spotify") && (
                path.startsWith("/album/") || path.startsWith("/playlist/") ||
                    path.startsWith("/artist/") || path.startsWith("/show/") ||
                    path.startsWith("/episode/")
                ) -> true
            else -> false
        }
    }.getOrDefault(false)

    fun platformOf(url: String): String = runCatching {
        val host = URL(url).host.lowercase(Locale.ROOT).removePrefix("www.")
        when {
            host.endsWith("youtube.com") || host == "youtu.be" -> "YouTube"
            host.endsWith("tiktok.com") -> "TikTok"
            host.endsWith("instagram.com") -> "Instagram"
            host.endsWith("facebook.com") || host == "fb.watch" -> "Facebook"
            host == "x.com" || host.endsWith("twitter.com") -> "X"
            host.endsWith("twitch.tv") -> "Twitch"
            host.endsWith("kick.com") -> "Kick"
            host.endsWith("bilibili.com") -> "Bilibili"
            host.endsWith("vimeo.com") -> "Vimeo"
            host.endsWith("reddit.com") -> "Reddit"
            host.endsWith("pinterest.com") || host == "pin.it" -> "Pinterest"
            host.endsWith("soundcloud.com") -> "SoundCloud"
            host.endsWith("spotify.com") -> "Spotify"
            host.endsWith("bandcamp.com") -> "Bandcamp"
            host.endsWith("dailymotion.com") || host == "dai.ly" -> "Dailymotion"
            else -> host
        }
    }.getOrDefault("Link")

    fun sanitizeFileName(raw: String): String {
        val cleaned = raw
            .replace(Regex("""[\\/:*?"<>|\u0000-\u001F]"""), " ")
            .replace(Regex("""\s+"""), " ")
            .trim()
            .trimEnd('.')
        val limited = if (cleaned.length > 100) cleaned.take(100).trim() else cleaned
        return limited.ifBlank { "download" }
    }

    fun displayName(title: String, format: MediaFormat): String =
        "${sanitizeFileName(title)}.${format.id}"
}
