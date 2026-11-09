package com.x1swimzft.universaldownloader.core

/**
 * yt-dlp option pairs for a format + quality choice. Kept as data so the mapping is unit-testable
 * without touching the Android library.
 */
object Formats {
    val VIDEO_QUALITIES = listOf("best", "1080", "720", "480", "360")
    val MP3_QUALITIES = listOf("320", "192", "128")
    val M4A_QUALITIES = listOf("best")

    fun qualities(format: MediaFormat): List<String> = when (format) {
        MediaFormat.MP4 -> VIDEO_QUALITIES
        MediaFormat.MP3 -> MP3_QUALITIES
        MediaFormat.M4A -> M4A_QUALITIES
    }

    fun defaultQuality(format: MediaFormat): String = qualities(format).first()

    /** H.264 + M4A first for the widest Android playback support, then progressively looser fallbacks. */
    fun videoSelector(quality: String): String =
        if (quality == "best") "bv*+ba/b"
        else "bv*[height<=$quality][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=$quality]+ba/b[height<=$quality]"

    fun options(format: MediaFormat, quality: String): List<Pair<String, String?>> = buildList {
        add("--no-playlist" to null)
        add("--newline" to null)
        add("--merge-output-format" to "mp4")
        when (format) {
            MediaFormat.MP4 -> {
                add("-f" to videoSelector(quality))
            }
            MediaFormat.MP3 -> {
                add("-f" to "ba/b")
                add("-x" to null)
                add("--audio-format" to "mp3")
                add("--audio-quality" to "${quality}K")
            }
            MediaFormat.M4A -> {
                add("-f" to "ba[ext=m4a]/ba/b")
                add("-x" to null)
                add("--audio-format" to "m4a")
                add("--audio-quality" to "0")
            }
        }
    }

    fun mimeType(format: MediaFormat): String = when (format) {
        MediaFormat.MP4 -> "video/mp4"
        MediaFormat.MP3 -> "audio/mpeg"
        MediaFormat.M4A -> "audio/mp4"
    }
}
