# Auto-update test: 0.7.0 → 0.7.1

Status of a purely local 0.7.0 → 0.7.1 update test as of 2026-10-27:

- **Update check against a local feed: feasible today.** Verified against a copy of the
  packaged 0.7.0 build, with no repo/build-config change (section 3).
- **Download + quit-and-install + relaunch on 0.7.1: not feasible today.** The app has no
  download/install code at all (section 4), so no feed can make the installed copy upgrade
  itself. That needs a small app-code change (approval required).

Nothing here changes source, build config, or the installed app on this machine. All local
tests run against a **copy** of `desktop/dist-release/win-unpacked`.

---

## 1. Current updater facts

| Fact | Where |
| --- | --- |
| `electron-updater` dependency `^6.3.9` (6.8.11 installed) | `desktop/package.json:13` |
| Required lazily; failure leaves `autoUpdater = null` | `desktop/main.js:38-43` |
| Startup check: `initAutoUpdater()` once, at the end of `app.whenReady` | `desktop/main.js:330-335`, called at `desktop/main.js:791` |
| Startup check bails unless `autoUpdater && app.isPackaged` | `desktop/main.js:331` |
| `autoDownload = false` (both startup and manual path) | `desktop/main.js:332`, `desktop/main.js:571` |
| Updater errors swallowed silently (`on("error", () => {})`) | `desktop/main.js:333` |
| Startup result discarded: no listeners, no notification | `desktop/main.js:334` |
| Manual check IPC `app:check-update` | `desktop/main.js:560-612` |
| Manual check also gated on `app.isPackaged` → returns `unavailable` in dev | `desktop/main.js:562-568` |
| 15 s timeout on the manual check | `desktop/main.js:574-579` |
| "update available" = `updateInfo.version !== app.getVersion()` | `desktop/main.js:581-588` |
| Message text hardcoded "…available on GitHub Releases." | `desktop/main.js:586` |
| 404 / `latest.yml` / "no published" mapped to `up-to-date` | `desktop/main.js:596-603` |
| All other errors → `Could not check for updates. Try again later.` | `desktop/main.js:604-608` |
| Renderer bridge `checkForUpdate()` | `desktop/preload.js:12` |
| UI: Settings → "App updates" button + message | `frontend/src/components/SettingsView.tsx:269-285` |
| Provider: `github`, owner `x1Swimzft`, repo `universal-downloader`, `releaseType: release` | `desktop/package.json:48-55` |
| Packaged builds read `resources/app-update.yml` | `electron-updater/out/AppUpdater.js:157`, `:483-486` |
| Generated config in the 0.7.0 build: `owner/repo/provider: github/releaseType: release/updaterCacheDirName: universal-downloader-updater` | `desktop/dist-release/win-unpacked/resources/app-update.yml` |
| Channel: app code never sets one → default `latest` → feed file is `latest.yml` | `AppUpdater.js:173`, `providers/GenericProvider.js:15-16` |
| `allowPrerelease = false`, `allowDowngrade = false` (no channel override) | `AppUpdater.js:125`, `:138` |
| No `downloadUpdate`, `quitAndInstall`, or `update-downloaded` handler anywhere in the repo | repo-wide grep, 0 matches |
| Version comes from `app.getVersion()` = `desktop/package.json:4` → currently **0.7.0** | `desktop/main.js:561`, `desktop/package.json:4` |

### Version strings you must not trust

Three UI strings are hardcoded, so an upgraded install still displays "v0.7.0":

- `frontend/src/components/Sidebar.tsx:19`
- `frontend/src/app/page.tsx:671`
- `frontend/src/components/SettingsView.tsx:272`

Use the executable's version info instead (see 3.6 / 4.4).

### Installer + local paths

- NSIS: `oneClick: true`, `perMachine: false`, `allowToChangeInstallationDirectory: false`
  (`desktop/package.json:38-47`). One-click means no wizard, no directory choice, and the
  installer **overwrites an existing install in place**.
- Install dir = `%LOCALAPPDATA%\Programs\universal-downloader`: with `oneClick && !perMachine`
  electron-builder uses the sanitized package name, not `productName`
  (`app-builder-lib/out/targets/nsis/NsisTarget.js:166`, `out/targets/targetUtil.js:40-41`).
- Settings: `%APPDATA%\Universal Downloader\settings.json` (`app.setName` at
  `desktop/main.js:23`, path built at `desktop/main.js:92`).
- Update cache: `%LOCALAPPDATA%\universal-downloader-updater` (`updaterCacheDirName` in
  `app-update.yml`). Clear it between attempts.
- `minimizeToTray` defaults to `true` (`desktop/main.js:98`), so closing the window only hides
  it. Quit via tray → **Quit Completely** (`desktop/main.js:545-549`) or Task Manager. The app
  holds a single-instance lock (`desktop/main.js:337-348`); a second launch exits silently.
- Build output dir is `desktop/dist-release` (`desktop/package.json:22-24`); published copies
  live in `release/`.

---

## 2. Artifacts a feed needs

| File | Needed for | Source |
| --- | --- | --- |
| `latest.yml` | the update **check** (only file fetched) | `desktop/dist-release/latest.yml`, copied to `release/latest.yml` |
| `Universal Downloader Setup <ver>.exe` | download + install | `desktop/dist-release/`, copied to `release/` |
| `…Setup <ver>.exe.blockmap` | differential download only | same dirs |
| `Universal Downloader-<ver>-win.zip` | portable target only; not part of the NSIS update | same dirs |

Current `release/latest.yml` (369 bytes):

```yaml
version: 0.7.0
files:
  - url: Universal-Downloader-Setup-0.7.0.exe
    sha512: F7Dadb9aqH0lcA8JBStDN6S2rcySCzt1/a0O6XEdTD8FqApiMVC+bcnPAqz15TMG4uzVxKrJCx78hkudZIcF1w==
    size: 264420537
path: Universal-Downloader-Setup-0.7.0.exe
sha512: F7Dadb9aqH0lcA8JBStDN6S2rcySCzt1/a0O6XEdTD8FqApiMVC+bcnPAqz15TMG4uzVxKrJCx78hkudZIcF1w==
releaseDate: '2026-10-26T16:33:01.865Z'
```

Two things to know:

1. **Name mismatch.** The manifest says `Universal-Downloader-Setup-0.7.0.exe`; the file on disk
   is `Universal Downloader Setup 0.7.0.exe` (spaces). A dumb static server 404s on the binary.
   Irrelevant for a check-only test, fatal for any download test — rename the copy or rewrite
   `url`/`path` to the real filename.
2. **No 0.7.1 artifacts exist yet.** `release/` tops out at 0.7.0 (`latest.yml`, installer,
   blockmap, zip), so a genuine 0.7.1 feed requires a build (section 4).

---

## 3. Local check-path test (works today)

This exercises the real packaged binary, `electron-updater`, `latest.yml` parsing, and the
Settings UI message. No repo change; the generated `app-update.yml` is rewritten **in a copy**.

1. Copy the packaged build somewhere disposable:

   ```powershell
   $t = "$env:TEMP\ud-auto-update-test"
   robocopy "E:\Project\universal-downloader\desktop\dist-release\win-unpacked" "$t\app" /E
   ```

   Never point this at `%LOCALAPPDATA%\Programs\universal-downloader`.

2. Replace `$t\app\resources\app-update.yml` with a generic provider:

   ```yaml
   provider: generic
   url: http://127.0.0.1:8099/
   channel: latest
   updaterCacheDirName: universal-downloader-updater
   useMultipleRangeRequest: false
   ```

   `useMultipleRangeRequest: false` because the helper server only answers single ranges.

3. Build the feed. Only `latest.yml` is read during a check, but keep it self-consistent:

   ```powershell
   New-Item -ItemType Directory "$t\feed"
   Copy-Item "E:\Project\universal-downloader\release\latest.yml" "$t\feed\latest.yml"
   (Get-Content "$t\feed\latest.yml" -Raw) -replace "version: 0.7.0", "version: 0.7.1" |
     Set-Content "$t\feed\latest.yml"
   Copy-Item "E:\Project\universal-downloader\release\Universal Downloader Setup 0.7.0.exe*" "$t\feed\"
   ```

4. Serve it and launch the copy:

   ```powershell
   node scripts/serve-update-feed.mjs "$t\feed" 8099
   & "$t\app\Universal Downloader.exe"
   ```

5. Observe. Within a few seconds the server log shows the startup check:

   ```
   GET /latest.yml?noCache=...
   ```

   That request alone proves the packaged app reached the feed. The startup check discards its
   result (`desktop/main.js:334`), so it shows no UI message — a quiet app is not a failure.

   Then Settings → App updates → **Check for updates**.

6. Read the result. Expected pass:

   ```
   Version 0.7.1 is available on GitHub Releases.
   ```

   ("GitHub Releases" is hardcoded at `desktop/main.js:586`; it is wrong for a local feed and is
   not a failure.)

| Observation | Meaning |
| --- | --- |
| Server log `GET /latest.yml?noCache=…` at launch | packaged build, feed reachable, check fires — pass |
| `Version 0.7.1 is available …` | check path + version compare — pass |
| `You are on the latest version.` | feed version ≤ running version (edit the served copy, not the repo one) |
| `No published release found yet…` | `latest.yml` 404 — wrong directory or filename (`desktop/main.js:596-603`) |
| `Could not check for updates. Try again later.` | connection refused, >15 s, or unparsable yml (`:604-608`) |
| `Update checks are available in the installed desktop app.` | not a packaged build (`npm start` / `electron .`) — gate at `:562` |

Verified on this machine (0.7.0 build copied to `%TEMP%`, feed version 0.7.1, server on 8099):

```
serving C:\Users\...\ud-auto-update-test\feed at http://127.0.0.1:8099/
GET /latest.yml?noCache=1k5tikflp

currentVersion 0.7.0
update-available 0.7.1
checkForUpdates resolved 0.7.1
```

Clean up: quit the copy from the tray, stop the server, delete `$t`.

---

## 4. Full 0.7.0 → 0.7.1 install test — blocked

> **Update 2026-10-27 (v0.7.1):** blocker 1 is fixed — `desktop/main.js` now handles
> `app:install-update` (`downloadUpdate()` + `quitAndInstall()`) and Settings shows
> **Install update** when a version is available. Verified end-to-end on the packaged 0.7.1
> build against a local feed advertising 0.7.2: `latest.yml` → `.blockmap` → installer were
> fetched, the app quit, the installer ran, the app relaunched and the updater cache was
> cleaned.
>
> The 0.7.0 → 0.7.1 leg still cannot be automatic: 0.7.0 shipped without that IPC bridge, so
> its Settings can only report the new version. 0.7.0 users must install 0.7.1 by hand once;
> every later version can update itself.

These are real blockers, not polish:

1. **No download/install path in the app.** `autoDownload = false` and nothing ever calls
   `downloadUpdate()` or `quitAndInstall()`; no `update-available`/`update-downloaded` handlers
   exist. The app can only report that a version exists. A 0.7.1 feed cannot make it upgrade
   itself. *Smallest unblock:* in the `app:check-update` "available" branch (or a new
   `update-downloaded` handler), `await autoUpdater.downloadUpdate()` then
   `autoUpdater.quitAndInstall()`, plus fix the misleading message at `desktop/main.js:586`.
   **Needs user approval — app source.**
2. **Provider is baked into the build.** `resources/app-update.yml` is generated from
   `build.publish` (GitHub, `desktop/package.json:48-55`). Two ways to point an installed 0.7.0
   at a local feed:
   - *No rebuild (recommended for a test):* rewrite
     `%LOCALAPPDATA%\Programs\universal-downloader\resources\app-update.yml` to the generic
     config from 3.2 and restore it afterwards. Only touches the installed copy.
   - *Rebuild with `publish: generic`.* Would work but changes release config and the real feed;
     **needs approval and is not recommended.**
3. **No 0.7.1 build exists.** Needs `desktop/package.json:4` bumped to `0.7.1` plus
   `npm run dist` in `desktop/`. That is a version/build-config change (**approval**), and the
   three hardcoded UI version strings (section 1) should move with it so the app does not lie.
4. **The updater overwrites the only install.** `oneClick` + fixed install dir replaces
   `%LOCALAPPDATA%\Programs\universal-downloader` content. Before any real install test:
   - back up that folder, and
   - back up `%APPDATA%\Universal Downloader\settings.json`,
   - or use a **clean VM / throwaway Windows profile**. Prefer the VM: it also verifies the
     no-admin, per-user install path.

### Procedure once 1–3 are unblocked

1. Back up (4.4) or snapshot the VM. Close every running instance (tray → Quit Completely).
2. Build 0.7.1, copy `latest.yml`, `Universal Downloader Setup 0.7.1.exe` and its `.blockmap`
   into the feed, and make `url`/`path` match the real filename.
3. Install 0.7.0 from `release\Universal Downloader Setup 0.7.0.exe` (no prompts, no admin).
4. Point the installed `resources\app-update.yml` at the feed (4.2, first option), clear
   `%LOCALAPPDATA%\universal-downloader-updater`, serve the feed, launch the app.
5. Settings → App updates → Check for updates.

| Step | Pass looks like | Fail looks like |
| --- | --- | --- |
| check | `Version 0.7.1 is available…`; server logs `GET /latest.yml` | up-to-date / could-not-check (see 3.6) |
| download | server logs the installer and `.blockmap` (Range requests); files appear in `%LOCALAPPDATA%\universal-downloader-updater`; app still responsive | no installer request, or stalls/timeout, or app freezes |
| install | app quits on its own (or offers restart), NSIS runs without UI, no admin prompt, no SmartScreen block | app keeps running, or error dialog, or install dir not replaced |
| relaunch | app starts; executable version is 0.7.1 (below); `%APPDATA%\Universal Downloader\settings.json` still has the pre-update settings | app fails to start; version still 0.7.0; settings reset |

Verify the version from the file system, not the UI:

```powershell
(Get-Item "$env:LOCALAPPDATA\Programs\universal-downloader\Universal Downloader.exe").VersionInfo.ProductVersion
```

0.7.0 currently returns `0.7.0.0`. After a successful update it must return `0.7.1.0`.

Manual fallback while 4.1 is unimplemented: run the 0.7.1 installer by hand on the 0.7.0
install and confirm it upgrades in place (settings preserved, version string 0.7.1.0). That
tests the NSIS overwrite/settings story but **not** `electron-updater`'s download and
quit-and-install handoff.

---

## 5. Helper script

`scripts/serve-update-feed.mjs` — dependency-free static server for a feed directory.

```powershell
node scripts/serve-update-feed.mjs [dir=release] [port=8099]
```

- Binds `127.0.0.1`, prints the URL, logs every request (that log is the observation probe).
- Content types: `.yml` → `text/yaml`, `.exe`/`.blockmap` → `application/octet-stream`,
  `.zip` → `application/zip`.
- Single byte-range support (`206`) so a future download test can resume/diff; no multipart
  ranges, hence `useMultipleRangeRequest: false` in `app-update.yml`.
- Rejects paths outside the feed directory.

Verified (serving `release/` on port 8099, then stopped):

```
GET /latest.yml                      200  content-type: text/yaml, content-length: 369
GET /Universal%20Downloader…exe -r 0-1023   206  bytes=1024
HEAD …exe.blockmap                   200
GET /nope.yml                        404
GET /../package.json                 404 (no leak)
```
