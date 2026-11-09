package com.x1swimzft.universaldownloader.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FormatsTest {

    @Test
    fun qualitiesReturnsExpectedValues() {
        assertEquals(listOf("best", "1080", "720", "480", "360"), Formats.qualities(MediaFormat.MP4))
        assertEquals(listOf("320", "192", "128"), Formats.qualities(MediaFormat.MP3))
        assertEquals(listOf("best"), Formats.qualities(MediaFormat.M4A))
    }

    @Test
    fun defaultQualityUsesFirstValue() {
        assertEquals("best", Formats.defaultQuality(MediaFormat.MP4))
        assertEquals("320", Formats.defaultQuality(MediaFormat.MP3))
        assertEquals("best", Formats.defaultQuality(MediaFormat.M4A))
    }

    @Test
    fun mp4OptionsCapHeightAndMergeToMp4() {
        val options = Formats.options(MediaFormat.MP4, "1080").toMap()

        val selector = options["-f"]
        assertTrue("expected an -f option, got $options", selector != null)
        assertTrue("selector must cap height at 1080, got $selector", selector!!.contains("height<=1080"))
        assertEquals("mp4", options["--merge-output-format"])
        assertTrue("expected --no-playlist, got $options", options.containsKey("--no-playlist"))
        assertNull(options["--no-playlist"])
    }

    @Test
    fun mp4BestUsesSimpleSelector() {
        val options = Formats.options(MediaFormat.MP4, "best")
        assertEquals("bv*+ba/b", options.single { it.first == "-f" }.second)
    }

    @Test
    fun mp3OptionsExtractToMp3AtChosenBitrate() {
        val options = Formats.options(MediaFormat.MP3, "320").toMap()

        assertEquals("ba/b", options["-f"])
        assertTrue("expected -x, got $options", options.containsKey("-x"))
        assertNull(options["-x"])
        assertEquals("mp3", options["--audio-format"])
        assertEquals("320K", options["--audio-quality"])
    }

    @Test
    fun m4aOptionsExtractToM4aAtBestQuality() {
        val options = Formats.options(MediaFormat.M4A, "best").toMap()

        assertEquals("ba[ext=m4a]/ba/b", options["-f"])
        assertTrue("expected -x, got $options", options.containsKey("-x"))
        assertNull(options["-x"])
        assertEquals("m4a", options["--audio-format"])
        assertEquals("0", options["--audio-quality"])
    }

    @Test
    fun mimeTypeMatchesEachFormat() {
        assertEquals("video/mp4", Formats.mimeType(MediaFormat.MP4))
        assertEquals("audio/mpeg", Formats.mimeType(MediaFormat.MP3))
        assertEquals("audio/mp4", Formats.mimeType(MediaFormat.M4A))
    }

    @Test
    fun optionsNeverRepeatAnOptionName() {
        for (format in MediaFormat.values()) {
            for (quality in Formats.qualities(format)) {
                val names = Formats.options(format, quality).map { it.first }
                assertEquals(
                    "duplicate option name for $format/$quality",
                    names.distinct(),
                    names
                )
            }
        }
    }
}
