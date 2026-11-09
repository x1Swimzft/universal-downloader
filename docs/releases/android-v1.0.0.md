# Universal Downloader — Android v1.0.0 (pre-release)

First public Android build. This is a **debug-signed pre-release**, not a Play Store
release. Everything runs on the phone: no PC, no server, no uploads.

## What is in this build

- Single-link analysis with thumbnail, title, duration and platform.
- MP4 up to 1080p (H.264 first), merged with FFmpeg.
- MP3 320 / 192 / 128 kbps and M4A remux.
- Queue with progress, ETA, cancel, retry and 1–3 concurrent downloads.
- Foreground service and notifications that survive leaving the app and locking the screen.
- Files saved through MediaStore to `Download/Universal Downloader` (no storage permission).
- Local SQLite history with open, share and delete.
- `cookies.txt` import for Instagram and private videos.
- Spotify track bridge: reads public track metadata and downloads matching YouTube audio.
- In-app yt-dlp update, refreshed automatically when older than 12 hours.
- Share-sheet intake and optional clipboard fill.
- English and Thai UI.

## Install

The APK is built per ABI:

| File | Use |
|---|---|
| `app-arm64-v8a-debug.apk` | Most Android phones |
| `app-x86_64-debug.apk` | Emulators and x86_64 devices |

On the phone, open the APK and allow installation from unknown sources when prompted. Over
ADB:

```bash
adb install -r app-arm64-v8a-debug.apk
```

**Signature note:** this build is debug-signed. A future properly signed build cannot be
installed over it; uninstall this pre-release first. There is no in-app auto-update for
Android yet.

## Requirements

- Android 10 or newer (API 29)
- `arm64-v8a` phone or `x86_64` emulator
- Instagram usually needs an imported `cookies.txt`

## Known limits (v1)

- One link at a time; playlist and channel URLs are rejected with a clear message.
- No pause: cancel, then retry.
- No TikTok photo posts, Instagram image carousels, Spotify albums/playlists, Apple Music
  matching, or clip trimming.
- Spotify resolves to the top matching YouTube audio, not Spotify's DRM-protected stream.
- The queue is in-memory: killing the app process drops queued jobs. Finished files and
  history are safe.

## License

The APK bundles [`youtubedl-android`](https://github.com/yausername/youtubedl-android)
0.18.1 (GPL-3.0), which includes yt-dlp, Python, FFmpeg and QuickJS. A distributed APK is
therefore GPL-3.0. Corresponding source: the `mobile/` directory at this tag plus the
upstream repositories linked above. The desktop app remains MIT.

## Checksums

`SHA256SUMS-android-1.0.0.txt` is attached to this release. Verify with:

```bash
sha256sum -c SHA256SUMS-android-1.0.0.txt
```

## Desktop is unaffected

This pre-release does not touch the desktop update feed: no `latest.yml` and no `v*` tag.
Desktop users stay on v1.0.0 and continue to receive desktop updates as usual.
