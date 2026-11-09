package com.x1swimzft.universaldownloader.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelsTest {

    @Test
    fun fromMessageMapsRepresentativeFailures() {
        val cases = listOf(
            "ERROR: Sign in to confirm you are not a bot" to DownloadError.LOGIN,
            "Private video" to DownloadError.PRIVATE,
            "This video is unavailable" to DownloadError.UNAVAILABLE,
            "Unable to download webpage: Connection timed out" to DownloadError.NETWORK,
            "No space left on device" to DownloadError.STORAGE,
            "ERROR: unable to download video data: HTTP Error 403: Forbidden" to DownloadError.FORBIDDEN,
            "ERROR: Unsupported URL: https://example.com/x" to DownloadError.UNSUPPORTED
        )

        for ((message, expected) in cases) {
            assertEquals("wrong mapping for: $message", expected, DownloadError.fromMessage(message))
        }
    }

    @Test
    fun fromMessageFallsBackToUnknown() {
        assertEquals(DownloadError.UNKNOWN, DownloadError.fromMessage("something unexpected"))
        assertEquals(DownloadError.UNKNOWN, DownloadError.fromMessage(null))
    }

    @Test
    fun newJobHasQueuedDefaultsAndUniqueId() {
        val first = newJob()
        val second = newJob()

        assertEquals(JobStatus.QUEUED, first.status)
        assertEquals(0, first.progress)
        assertTrue("id should not be blank", first.id.isNotBlank())
        assertTrue("second id should not be blank", second.id.isNotBlank())
        assertNotEquals(first.id, second.id)
    }

    @Test
    fun jobStatusFlagsMatchOnlyTheExpectedStates() {
        val expectedActive = setOf(JobStatus.DOWNLOADING, JobStatus.PROCESSING)
        val expectedFinished = setOf(JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED)

        assertEquals(
            "only DOWNLOADING and PROCESSING are active",
            expectedActive,
            JobStatus.values().filter { it.isActive }.toSet()
        )
        assertEquals(
            "only DONE, FAILED and CANCELED are finished",
            expectedFinished,
            JobStatus.values().filter { it.isFinished }.toSet()
        )
    }

    private fun newJob() = Job(
        url = "https://example.com/video/1",
        title = "Example video",
        platform = "Example",
        format = MediaFormat.MP4,
        quality = "best"
    )
}
