package com.x1swimzft.universaldownloader.ui

import android.content.ClipboardManager
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.x1swimzft.universaldownloader.Downloads
import com.x1swimzft.universaldownloader.R
import com.x1swimzft.universaldownloader.core.DownloadError
import com.x1swimzft.universaldownloader.core.Formats
import com.x1swimzft.universaldownloader.core.Job
import com.x1swimzft.universaldownloader.core.MediaFormat
import com.x1swimzft.universaldownloader.core.MediaInfo
import com.x1swimzft.universaldownloader.core.UrlTools
import com.x1swimzft.universaldownloader.data.Prefs
import com.x1swimzft.universaldownloader.engine.DownloadEngine
import com.x1swimzft.universaldownloader.engine.EngineException
import com.x1swimzft.universaldownloader.ui.components.ChoiceChip
import com.x1swimzft.universaldownloader.ui.components.ControlShape
import com.x1swimzft.universaldownloader.ui.components.SectionLabel
import com.x1swimzft.universaldownloader.ui.components.UdButton
import com.x1swimzft.universaldownloader.ui.components.UdCard
import com.x1swimzft.universaldownloader.ui.components.UdOutlineButton
import com.x1swimzft.universaldownloader.ui.components.errorText
import com.x1swimzft.universaldownloader.ui.components.formatDuration
import com.x1swimzft.universaldownloader.ui.components.qualityLabel
import com.x1swimzft.universaldownloader.ui.theme.UdColor
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DownloadScreen(
    incomingUrl: String?,
    onIncomingConsumed: () -> Unit,
    onQueued: () -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val clipboard = remember { context.getSystemService(ClipboardManager::class.java) }

    var url by rememberSaveable { mutableStateOf("") }
    var format by rememberSaveable { mutableStateOf(Prefs.defaultFormat()) }
    var quality by rememberSaveable {
        mutableStateOf(
            (if (format.isAudio) Prefs.audioQuality() else Prefs.videoQuality())
                .takeIf { it in Formats.qualities(format) }
                ?: Formats.defaultQuality(format)
        )
    }
    var info by remember { mutableStateOf<MediaInfo?>(null) }
    var analyzing by remember { mutableStateOf(false) }
    var errorCode by remember { mutableStateOf<String?>(null) }
    var pasteEmpty by remember { mutableStateOf(false) }

    fun analyze() {
        val target = url.trim()
        when {
            target.isBlank() -> {
                errorCode = "URL_EMPTY"
                return
            }
            !UrlTools.isValid(target) -> {
                errorCode = "URL_INVALID"
                return
            }
        }
        scope.launch {
            analyzing = true
            errorCode = null
            info = null
            try {
                val result = DownloadEngine.analyze(context, target)
                info = result
                if (result.audioOnly) {
                    format = MediaFormat.MP3
                    quality = Prefs.audioQuality()
                        .takeIf { it in Formats.qualities(MediaFormat.MP3) }
                        ?: Formats.defaultQuality(MediaFormat.MP3)
                }
            } catch (e: EngineException) {
                errorCode = e.error.name
            } catch (e: Exception) {
                errorCode = DownloadError.UNKNOWN.name
            } finally {
                analyzing = false
            }
        }
    }

    fun pasteFromClipboard() {
        val text = clipboard?.primaryClip
            ?.takeIf { it.itemCount > 0 }
            ?.getItemAt(0)
            ?.coerceToText(context)
            ?.toString()
        val found = UrlTools.extractUrl(text)
        if (found != null) {
            url = found
            pasteEmpty = false
        } else {
            pasteEmpty = true
        }
    }

    LaunchedEffect(incomingUrl) {
        if (!incomingUrl.isNullOrBlank()) {
            url = incomingUrl
            onIncomingConsumed()
        }
    }

    LaunchedEffect(Unit) {
        if (Prefs.clipboardOnOpen()) {
            val text = clipboard?.primaryClip
                ?.takeIf { it.itemCount > 0 }
                ?.getItemAt(0)
                ?.coerceToText(context)
                ?.toString()
            UrlTools.extractUrl(text)?.let { if (url.isBlank()) url = it }
        }
    }

    LaunchedEffect(pasteEmpty) {
        if (pasteEmpty) {
            delay(2500)
            pasteEmpty = false
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp)
    ) {
        Text(
            stringResource(R.string.download_headline),
            style = MaterialTheme.typography.headlineMedium,
            color = UdColor.Text
        )
        Spacer(Modifier.height(6.dp))
        Text(
            stringResource(R.string.download_sub),
            style = MaterialTheme.typography.bodyMedium,
            color = UdColor.Muted
        )

        Spacer(Modifier.height(24.dp))
        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            shape = ControlShape,
            placeholder = { Text(stringResource(R.string.url_hint)) },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Uri,
                imeAction = ImeAction.Go
            ),
            keyboardActions = KeyboardActions(onGo = { analyze() }),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = UdColor.Accent,
                unfocusedBorderColor = UdColor.Border,
                focusedContainerColor = UdColor.Surface,
                unfocusedContainerColor = UdColor.Surface,
                cursorColor = UdColor.Accent,
                focusedTextColor = UdColor.Text,
                unfocusedTextColor = UdColor.Text,
                focusedPlaceholderColor = UdColor.Muted,
                unfocusedPlaceholderColor = UdColor.Muted
            )
        )

        Spacer(Modifier.height(12.dp))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            UdOutlineButton(stringResource(R.string.paste), onClick = { pasteFromClipboard() })
            UdButton(
                text = stringResource(R.string.analyze),
                onClick = { analyze() },
                modifier = Modifier.weight(1f),
                enabled = url.isNotBlank(),
                busy = analyzing
            )
        }

        if (pasteEmpty) {
            Spacer(Modifier.height(8.dp))
            Text(
                stringResource(R.string.paste_empty),
                style = MaterialTheme.typography.bodySmall,
                color = UdColor.Muted
            )
        }

        errorCode?.let { code ->
            Spacer(Modifier.height(12.dp))
            ErrorLine(code)
        }

        val preview = info
        if (preview != null) {
            Spacer(Modifier.height(20.dp))
            UdCard {
                preview.thumbnail?.let { thumb ->
                    AsyncImage(
                        model = thumb,
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .fillMaxWidth()
                            .aspectRatio(16f / 9f)
                            .clip(RoundedCornerShape(12.dp))
                            .background(UdColor.Raised)
                    )
                    Spacer(Modifier.height(12.dp))
                }

                Text(
                    preview.title,
                    style = MaterialTheme.typography.titleMedium,
                    color = UdColor.Text,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis
                )

                val meta = listOfNotNull(
                    preview.platform,
                    formatDuration(preview.durationSec),
                    preview.uploader
                ).filter { it.isNotBlank() }.joinToString(" · ")
                if (meta.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        meta,
                        style = MaterialTheme.typography.bodySmall,
                        color = UdColor.Muted
                    )
                }

                Spacer(Modifier.height(16.dp))
                SectionLabel(stringResource(R.string.format_label))
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MediaFormat.entries.forEach { candidate ->
                        ChoiceChip(
                            text = candidate.id.uppercase(),
                            selected = candidate == format,
                            onClick = {
                                if (candidate != format) {
                                    format = candidate
                                    quality = Formats.defaultQuality(candidate)
                                }
                            }
                        )
                    }
                }

                Spacer(Modifier.height(16.dp))
                SectionLabel(stringResource(R.string.quality_label))
                Spacer(Modifier.height(8.dp))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Formats.qualities(format).forEach { candidate ->
                        ChoiceChip(
                            text = qualityLabel(candidate),
                            selected = candidate == quality,
                            onClick = { quality = candidate }
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(20.dp))
        UdButton(
            text = stringResource(R.string.btn_download),
            onClick = {
                val current = info
                if (current != null) {
                    Downloads.enqueue(
                        context,
                        Job(
                            url = current.url,
                            title = current.title,
                            platform = current.platform,
                            thumbnail = current.thumbnail,
                            durationSec = current.durationSec,
                            format = format,
                            quality = quality
                        )
                    )
                    info = null
                    url = ""
                    onQueued()
                }
            },
            enabled = info != null
        )

        Spacer(Modifier.height(24.dp))
        Text(
            stringResource(R.string.cookies_hint),
            style = MaterialTheme.typography.bodySmall,
            color = UdColor.Muted
        )
        Spacer(Modifier.height(24.dp))
    }
}

/** Link validation has its own copy; errorText() would collapse both into the generic message. */
@Composable
private fun ErrorLine(code: String) {
    Text(
        when (code) {
            "URL_EMPTY" -> stringResource(R.string.err_url_empty)
            "URL_INVALID" -> stringResource(R.string.err_url_invalid)
            else -> errorText(code)
        },
        style = MaterialTheme.typography.bodyMedium,
        color = UdColor.Danger
    )
}
