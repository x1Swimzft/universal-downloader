package com.x1swimzft.universaldownloader.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlToolsTest {

    @Test
    fun extractUrlFindsFirstLinkInShareText() {
        val text = "ดูคลิปนี้ https://www.tiktok.com/@a/video/123?is_from_webapp=1 สนุกมาก"
        assertEquals(
            "https://www.tiktok.com/@a/video/123?is_from_webapp=1",
            UrlTools.extractUrl(text)
        )
    }

    @Test
    fun extractUrlTrimsTrailingPunctuation() {
        assertEquals(
            "https://example.com/a",
            UrlTools.extractUrl("watch https://example.com/a).")
        )
        assertEquals(
            "https://example.com/b?x=1",
            UrlTools.extractUrl("watch https://example.com/b?x=1, then")
        )
    }

    @Test
    fun extractUrlReturnsNullWhenNoLinkExists() {
        assertNull(UrlTools.extractUrl("no links here"))
        assertNull(UrlTools.extractUrl(null))
    }

    @Test
    fun isValidAcceptsHttpUrlsAndRejectsOtherInput() {
        assertTrue(UrlTools.isValid("https://youtu.be/abc"))
        assertTrue(UrlTools.isValid("http://example.com/video"))
        assertFalse(UrlTools.isValid("not a url"))
        assertFalse(UrlTools.isValid("ftp://x.com/a"))
        assertFalse(UrlTools.isValid(""))
    }

    @Test
    fun looksLikePlaylistDetectsYoutubePlaylistAndChannels() {
        assertTrue(UrlTools.looksLikePlaylist("https://www.youtube.com/playlist?list=PL123"))
        assertTrue(UrlTools.looksLikePlaylist("https://www.youtube.com/@channel"))
        assertTrue(UrlTools.looksLikePlaylist("https://www.youtube.com/channel/UC123"))
    }

    @Test
    fun looksLikePlaylistDetectsSoundcloudSets() {
        assertTrue(UrlTools.looksLikePlaylist("https://soundcloud.com/artist/sets/album"))
    }

    @Test
    fun looksLikePlaylistRejectsSingleVideoUrls() {
        assertFalse(UrlTools.looksLikePlaylist("https://www.youtube.com/watch?v=abc"))
        assertFalse(UrlTools.looksLikePlaylist("https://www.tiktok.com/@a/video/123"))
        assertFalse(UrlTools.looksLikePlaylist("https://www.instagram.com/reel/abc/"))
    }

    @Test
    fun looksLikePlaylistRejectsPlaylistParameterOnWatchUrl() {
        assertFalse(UrlTools.looksLikePlaylist("https://www.youtube.com/watch?v=abc&list=PL123"))
    }

    @Test
    fun platformOfMapsKnownHosts() {
        assertEquals("YouTube", UrlTools.platformOf("https://www.youtube.com/watch?v=abc"))
        assertEquals("YouTube", UrlTools.platformOf("https://youtu.be/abc"))
        assertEquals("TikTok", UrlTools.platformOf("https://www.tiktok.com/@a/video/123"))
        assertEquals("Instagram", UrlTools.platformOf("https://www.instagram.com/reel/abc/"))
        assertEquals("X", UrlTools.platformOf("https://x.com/user/status/1"))
    }

    @Test
    fun platformOfFallsBackToHost() {
        assertEquals("example.com", UrlTools.platformOf("https://example.com/video/1"))
    }

    @Test
    fun sanitizeFileNameReplacesForbiddenAndControlCharacters() {
        assertEquals(
            "a b c d e f g h i j",
            UrlTools.sanitizeFileName("""a/b\c:d*e?f"g<h>i|j""")
        )
        assertEquals("a b c", UrlTools.sanitizeFileName("a\u0001b\u001fc"))
    }

    @Test
    fun sanitizeFileNameCollapsesWhitespaceAndTrimsDots() {
        assertEquals("hello world", UrlTools.sanitizeFileName("  hello   world  "))
        assertEquals("video", UrlTools.sanitizeFileName("video..."))
    }

    @Test
    fun sanitizeFileNameTruncatesTo100Characters() {
        val result = UrlTools.sanitizeFileName("x".repeat(150))
        assertEquals(100, result.length)
        assertEquals("x".repeat(100), result)
    }

    @Test
    fun sanitizeFileNameFallsBackToDownloadForBlankInput() {
        assertEquals("download", UrlTools.sanitizeFileName(""))
        assertEquals("download", UrlTools.sanitizeFileName("   "))
        assertEquals("download", UrlTools.sanitizeFileName("\u0001"))
    }

    @Test
    fun displayNameAppendsFormatExtension() {
        assertEquals("My Video.mp4", UrlTools.displayName("My: Video?", MediaFormat.MP4))
    }
}
