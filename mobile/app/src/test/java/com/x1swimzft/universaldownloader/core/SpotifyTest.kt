package com.x1swimzft.universaldownloader.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpotifyTest {

    private val trackUrl = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc123"

    @Test
    fun trackIdReadsTrackLinksOnly() {
        assertEquals("4cOdK2wGLETKBW3PvgPWqT", Spotify.trackId(trackUrl))
        assertEquals(
            "4cOdK2wGLETKBW3PvgPWqT",
            Spotify.trackId("https://open.spotify.com/intl-de/track/4cOdK2wGLETKBW3PvgPWqT")
        )
        assertNull(Spotify.trackId("https://open.spotify.com/album/4cOdK2wGLETKBW3PvgPWqT"))
        assertNull(Spotify.trackId("https://open.spotify.com/playlist/4cOdK2wGLETKBW3PvgPWqT"))
        assertNull(Spotify.trackId("https://example.com/track/4cOdK2wGLETKBW3PvgPWqT"))
    }

    @Test
    fun collectionsAreRejectedBeforeAnalysis() {
        assertTrue(Spotify.isCollection("https://open.spotify.com/album/abc"))
        assertTrue(Spotify.isCollection("https://open.spotify.com/playlist/abc"))
        assertTrue(Spotify.isCollection("https://open.spotify.com/artist/abc"))
        assertTrue(Spotify.isCollection("https://open.spotify.com/intl-de/album/abc"))
        assertFalse(Spotify.isCollection(trackUrl))
        assertTrue(UrlTools.looksLikePlaylist("https://open.spotify.com/album/abc"))
    }

    @Test
    fun onlySpotifyHostsAreHandled() {
        assertTrue(Spotify.isSpotify(trackUrl))
        assertTrue(Spotify.isSpotify("https://open.spotify.com/track/abc"))
        assertFalse(Spotify.isSpotify("https://www.youtube.com/watch?v=abc"))
    }

    @Test
    fun searchQueryKeepsArtistWhenKnown() {
        assertEquals(
            "Rick Astley - Never Gonna Give You Up official audio",
            Spotify.searchQuery("Never Gonna Give You Up", "Rick Astley")
        )
        assertEquals(
            "Never Gonna Give You Up official audio",
            Spotify.searchQuery("  Never Gonna Give You Up  ", null)
        )
    }

    @Test
    fun spotifyTracksAreLabelledFromTheUrl() {
        assertEquals("Spotify", UrlTools.platformOf(trackUrl))
    }
}
