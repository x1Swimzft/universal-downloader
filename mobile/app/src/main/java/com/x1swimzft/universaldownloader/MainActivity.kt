package com.x1swimzft.universaldownloader

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import com.x1swimzft.universaldownloader.core.UrlTools
import com.x1swimzft.universaldownloader.i18n.LocaleHelper
import com.x1swimzft.universaldownloader.ui.AppRoot
import com.x1swimzft.universaldownloader.ui.theme.UDTheme
import com.x1swimzft.universaldownloader.ui.theme.UdColor

class MainActivity : ComponentActivity() {
    private val sharedUrl = mutableStateOf<String?>(null)

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(LocaleHelper.wrap(newBase))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleIntent(intent)
        setContent {
            UDTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = UdColor.Bg) {
                    AppRoot(
                        incomingUrl = sharedUrl.value,
                        onIncomingConsumed = {
                            sharedUrl.value = null
                            setIntent(Intent())
                        },
                        onLanguageChanged = { recreate() }
                    )
                }
            }
        }
        askForNotifications()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent?.action == Intent.ACTION_SEND && intent.type == "text/plain") {
            UrlTools.extractUrl(intent.getStringExtra(Intent.EXTRA_TEXT))?.let { sharedUrl.value = it }
        }
    }

    private fun askForNotifications() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}
