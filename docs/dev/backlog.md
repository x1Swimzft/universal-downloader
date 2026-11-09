# Backlog

Known gaps accepted knowingly. Not release blockers unless stated.

## v0.7.1 — accepted, not fixed

These came out of the updater review. The install path works (verified against a local
feed), but each of these is still open.

1. **No download timeout.** `app:check-update` races 15 s; `app:install-update` has no
   timeout, so a stalled download leaves the Settings button on "Downloading…" until the
   user restarts the app. Upgrade when a stuck-update report appears or before 1.0.
2. **Install does not wait for active downloads.** Clicking **Install update** quits
   immediately; in-flight queue jobs are interrupted. Needs a queue-aware guard (or an
   explicit confirmation listing active jobs) before the updater is used by many users.
3. **Renderer may see a rejection on quit.** `quitAndInstall()` fires before the IPC reply,
   so the window can briefly surface "Could not download the update" as the app exits.
   Cosmetic; fix by replying before calling `quitAndInstall`.
4. **No Electron main-process test harness.** `app:check-update` and `app:install-update`
   are covered only by manual/CDP runs, not by automated tests. Adding a harness (spectron
   successor or a headless Electron runner) is prerequisite for trusting further updater
   changes.
5. **First real auto-update still unproven.** The 0.7.1 → 0.7.2 path was exercised with a
   local feed that advertised 0.7.2 while serving the 0.7.1 installer, so download, install
   and relaunch are proven but the version bump is not. Validate when 0.7.2 ships from an
   installed 0.7.1.

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

- **Stale ackend-engine.exe can ship unnoticed.** `desktop/backend-engine` is a prebuilt
  PyInstaller folder and `electron-builder` copies it verbatim; nothing in
  `verify-release` compares it to the Python source, so the first 0.8.0 package shipped a
  backend that predated Phase 2 (the new endpoints 404'd). Rebuild with
  `pyinstaller backend-engine.spec` and copy `backend/dist/backend-engine` into
  `desktop/backend-engine` before every package. Upgrade: give the backend an
  `APP_VERSION` and make `verify-release` compare it, or hash the engine in the guard.

## Update channels - deferred to v1.1

Phase 4.C kept the stable feed untouched: no uild.publish.channel change and no
artifact naming change for 1.0.0, so `latest.yml` stays byte-compatible for
0.9.0 -> 1.0.0. A beta channel (`beta.yml` only when the version contains `-beta`)
needs its own electron-builder config change and an end-to-end feed test; doing it in the
same release as the 1.0.0 updater bump would put the stable path at risk for no user
benefit. Revisit in v1.1 with the local harness in `docs/dev/auto-update-test.md`.
