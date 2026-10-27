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

## v0.7.1 — extractor issues reported, not fixed

6. **Spotify cover art is always missing.** `_spotify_cover` (`backend/app/services/extractor.py:968`)
   reads `coverArt`, but live embed entities carry artwork under `visualIdentity.image`.
   Verified live: `_resolve_spotify()` returns `thumbnail: None` for a real track, so
   embedded cover art is never written.
7. **TikTok `embed/v2` fixture not captured.** TikTok answered 503 "overload-protect
   triggered" during capture, so that shape is still only covered by synthetic tests.
