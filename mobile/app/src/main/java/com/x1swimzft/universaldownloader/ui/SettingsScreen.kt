@file:OptIn(ExperimentalLayoutApi::class)

package com.x1swimzft.universaldownloader.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.x1swimzft.universaldownloader.R
import com.x1swimzft.universaldownloader.core.Formats
import com.x1swimzft.universaldownloader.core.MediaFormat
import com.x1swimzft.universaldownloader.data.Prefs
import com.x1swimzft.universaldownloader.engine.DownloadEngine
import com.x1swimzft.universaldownloader.ui.components.ChoiceChip
import com.x1swimzft.universaldownloader.ui.components.Divider
import com.x1swimzft.universaldownloader.ui.components.ScreenHeader
import com.x1swimzft.universaldownloader.ui.components.SectionLabel
import com.x1swimzft.universaldownloader.ui.components.SettingRow
import com.x1swimzft.universaldownloader.ui.components.UdCard
import com.x1swimzft.universaldownloader.ui.components.UdOutlineButton
import com.x1swimzft.universaldownloader.ui.components.qualityLabel
import com.x1swimzft.universaldownloader.ui.theme.UdColor
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun SettingsScreen(onLanguageChanged: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var language by remember { mutableStateOf(Prefs.language()) }
    var defaultFormat by remember { mutableStateOf(Prefs.defaultFormat()) }
    var videoQuality by remember { mutableStateOf(Prefs.videoQuality()) }
    var audioQuality by remember { mutableStateOf(Prefs.audioQuality()) }
    var concurrent by remember { mutableStateOf(Prefs.maxConcurrent()) }
    var clipboard by remember { mutableStateOf(Prefs.clipboardOnOpen()) }

    var engineVersion by remember { mutableStateOf(DownloadEngine.version(context)) }
    var updating by remember { mutableStateOf(false) }
    var updateResult by remember { mutableStateOf("") }

    // The bundled version string is only readable after the engine unpacks itself once.
    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) { runCatching { DownloadEngine.init(context) } }
        engineVersion = DownloadEngine.version(context)
    }

    var cookiesStatus by remember { mutableStateOf<String?>(null) }
    var tempStatus by remember { mutableStateOf("") }

    val versionName = remember {
        runCatching {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        }.getOrNull() ?: "1.0.0"
    }

    val cookiesPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            scope.launch {
                val saved = withContext(Dispatchers.IO) {
                    runCatching {
                        context.contentResolver.openInputStream(uri)?.use { input ->
                            File(context.filesDir, "cookies.txt").outputStream().use { output ->
                                input.copyTo(output)
                            }
                        } != null
                    }.getOrDefault(false)
                }
                if (saved) cookiesStatus = context.getString(R.string.cookies_loaded)
            }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp)
    ) {
        ScreenHeader(stringResource(R.string.settings_title))
        Spacer(Modifier.height(16.dp))

        SettingsSection(stringResource(R.string.section_language)) {
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                listOf(
                    "system" to R.string.language_system,
                    "en" to R.string.language_en,
                    "th" to R.string.language_th
                ).forEach { (tag, label) ->
                    ChoiceChip(stringResource(label), language == tag) {
                        Prefs.setLanguage(tag)
                        language = tag
                        onLanguageChanged()
                    }
                }
            }
        }

        SettingsSection(stringResource(R.string.section_downloads)) {
            ChipSetting(stringResource(R.string.setting_default_format)) {
                MediaFormat.entries.forEach { format ->
                    ChoiceChip(format.id.uppercase(), defaultFormat == format) {
                        Prefs.setDefaultFormat(format)
                        defaultFormat = format
                    }
                }
            }
            Divider()
            ChipSetting(stringResource(R.string.setting_video_quality)) {
                Formats.VIDEO_QUALITIES.forEach { quality ->
                    ChoiceChip(qualityLabel(quality), videoQuality == quality) {
                        Prefs.setVideoQuality(quality)
                        videoQuality = quality
                    }
                }
            }
            Divider()
            ChipSetting(stringResource(R.string.setting_audio_quality)) {
                Formats.MP3_QUALITIES.forEach { quality ->
                    ChoiceChip(quality, audioQuality == quality) {
                        Prefs.setAudioQuality(quality)
                        audioQuality = quality
                    }
                }
            }
            Divider()
            ChipSetting(stringResource(R.string.setting_concurrent)) {
                listOf(1, 2, 3).forEach { count ->
                    ChoiceChip(count.toString(), concurrent == count) {
                        Prefs.setMaxConcurrent(count)
                        concurrent = count
                    }
                }
            }
            Divider()
            SettingRow(
                title = stringResource(R.string.setting_clipboard),
                subtitle = stringResource(R.string.setting_clipboard_desc),
                trailing = {
                    Switch(
                        checked = clipboard,
                        onCheckedChange = {
                            Prefs.setClipboardOnOpen(it)
                            clipboard = it
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = UdColor.OnAccent,
                            checkedTrackColor = UdColor.Accent,
                            uncheckedThumbColor = UdColor.Muted,
                            uncheckedTrackColor = UdColor.Raised,
                            uncheckedBorderColor = UdColor.Border
                        )
                    )
                }
            )
        }

        SettingsSection(stringResource(R.string.section_cookies)) {
            SettingRow(
                title = stringResource(R.string.cookies_import),
                subtitle = stringResource(R.string.cookies_desc),
                trailing = {
                    UdOutlineButton(
                        text = stringResource(R.string.cookies_import),
                        onClick = {
                            cookiesPicker.launch(
                                arrayOf("text/plain", "text/*", "application/octet-stream")
                            )
                        }
                    )
                }
            )
            Spacer(Modifier.height(4.dp))
            val hasCookies = DownloadEngine.cookiesFile(context) != null
            Text(
                cookiesStatus ?: if (hasCookies) {
                    stringResource(R.string.cookies_loaded)
                } else {
                    stringResource(R.string.cookies_none)
                },
                style = MaterialTheme.typography.bodySmall,
                color = if (hasCookies) UdColor.Success else UdColor.Muted
            )
        }

        SettingsSection(stringResource(R.string.section_engine)) {
            SettingRow(
                title = stringResource(R.string.engine_version),
                trailing = {
                    Text(
                        engineVersion,
                        style = MaterialTheme.typography.bodySmall,
                        color = UdColor.Muted
                    )
                }
            )
            Divider()
            SettingRow(
                title = stringResource(R.string.engine_update),
                trailing = {
                    UdOutlineButton(
                        text = if (updating) {
                            stringResource(R.string.engine_updating)
                        } else {
                            stringResource(R.string.engine_update)
                        },
                        onClick = {
                            if (!updating) {
                                scope.launch {
                                    updating = true
                                    updateResult = ""
                                    val result = runCatching { DownloadEngine.update(context) }
                                    updateResult = result.fold(
                                        onSuccess = { status ->
                                            context.getString(
                                                if (status == "updated") R.string.engine_update_done
                                                else R.string.engine_updated
                                            )
                                        },
                                        onFailure = { error ->
                                            context.getString(
                                                R.string.engine_update_failed,
                                                error.message ?: ""
                                            )
                                        }
                                    )
                                    engineVersion = DownloadEngine.version(context)
                                    updating = false
                                }
                            }
                        },
                        enabled = !updating
                    )
                }
            )
            if (updateResult.isNotBlank()) {
                Spacer(Modifier.height(8.dp))
                Text(
                    updateResult,
                    style = MaterialTheme.typography.bodySmall,
                    color = UdColor.Muted
                )
            }
        }

        SettingsSection(stringResource(R.string.section_storage)) {
            SettingRow(
                title = stringResource(R.string.clear_temp),
                trailing = {
                    UdOutlineButton(
                        text = stringResource(R.string.clear_temp),
                        onClick = {
                            scope.launch {
                                withContext(Dispatchers.IO) { DownloadEngine.clearTemp(context) }
                                tempStatus = context.getString(R.string.temp_cleared)
                                delay(2500)
                                tempStatus = ""
                            }
                        }
                    )
                }
            )
            if (tempStatus.isNotBlank()) {
                Spacer(Modifier.height(8.dp))
                Text(
                    tempStatus,
                    style = MaterialTheme.typography.bodySmall,
                    color = UdColor.Success
                )
            }
        }

        SettingsSection(stringResource(R.string.section_about)) {
            Text(
                stringResource(R.string.about_version, versionName),
                style = MaterialTheme.typography.titleMedium,
                color = UdColor.Text
            )
            Spacer(Modifier.height(6.dp))
            Text(
                stringResource(R.string.about_license),
                style = MaterialTheme.typography.bodySmall,
                color = UdColor.Muted
            )
            Spacer(Modifier.height(2.dp))
            Text(
                stringResource(R.string.about_folder),
                style = MaterialTheme.typography.bodySmall,
                color = UdColor.Muted
            )
        }

        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun SettingsSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    SectionLabel(title)
    Spacer(Modifier.height(8.dp))
    UdCard(content = content)
    Spacer(Modifier.height(24.dp))
}

/**
 * Chip groups wrap on their own line: in a [SettingRow] trailing slot a [FlowRow] takes the
 * width it wants and squeezes the title out.
 */
@Composable
private fun ChipSetting(title: String, chips: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 12.dp)) {
        Text(title, style = MaterialTheme.typography.bodyLarge, color = UdColor.Text)
        Spacer(Modifier.height(8.dp))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            chips()
        }
    }
}
