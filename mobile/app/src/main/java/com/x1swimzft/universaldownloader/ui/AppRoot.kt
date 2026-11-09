package com.x1swimzft.universaldownloader.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.x1swimzft.universaldownloader.R
import com.x1swimzft.universaldownloader.ui.theme.UdColor

private data class Tab(val label: Int, val icon: Int)

private val tabs = listOf(
    Tab(R.string.nav_download, R.drawable.ic_nav_download),
    Tab(R.string.nav_queue, R.drawable.ic_nav_queue),
    Tab(R.string.nav_history, R.drawable.ic_nav_history),
    Tab(R.string.nav_settings, R.drawable.ic_nav_settings)
)

@Composable
fun AppRoot(
    incomingUrl: String?,
    onIncomingConsumed: () -> Unit,
    onLanguageChanged: () -> Unit
) {
    var selected by rememberSaveable { mutableIntStateOf(0) }

    Scaffold(
        containerColor = UdColor.Bg,
        bottomBar = {
            NavigationBar(containerColor = UdColor.Surface, tonalElevation = 0.dp) {
                tabs.forEachIndexed { index, tab ->
                    NavigationBarItem(
                        selected = selected == index,
                        onClick = { selected = index },
                        icon = {
                            Icon(
                                painter = painterResource(tab.icon),
                                contentDescription = stringResource(tab.label)
                            )
                        },
                        label = { Text(stringResource(tab.label)) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = UdColor.AccentLight,
                            selectedTextColor = UdColor.AccentLight,
                            indicatorColor = UdColor.AccentDim,
                            unselectedIconColor = UdColor.Muted,
                            unselectedTextColor = UdColor.Muted
                        )
                    )
                }
            }
        }
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (selected) {
                0 -> DownloadScreen(
                    incomingUrl = incomingUrl,
                    onIncomingConsumed = onIncomingConsumed,
                    onQueued = { selected = 1 }
                )
                1 -> QueueScreen()
                2 -> HistoryScreen()
                else -> SettingsScreen(onLanguageChanged = onLanguageChanged)
            }
        }
    }
}
