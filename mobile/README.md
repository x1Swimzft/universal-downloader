# Universal Downloader — Android

Native Android build of Universal Downloader. Everything runs on the phone: no PC, no server, no uploads.
Powered by [youtubedl-android](https://github.com/yausername/youtubedl-android) (yt-dlp + Python + FFmpeg + QuickJS).

<p>
  <b>Package</b> com.x1swimzft.universaldownloader · <b>minSdk</b> 29 · <b>targetSdk</b> 35 · <b>compileSdk</b> 36
</p>

## Features

- Single-link analysis with thumbnail, title, duration, platform
- MP4 up to 1080p (H.264 first, then best available) merged with FFmpeg
- MP3 320 / 192 / 128 kbps, M4A remux
- Queue with progress, ETA, cancel, retry, and configurable concurrency (1–3)
- Foreground service + notifications that survive leaving the app and turning the screen off
- Files saved through MediaStore to `Download/Universal Downloader` (no storage permission)
- Local history (SQLite) with open/share, delete
- `cookies.txt` import for Instagram and private videos
- Spotify track bridge: reads public track metadata, downloads the matching YouTube audio
- In-app yt-dlp update, refreshed automatically on launch when it is more than 12 h old
- Share-sheet intake (share a link from TikTok/YouTube straight into the app)
- Optional clipboard fill when returning to the app
- English + Thai UI (System / English / ไทย)

## Build

Requirements: JDK 21, Android SDK 36, Android SDK Build-Tools 35/36.

```powershell
cd mobile
$env:JAVA_HOME = "C:\Users\<you>\.jdks\jbr-21.0.11"
.\gradlew.bat :app:assembleDebug
```

Because ABI splits are enabled, the APK is written to:

```
app/build/outputs/apk/debug/app-arm64-v8a-debug.apk    # phones
app/build/outputs/apk/debug/app-x86_64-debug.apk       # emulator
```

Install on a device or a running emulator:

```powershell
adb install -r app\build\outputs\apk\debug\app-arm64-v8a-debug.apk
```

Release:

```powershell
.\gradlew.bat :app:assembleRelease
```

## Project layout

```
app/src/main/java/com/x1swimzft/universaldownloader/
  App.kt                 application, locale wrapper, notification channel
  MainActivity.kt        Compose host, share intent, notification permission
  Downloads.kt           in-memory queue state (StateFlow)
  core/                  formats, URL helpers, models (pure Kotlin, unit tested)
  engine/                youtubedl-android + FFmpeg wrapper
  service/               foreground service, notifications
  media/                 MediaStore writer
  data/                  settings and history persistence
  ui/                    Compose screens and shared components
```

## Limitations (v1)

- One link at a time; playlists and channel URLs are rejected with a clear message
- Pause is not supported — cancel, then retry
- TikTok photo posts, Instagram image carousels, Spotify albums/playlists, Apple Music matching, and clip trimming are not implemented
- Spotify tracks are matched to the top YouTube result, so the file is the YouTube audio rather than Spotify's stream (Spotify is DRM-protected)
- The queue lives in memory: killing the app process drops queued jobs (finished files and history are safe)
- Instagram almost always needs `cookies.txt`

## Licensing

`youtubedl-android` is GPL-3.0, so any distributed APK that bundles it must comply with GPL-3.0.
Personal use is unaffected. The desktop Universal Downloader is MIT; this mobile module inherits GPL
through its download engine.

## Troubleshooting

- **First run: yt-dlp updates itself** — the app refreshes the extractor on launch when the last check
  is over 12 h old. If a download fails with a 403 anyway, it updates once and retries automatically.
  Settings → Update yt-dlp forces a refresh.
- **Download fails on a site that used to work** — open Settings → Update yt-dlp. Sites change their
  extractors constantly.
- **“This site wants a login”** — export cookies with a browser extension to a Netscape-format
  `cookies.txt`, then Settings → Import cookies.txt.
- **APK too large** — that is Python + FFmpeg. Use the ABI split for the target device instead of a
  universal APK.
