# Backlog

Known gaps accepted knowingly. Not release blockers unless stated.

## v0.7.1 — updater review (status 2026-11-09)

1. ~~**No download timeout.**~~ **Resolved.** `desktop/updater.js` wraps `downloadUpdate()`
   in a 10-minute `withTimeout`; the timeout is unit-tested in `desktop/updater.test.js`.
2. **Install does not wait for active downloads.** Partially addressed: `installUpdate`
   accepts `countActiveJobs` and the dialog names the count, but `main.js` does not supply
   it yet, so the dialog says a running download will stop without listing it. Still open
   until the renderer or main process passes the queue count.
3. ~~**Renderer may see a rejection on quit.**~~ **Resolved.** `installUpdate` schedules
   `quitAndInstall` instead of calling it before the IPC reply; covered by the
   "replies before quitting" test.
4. ~~**No Electron main-process test harness.**~~ **Resolved for check/download/install
   logic.** `desktop/e2e/update.test.js` runs with `npm run test:e2e` against a local HTTP
   feed and covers available, no-update, 404, network, and download-failure paths. It
   injects the updater and never runs a real installer, so the NSIS install/relaunch still
   needs the manual packaged-app test in `docs/dev/auto-update-test.md`.
5. **First real auto-update still unproven.** The 0.7.1 → 0.7.2 test served the old
   installer, so the version bump is still unverified. The harness covers the logic, not
   the installed NSIS path; validate when the next stable ships.

## v0.7.1 — extractor issues (resolved)

6. ~~**Spotify cover art is always missing.**~~ **Resolved before v1.0.0.** `_spotify_cover`
   (`backend/app/services/adapters/music.py:177-204`) now falls back to `visualIdentity.image`
   when `coverArt` is absent. Covered by `backend/tests/test_adapter_music.py` (unit selection
   plus the captured embed fixture). No v1.1 code change.
7. ~~**TikTok `embed/v2` fixture not captured.**~~ **Resolved 2026-11-09.** Captured live from
   `https://www.tiktok.com/embed/v2/7508048429776407830` (HTTP 200, 30 images), trimmed to
   three in `backend/tests/fixtures/tiktok/photo_embed_v2.html` with signed query values
   redacted. Covered by `TestCapturedTikTokFixtures.test_embed_v2_html_fixture`; the embed
   payload carries no title/desc, so the parser falls back to `None`.

## 2.F extractor updater - resolved 2026-10-27

- Import order fixed: `services/ytdlp_loader.py` installs the user-copy finder before
  `yt_dlp` is imported, so a freshly installed wheel is active in the same process.
- Corrupt user copy can no longer brick startup: `yt_dlp/__init__.py` and `version.py`
  are compile-checked before activation; a broken copy is renamed to
  `yt_dlp.broken-<timestamp>` (with a `.reason.txt`) and the bundled copy is used.
  A copy that fails at import time is quarantined and the import retried.
- Wheel SHA-256 is now compared against PyPI's `digests.sha256` before install.

Still open (not blocking): no total download deadline or progress for the wheel, no cancel,
no recovery of `yt_dlp.backup` after a crash, and a stale user copy still shadows a newer
bundled copy by design.

## Release process - 2026-10-27

- ~~**Stale backend-engine.exe can ship unnoticed.**~~ **Resolved 2026-11-09.** The engine
  is still a prebuilt PyInstaller folder copied verbatim, but `backend/app/main.py` now
  exposes `APP_VERSION`; the release workflow writes
  `desktop/backend-engine/app-version.txt` while staging, and `verify-release` fails when
  the stamp is missing or differs from `APP_VERSION`/`latest.yml`. The mtime guard remains
  as a second check. (The first 0.8.0 package shipped a backend that predated Phase 2.)

## Update channels - deferred to v1.1

Phase 4.C kept the stable feed untouched: no uild.publish.channel change and no
artifact naming change for 1.0.0, so `latest.yml` stays byte-compatible for
0.9.0 -> 1.0.0. A beta channel (`beta.yml` only when the version contains `-beta`)
needs its own electron-builder config change and an end-to-end feed test; doing it in the
same release as the 1.0.0 updater bump would put the stable path at risk for no user
benefit. Revisit in v1.1 with the local harness in `docs/dev/auto-update-test.md`.
