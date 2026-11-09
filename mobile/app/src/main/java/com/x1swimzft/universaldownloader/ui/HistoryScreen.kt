package com.x1swimzft.universaldownloader.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.x1swimzft.universaldownloader.Downloads
import com.x1swimzft.universaldownloader.R
import com.x1swimzft.universaldownloader.data.HistoryDb
import com.x1swimzft.universaldownloader.data.HistoryEntry
import com.x1swimzft.universaldownloader.ui.components.EmptyState
import com.x1swimzft.universaldownloader.ui.components.HistoryCard
import com.x1swimzft.universaldownloader.ui.components.PillShape
import com.x1swimzft.universaldownloader.ui.components.ScreenHeader
import com.x1swimzft.universaldownloader.ui.theme.UdColor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun HistoryScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var entries by remember { mutableStateOf<List<HistoryEntry>>(emptyList()) }
    var confirmClear by remember { mutableStateOf(false) }
    val jobs by Downloads.jobs.collectAsState()

    // Reloads whenever a download reaches a finished state; jobs keep the count changing while active.
    LaunchedEffect(jobs.count { it.status.isFinished }) {
        entries = withContext(Dispatchers.IO) { HistoryDb.list(context) }
    }

    Column(Modifier.fillMaxSize().padding(20.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) {
                ScreenHeader(stringResource(R.string.history_title))
            }
            if (entries.isNotEmpty()) {
                Text(
                    stringResource(R.string.history_clear),
                    style = MaterialTheme.typography.labelMedium,
                    color = UdColor.Muted,
                    modifier = Modifier
                        .clip(PillShape)
                        .clickable { confirmClear = true }
                        .padding(horizontal = 10.dp, vertical = 8.dp)
                )
            }
        }

        if (entries.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                EmptyState(
                    title = stringResource(R.string.history_empty_title),
                    body = stringResource(R.string.history_empty_body)
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                contentPadding = PaddingValues(vertical = 16.dp)
            ) {
                items(entries, key = { it.id }) { entry ->
                    HistoryCard(
                        entry = entry,
                        onOpen = { entry.fileUri?.let { openFile(context, it) } },
                        onDelete = {
                            scope.launch {
                                withContext(Dispatchers.IO) { HistoryDb.delete(context, entry.id) }
                                entries = entries.filterNot { it.id == entry.id }
                            }
                        }
                    )
                }
            }
        }
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text(stringResource(R.string.history_clear)) },
            text = { Text(stringResource(R.string.history_clear_message)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirmClear = false
                        scope.launch {
                            entries = withContext(Dispatchers.IO) {
                                HistoryDb.clear(context)
                                HistoryDb.list(context)
                            }
                        }
                    }
                ) {
                    Text(stringResource(R.string.action_delete), color = UdColor.Danger)
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmClear = false }) {
                    Text(stringResource(R.string.action_cancel), color = UdColor.Muted)
                }
            }
        )
    }
}
