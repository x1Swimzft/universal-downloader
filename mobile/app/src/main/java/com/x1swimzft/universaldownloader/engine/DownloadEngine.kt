package com.x1swimzft.universaldownloader.engine

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.Log
import com.x1swimzft.universaldownloader.core.DownloadError
import com.x1swimzft.universaldownloader.core.Formats
import com.x1swimzft.universaldownloader.core.Job
import com.x1swimzft.universaldownloader.core.MediaInfo
import com.x1swimzft.universaldownloader.core.Spotify
import com.x1swimzft.universaldownloader.core.SpotifyTrack
import com.x1swimzft.universaldownloader.core.UrlTools
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class EngineException(val error: DownloadError, override val message: String) : Exception(message)

class EngineCanceled : Exception("canceled")

object DownloadEngine {
    @Volatile
    private var ready = false

    fun init(context: Context) {
        if (ready) return
        synchronized(this) {
            if (ready) return
            val app = context.applicationContext
            YoutubeDL.getInstance().init(app)
            FFmpeg.getInstance().init(app)
            ready = true
        }
    }

    suspend fun analyze(context: Context, url: String): MediaInfo = withContext(Dispatchers.IO) {
        if (!UrlTools.isValid(url)) throw EngineException(DownloadError.UNKNOWN, "invalid url")
        if (Spotify.isSpotify(url)) {
            if (Spotify.isCollection(url)) throw EngineException(DownloadError.PLAYLIST, "spotify collection")
            return@withContext analyzeSpotify(url)
        }
        if (UrlTools.looksLikePlaylist(url)) throw EngineException(DownloadError.PLAYLIST, "playlist url")
        init(context)
        val request = YoutubeDLRequest(url).apply {
            addOption("--no-playlist")
            addOption("--no-warnings")
            cookiesFile(context)?.let { addOption("--cookies", it.absolutePath) }
        }
        try {
            val info = YoutubeDL.getInstance().getInfo(request)
            MediaInfo(
                url = url,
                title = (info.title ?: info.fulltitle ?: url).trim(),
                uploader = info.uploader,
                durationSec = info.duration.takeIf { it > 0 },
                thumbnail = info.thumbnail,
                platform = UrlTools.platformOf(url)
            )
        } catch (e: Exception) {
            Log.e("DownloadEngine", "analyze failed for $url: ${e.message}", e)
            throw EngineException(DownloadError.fromMessage(e.message), e.message ?: "analyze failed")
        }
    }

    /**
     * Spotify tracks are DRM-protected and have no yt-dlp extractor. Read the public embed
     * metadata, then hand yt-dlp the equivalent `ytsearch1:` query (same bridge the desktop app uses).
     */
    private fun analyzeSpotify(url: String): MediaInfo {
        val id = Spotify.trackId(url)
            ?: throw EngineException(DownloadError.UNSUPPORTED, "not a spotify track url")
        val html = runCatching { httpGet("https://open.spotify.com/embed/track/$id") }.getOrNull()
        val parsed = html?.let { parseSpotifyEmbed(it) }
        val fallback = if (parsed == null) fetchSpotifyOEmbed(url) else null
        val track = parsed ?: fallback
            ?: throw EngineException(DownloadError.UNAVAILABLE, "spotify metadata unavailable")
        if (!track.playable) throw EngineException(DownloadError.UNAVAILABLE, "spotify track unavailable")
        val thumbnail = track.thumbnail ?: html?.let { COVER_RE.find(it)?.value }
        return MediaInfo(
            url = "ytsearch1:${Spotify.searchQuery(track.title, track.artist)}",
            title = track.title,
            uploader = track.artist,
            durationSec = track.durationSec,
            thumbnail = thumbnail,
            platform = "Spotify",
            audioOnly = true
        )
    }

    private fun parseSpotifyEmbed(html: String): SpotifyTrack? = runCatching {
        val raw = NEXT_DATA_RE.find(html)?.groupValues?.get(1) ?: return@runCatching null
        val entity = JSONObject(raw)
            .optJSONObject("props")?.optJSONObject("pageProps")
            ?.optJSONObject("state")?.optJSONObject("data")
            ?.optJSONObject("entity") ?: return@runCatching null
        if (entity.optString("type") != "track") return@runCatching null
        val title = entity.optString("name").ifBlank { entity.optString("title") }
        if (title.isBlank()) return@runCatching null
        val artist = entity.optJSONArray("artists")
            ?.optJSONObject(0)?.optString("name")?.ifBlank { null }
        SpotifyTrack(
            title = title,
            artist = artist,
            durationSec = (entity.optInt("duration", 0) / 1000).takeIf { it > 0 },
            thumbnail = COVER_RE.find(html)?.value,
            playable = entity.optBoolean("isPlayable", true)
        )
    }.getOrNull()

    private fun fetchSpotifyOEmbed(url: String): SpotifyTrack? = runCatching {
        val encoded = URLEncoder.encode(url, "UTF-8")
        val json = JSONObject(httpGet("https://open.spotify.com/oembed?url=$encoded"))
        val title = json.optString("title")
        if (title.isBlank()) return@runCatching null
        SpotifyTrack(title = title, thumbnail = json.optString("thumbnail_url").ifBlank { null })
    }.getOrNull()

    private fun httpGet(target: String): String {
        val connection = (URL(target).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15_000
            readTimeout = 15_000
            setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36")
            setRequestProperty("Accept-Language", "en")
        }
        return try {
            if (connection.responseCode !in 200..299) {
                throw IOException("HTTP ${connection.responseCode}")
            }
            connection.inputStream.bufferedReader().use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }

    /** Downloads into a private per-job folder; the caller copies the single result into MediaStore. */
    suspend fun download(
        context: Context,
        job: Job,
        onProgress: (Int, Long?) -> Unit
    ): File = withContext(Dispatchers.IO) {
        init(context)
        val dir = File(context.filesDir, "tmp/${job.id}").apply {
            deleteRecursively()
            mkdirs()
        }
        val request = YoutubeDLRequest(job.url)
        Formats.options(job.format, job.quality).forEach { (key, value) ->
            if (value == null) request.addOption(key) else request.addOption(key, value)
        }
        request.addOption("-o", File(dir, "media.%(ext)s").absolutePath)
        cookiesFile(context)?.let { request.addOption("--cookies", it.absolutePath) }

        var lastPercent = -1
        var lastAt = 0L
        try {
            YoutubeDL.getInstance().execute(request, job.id, false) { progress, eta, _ ->
                val percent = progress.toInt().coerceIn(0, 100)
                val now = System.currentTimeMillis()
                if (percent != lastPercent || now - lastAt >= 500) {
                    lastPercent = percent
                    lastAt = now
                    onProgress(percent, eta.takeIf { it > 0 })
                }
            }
        } catch (e: YoutubeDL.CanceledException) {
            dir.deleteRecursively()
            throw EngineCanceled()
        } catch (e: Exception) {
            Log.e("DownloadEngine", "download failed for ${job.url}: ${e.message}", e)
            dir.deleteRecursively()
            throw EngineException(DownloadError.fromMessage(e.message), e.message ?: "download failed")
        }

        dir.listFiles()
            ?.filter { it.isFile && it.length() > 0 && !it.name.endsWith(".part") }
            ?.maxByOrNull { it.length() }
            ?: throw EngineException(DownloadError.UNKNOWN, "no output file")
    }

    fun cancel(jobId: String) {
        runCatching { YoutubeDL.getInstance().destroyProcessById(jobId) }
    }

    suspend fun update(context: Context): String = withContext(Dispatchers.IO) {
        init(context)
        val status = YoutubeDL.getInstance().updateYoutubeDL(context, YoutubeDL.UpdateChannel.STABLE)
        if (status == YoutubeDL.UpdateStatus.DONE) "updated" else "uptodate"
    }

    fun version(context: Context): String =
        runCatching { YoutubeDL.getInstance().versionName(context) }.getOrNull() ?: "—"

    fun clearTemp(context: Context) {
        File(context.filesDir, "tmp").deleteRecursively()
    }

    fun cookiesFile(context: Context): File? =
        File(context.filesDir, "cookies.txt").takeIf { it.exists() && it.length() > 0 }

    fun isOnline(context: Context): Boolean = runCatching {
        val manager = context.getSystemService(ConnectivityManager::class.java) ?: return true
        val network = manager.activeNetwork ?: return false
        val caps = manager.getNetworkCapabilities(network) ?: return false
        caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }.getOrDefault(true)

    /** 403s and extractor breakage are almost always a stale yt-dlp; anything else fails fast. */
    fun isRetryableEngineFailure(error: Exception): Boolean {
        if (error is EngineException && error.error == DownloadError.FORBIDDEN) return true
        val message = error.message?.lowercase() ?: return false
        return listOf(
            "http error 403",
            "403: forbidden",
            "unable to extract",
            "signature",
            "nsig",
            "player response",
            "precondition check failed"
        ).any { it in message }
    }

    private val NEXT_DATA_RE =
        Regex("""<script id="__NEXT_DATA__"[^>]*>(.*?)</script>""", RegexOption.DOT_MATCHES_ALL)
    private val COVER_RE = Regex("""https://image-cdn[^"\\]+""")
}
