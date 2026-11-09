package com.x1swimzft.universaldownloader.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.x1swimzft.universaldownloader.Downloads
import com.x1swimzft.universaldownloader.R
import com.x1swimzft.universaldownloader.ui.components.EmptyState
import com.x1swimzft.universaldownloader.ui.components.JobCard
import com.x1swimzft.universaldownloader.ui.components.ScreenHeader
import com.x1swimzft.universaldownloader.ui.theme.UdColor

@Composable
fun QueueScreen() {
    val context = LocalContext.current
    val jobs by Downloads.jobs.collectAsState()
    val hasFinished = jobs.any { it.status.isFinished }

    Column(
        Modifier
            .fillMaxSize()
            .padding(20.dp)
    ) {
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(Modifier.weight(1f)) {
                ScreenHeader(stringResource(R.string.queue_title))
            }
            if (hasFinished) {
                Text(
                    stringResource(R.string.queue_clear_finished),
                    style = MaterialTheme.typography.labelMedium,
                    color = UdColor.Muted,
                    modifier = Modifier
                        .clickable { Downloads.clearFinished() }
                        .padding(horizontal = 8.dp, vertical = 10.dp)
                )
            }
        }

        if (jobs.isEmpty()) {
            Box(
                Modifier.weight(1f).fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                EmptyState(
                    title = stringResource(R.string.queue_empty_title),
                    body = stringResource(R.string.queue_empty_body)
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                contentPadding = PaddingValues(vertical = 16.dp)
            ) {
                items(jobs, key = { it.id }) { job ->
                    JobCard(
                        job = job,
                        onCancel = { Downloads.cancel(context, job.id) },
                        onRetry = { Downloads.retry(context, job.id) },
                        onRemove = { Downloads.remove(job.id) },
                        onOpen = { job.fileUri?.let { openFile(context, it) } },
                        onShare = { job.fileUri?.let { shareFile(context, it) } }
                    )
                }
            }
        }
    }
}
