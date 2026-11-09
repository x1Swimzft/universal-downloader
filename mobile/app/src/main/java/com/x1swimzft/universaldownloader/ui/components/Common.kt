package com.x1swimzft.universaldownloader.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.x1swimzft.universaldownloader.R
import com.x1swimzft.universaldownloader.core.Job
import com.x1swimzft.universaldownloader.core.JobStatus
import com.x1swimzft.universaldownloader.data.HistoryEntry
import com.x1swimzft.universaldownloader.ui.theme.UdColor
import java.util.Locale
import androidx.compose.ui.res.stringResource

val CardShape = RoundedCornerShape(16.dp)
val ControlShape = RoundedCornerShape(12.dp)
val PillShape = RoundedCornerShape(999.dp)

@Composable
fun UdCard(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit
) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(CardShape)
            .background(UdColor.Surface)
            .border(1.dp, UdColor.Border, CardShape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(16.dp),
        content = content
    )
}

@Composable
fun ScreenHeader(title: String, subtitle: String? = null) {
    Column(Modifier.fillMaxWidth()) {
        Text(title, style = MaterialTheme.typography.headlineSmall, color = UdColor.Text)
        if (subtitle != null) {
            Spacer(Modifier.height(4.dp))
            Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = UdColor.Muted)
        }
    }
}

@Composable
fun SectionLabel(text: String) {
    Text(
        text.uppercase(Locale.getDefault()),
        style = MaterialTheme.typography.labelSmall,
        color = UdColor.Muted,
        letterSpacing = 1.2.sp
    )
}

@Composable
fun UdButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    busy: Boolean = false
) {
    Button(
        onClick = onClick,
        modifier = modifier.fillMaxWidth().heightIn(min = 50.dp),
        enabled = enabled && !busy,
        shape = ControlShape,
        colors = ButtonDefaults.buttonColors(
            containerColor = UdColor.Accent,
            contentColor = UdColor.OnAccent,
            disabledContainerColor = UdColor.AccentDim,
            disabledContentColor = UdColor.Muted
        )
    ) {
        if (busy) {
            CircularProgressIndicator(
                modifier = Modifier.size(18.dp),
                strokeWidth = 2.dp,
                color = UdColor.OnAccent
            )
        } else {
            Text(text, style = MaterialTheme.typography.labelLarge)
        }
    }
}

@Composable
fun UdOutlineButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.heightIn(min = 44.dp),
        enabled = enabled,
        shape = ControlShape,
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = UdColor.Text2,
            disabledContentColor = UdColor.Muted
        )
    ) {
        Text(text, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
fun ChoiceChip(text: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .clip(PillShape)
            .background(if (selected) UdColor.AccentDim else UdColor.Raised)
            .border(1.dp, if (selected) UdColor.AccentDimBorder else UdColor.Border, PillShape)
            .clickable(onClick = onClick)
            .heightIn(min = 40.dp)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            color = if (selected) UdColor.AccentLight else UdColor.Text2
        )
    }
}

@Composable
fun StatusPill(status: JobStatus) {
    val (label, color, bg) = when (status) {
        JobStatus.QUEUED -> Triple(stringResource(R.string.status_queued), UdColor.Text2, UdColor.Raised)
        JobStatus.DOWNLOADING -> Triple(stringResource(R.string.status_downloading), UdColor.AccentLight, UdColor.AccentDim)
        JobStatus.PROCESSING -> Triple(stringResource(R.string.status_processing), UdColor.AccentLight, UdColor.AccentDim)
        JobStatus.DONE -> Triple(stringResource(R.string.status_done), UdColor.Success, UdColor.SuccessBg)
        JobStatus.FAILED -> Triple(stringResource(R.string.status_failed), UdColor.Danger, UdColor.DangerBg)
        JobStatus.CANCELED -> Triple(stringResource(R.string.status_canceled), UdColor.Muted, UdColor.Raised)
    }
    Text(
        label,
        style = MaterialTheme.typography.labelSmall,
        color = color,
        modifier = Modifier
            .clip(PillShape)
            .background(bg)
            .padding(horizontal = 10.dp, vertical = 4.dp)
    )
}

@Composable
fun EmptyState(title: String, body: String, modifier: Modifier = Modifier) {
    Column(
        modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(title, style = MaterialTheme.typography.titleMedium, color = UdColor.Text)
        Spacer(Modifier.height(8.dp))
        Text(
            body,
            style = MaterialTheme.typography.bodyMedium,
            color = UdColor.Muted,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center
        )
    }
}

@Composable
fun SettingRow(
    title: String,
    subtitle: String? = null,
    trailing: @Composable () -> Unit
) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 52.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = UdColor.Text)
            if (subtitle != null) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = UdColor.Muted)
            }
        }
        Spacer(Modifier.width(12.dp))
        trailing()
    }
}

@Composable
fun Thumbnail(url: String?, modifier: Modifier = Modifier) {
    AsyncImage(
        model = url,
        contentDescription = null,
        contentScale = ContentScale.Crop,
        modifier = modifier
            .size(52.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(UdColor.Raised)
    )
}

@Composable
fun JobCard(
    job: Job,
    onCancel: () -> Unit,
    onRetry: () -> Unit,
    onRemove: () -> Unit,
    onOpen: () -> Unit,
    onShare: () -> Unit
) {
    UdCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Thumbnail(job.thumbnail)
            Spacer(Modifier.width(12.dp))
            val quality = qualityLabel(job.quality)
            val meta = listOfNotNull(
                job.platform,
                job.format.id.uppercase(Locale.US),
                quality
            ).joinToString(" · ")
            Column(Modifier.weight(1f)) {
                Text(
                    job.title,
                    style = MaterialTheme.typography.titleMedium,
                    color = UdColor.Text,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    meta,
                    style = MaterialTheme.typography.bodySmall,
                    color = UdColor.Muted,
                    maxLines = 1
                )
            }
            Spacer(Modifier.width(8.dp))
            StatusPill(job.status)
        }

        if (job.status.isActive) {
            Spacer(Modifier.height(12.dp))
            LinearProgressIndicator(
                progress = { job.progress / 100f },
                modifier = Modifier.fillMaxWidth().height(6.dp).clip(PillShape),
                color = UdColor.Accent,
                trackColor = UdColor.Border
            )
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${job.progress}%", style = MaterialTheme.typography.bodySmall, color = UdColor.Text2)
                val eta = job.etaSec
                Text(
                    if (eta != null && eta > 0) stringResource(R.string.eta_left, eta) else "",
                    style = MaterialTheme.typography.bodySmall,
                    color = UdColor.Muted
                )
            }
        }

        if (job.status == JobStatus.FAILED && job.error != null) {
            Spacer(Modifier.height(8.dp))
            Text(
                errorText(job.error),
                style = MaterialTheme.typography.bodySmall,
                color = UdColor.Danger
            )
        }

        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            when {
                job.status.isActive -> UdOutlineButton(stringResource(R.string.action_cancel), onCancel)
                job.status == JobStatus.QUEUED -> UdOutlineButton(stringResource(R.string.action_cancel), onCancel)
                job.status == JobStatus.DONE -> {
                    UdOutlineButton(stringResource(R.string.action_open), onOpen)
                    UdOutlineButton(stringResource(R.string.action_share), onShare)
                    UdOutlineButton(stringResource(R.string.action_remove), onRemove)
                }
                else -> {
                    UdOutlineButton(stringResource(R.string.action_retry), onRetry)
                    UdOutlineButton(stringResource(R.string.action_remove), onRemove)
                }
            }
        }
    }
}

@Composable
fun HistoryCard(entry: HistoryEntry, onOpen: () -> Unit, onDelete: () -> Unit) {
    UdCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Thumbnail(entry.thumbnail)
            Spacer(Modifier.width(12.dp))
            val quality = qualityLabel(entry.quality)
            val meta = listOfNotNull(
                entry.platform,
                entry.format.uppercase(Locale.US),
                quality,
                formatBytes(entry.sizeBytes)
            ).filter { it.isNotBlank() }.joinToString(" · ")
            Column(Modifier.weight(1f)) {
                Text(
                    entry.title,
                    style = MaterialTheme.typography.titleMedium,
                    color = UdColor.Text,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    meta,
                    style = MaterialTheme.typography.bodySmall,
                    color = UdColor.Muted,
                    maxLines = 1
                )
            }
            Spacer(Modifier.width(8.dp))
            Text(
                if (entry.status == JobStatus.DONE.name) stringResource(R.string.status_done)
                else stringResource(R.string.status_failed),
                style = MaterialTheme.typography.labelSmall,
                color = if (entry.status == JobStatus.DONE.name) UdColor.Success else UdColor.Danger
            )
        }
        if (entry.status == JobStatus.DONE.name) {
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                UdOutlineButton(stringResource(R.string.action_open), onOpen)
                UdOutlineButton(stringResource(R.string.action_delete), onDelete)
            }
        } else {
            Spacer(Modifier.height(10.dp))
            UdOutlineButton(stringResource(R.string.action_delete), onDelete)
        }
    }
}

@Composable
fun qualityLabel(quality: String): String =
    if (quality == "best") stringResource(R.string.quality_best) else quality

@Composable
fun errorText(code: String?): String = when (code) {
    "NETWORK" -> stringResource(R.string.err_network)
    "LOGIN" -> stringResource(R.string.err_login)
    "PRIVATE" -> stringResource(R.string.err_private)
    "UNAVAILABLE" -> stringResource(R.string.err_unavailable)
    "PLAYLIST" -> stringResource(R.string.err_playlist)
    "COOKIES" -> stringResource(R.string.err_cookies)
    "STORAGE" -> stringResource(R.string.err_storage)
    "FORBIDDEN" -> stringResource(R.string.err_forbidden)
    "UNSUPPORTED" -> stringResource(R.string.err_unsupported)
    "CANCELED" -> stringResource(R.string.status_canceled)
    "ENGINE" -> stringResource(R.string.err_engine)
    else -> stringResource(R.string.err_unknown)
}

fun formatBytes(bytes: Long?): String {
    if (bytes == null || bytes <= 0) return ""
    val units = arrayOf("B", "KB", "MB", "GB")
    var value = bytes.toDouble()
    var index = 0
    while (value >= 1024 && index < units.lastIndex) {
        value /= 1024
        index++
    }
    return if (index == 0) "${value.toInt()} ${units[index]}"
    else String.format(Locale.US, "%.1f %s", value, units[index])
}

fun formatDuration(seconds: Int?): String {
    if (seconds == null || seconds <= 0) return ""
    val h = seconds / 3600
    val m = (seconds % 3600) / 60
    val s = seconds % 60
    return if (h > 0) String.format(Locale.US, "%d:%02d:%02d", h, m, s)
    else String.format(Locale.US, "%d:%02d", m, s)
}

@Composable
fun Divider() {
    Spacer(
        Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(UdColor.Border)
    )
}

@Composable
fun Dot(color: Color, size: Int = 6) {
    Spacer(
        Modifier
            .size(size.dp)
            .clip(PillShape)
            .background(color)
    )
}
