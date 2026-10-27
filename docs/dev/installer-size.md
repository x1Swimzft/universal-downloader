# Installer size analysis (v1.0.0)

Report only. Nothing was removed, stripped or repackaged for this release.

## Measured (v0.9.0 build, same pipeline as 1.0.0)

| Component | Size |
|---|---|
| `Universal Downloader.exe` (Electron runtime) | 180.1 MB |
| `resources/app.asar` | **266.3 MB** |
| `resources/bin/ffmpeg.exe` | 100.9 MB |
| `resources/bin/ffprobe.exe` | 100.7 MB |
| `resources/backend-engine/` (PyInstaller) | 60.4 MB |
| `resources/frontend-out/` | 1.3 MB |
| Unpacked app total | ~798 MB |
| Installer (`Setup.exe`) | ~244 MB |
| Portable ZIP | ~311 MB |

## The dominant problem: resources are shipped twice

`app.asar` is 266 MB even though the only JavaScript dependencies are ~2 MB
(`electron-updater`, `js-yaml`, `argparse`, `builder-util-runtime`, …). Listing the
archive shows why:

```
\backend-engine   2660 files
\frontend-out       35 files
\bin                 5 files
\assets              4 files
\certs               2 files
\updater.test.js     1 file
```

`electron-builder` packs the whole `desktop/` directory into the asar, and
`build.extraResources` then copies `backend-engine`, `bin`, `frontend-out` and `assets`
to `resources/` as well. The installer therefore carries a second copy of the engine,
FFmpeg and the UI, plus the test file and the `certs/` folder (empty today, but it is
where signing material would live).

## Recommendations (not done in 1.0.0)

1. Add a `build.files` allowlist so the asar contains only runtime code:
   `main.js`, `preload.js`, `updater.js`, `assets/icon.ico`, `package.json`,
   `node_modules/**`. Expected saving: roughly 250 MB unpacked, and a materially
   smaller installer.
2. Keep `certs/`, `*.test.js`, `dist-release/` and build scratch out of the package by
   construction, not by convention.
3. `ffmpeg` + `ffprobe` are 201 MB of the remaining payload. `ffprobe` is only used for
   duration/metadata; a reduced build or lazy download would help, but that changes
   runtime behaviour and needs a full test + install pass.
4. Verify the win after (1) with: unpacked size, installer size, cold start, one video
   download, one audio download, and the generated `latest.yml` unchanged.

Any of these is a packaging change and was deliberately left out of 1.0.0.
