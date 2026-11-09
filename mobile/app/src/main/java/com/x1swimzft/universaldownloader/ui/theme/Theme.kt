package com.x1swimzft.universaldownloader.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Tokens lifted from the desktop app's globals.css so the mobile build reads as the same product.
object UdColor {
    val Bg = Color(0xFF0A0A0F)
    val Surface = Color(0xFF111118)
    val Raised = Color(0xFF191923)
    val Hover = Color(0xFF232334)
    val Border = Color(0xFF242432)
    val Text = Color(0xFFECEBF2)
    val Text2 = Color(0xFFC9C8D6)
    val Muted = Color(0xFF9A99AB)
    val Accent = Color(0xFFC8283F)
    val AccentHover = Color(0xFFD93450)
    val AccentLight = Color(0xFFFF5A70)
    val AccentDim = Color(0xFF2A1119)
    val AccentDimBorder = Color(0xFF6B1F30)
    val Success = Color(0xFF4ADE80)
    val SuccessBg = Color(0xFF0F2A1C)
    val Danger = Color(0xFFFF8A99)
    val DangerBg = Color(0xFF2A1119)
    val OnAccent = Color(0xFFFFFFFF)
}

private val UdTypography = Typography(
    headlineMedium = TextStyle(fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold),
    headlineSmall = TextStyle(fontSize = 22.sp, lineHeight = 29.sp, fontWeight = FontWeight.Bold),
    titleLarge = TextStyle(fontSize = 18.sp, lineHeight = 25.sp, fontWeight = FontWeight.Bold),
    titleMedium = TextStyle(fontSize = 15.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold),
    bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontSize = 13.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 18.sp),
    labelLarge = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.SemiBold),
    labelMedium = TextStyle(fontSize = 12.sp, lineHeight = 17.sp, fontWeight = FontWeight.Medium),
    labelSmall = TextStyle(fontSize = 11.sp, lineHeight = 15.sp, fontWeight = FontWeight.Medium)
)

private val UdColorScheme = darkColorScheme(
    primary = UdColor.Accent,
    onPrimary = UdColor.OnAccent,
    primaryContainer = UdColor.AccentDim,
    onPrimaryContainer = UdColor.AccentLight,
    secondary = UdColor.AccentLight,
    onSecondary = UdColor.OnAccent,
    background = UdColor.Bg,
    onBackground = UdColor.Text,
    surface = UdColor.Surface,
    onSurface = UdColor.Text,
    surfaceVariant = UdColor.Raised,
    onSurfaceVariant = UdColor.Text2,
    surfaceContainer = UdColor.Raised,
    surfaceContainerHigh = UdColor.Hover,
    outline = UdColor.Border,
    outlineVariant = UdColor.Border,
    error = UdColor.Danger,
    onError = UdColor.Bg,
    errorContainer = UdColor.DangerBg,
    onErrorContainer = UdColor.Danger
)

@Composable
fun UDTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = UdColorScheme, typography = UdTypography, content = content)
}
