package com.x1swimzft.universaldownloader.core

import java.net.URL
import java.util.Locale

/**
 * Spotify has no yt-dlp extractor (DRM). Desktop parity: read track metadata from the embed
 * page, then download the top YouTube match via `ytsearch1:`.
 */
data class SpotifyTrack(
    val title: String,
    val artist: String? = null,
    val durationSec: Int? = null,
    val thumbnail: String? = null,
    val playable: Boolean = true
)

object Spotify {
    private val TRACK_PATH = Regex("""^(?:/intl-[a-z]{2,5})?/track/([A-Za-z0-9]{10,})/?$""")
    private val INTL_PREFIX = Regex("""^/intl-[a-z]{2,5}""")
    private val COLLECTION_PREFIXES =
        listOf("/album/", "/playlist/", "/artist/", "/show/", "/episode/")

    fun isSpotify(url: String): Boolean = runCatching {
        val host = URL(url).host.lowercase(Locale.ROOT).removePrefix("www.")
        host == "open.spotify.com" || host == "spotify.com" || host.endsWith(".spotify.com")
    }.getOrDefault(false)

    fun trackId(url: String): String? = runCatching {
        val parsed = URL(url)
        val host = parsed.host.lowercase(Locale.ROOT).removePrefix("www.")
        if (host != "open.spotify.com") return@runCatching null
        TRACK_PATH.find(parsed.path.orEmpty())?.groupValues?.get(1)
    }.getOrNull()

    fun isCollection(url: String): Boolean = runCatching {
        val parsed = URL(url)
        val host = parsed.host.lowercase(Locale.ROOT).removePrefix("www.")
        val path = parsed.path.orEmpty().replaceFirst(INTL_PREFIX, "")
        host == "open.spotify.com" && COLLECTION_PREFIXES.any { path.startsWith(it) }
    }.getOrDefault(false)

    fun searchQuery(title: String, artist: String?): String {
        val cleanTitle = title.trim()
        val cleanArtist = artist?.trim().orEmpty()
        val base = if (cleanArtist.isNotBlank()) "$cleanArtist - $cleanTitle" else cleanTitle
        return "$base official audio"
    }
}
