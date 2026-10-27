# Extractor update path (Phase 2, step 2.F) — verification

Status: **verified, no code changed.** This document is the only artifact of task 2.F.
Scope was verification only: `backend/app/services/extractor_update.py` was read, not modified.

- Branch: `phase-2-v0.8.0`, HEAD `2defe64` plus uncommitted edits from sibling 2.x tasks
  (`backend/app/main.py`, `frontend/src/components/SettingsView.tsx`, `frontend/src/lib/api.ts`).
  Line numbers for those three files move; backend `services/` files are clean at HEAD.
- Verified on Windows 11, 2026-10-27, against the dev venv (`backend/.venv`, Python 3.11.17).

The implementation already exists and works. Task 2.F is therefore documentation, not a new
updater (this matches `docs/dev/extractor-architecture.md:25-29`).

---

## 1. Where it installs, what it compares, where it fetches from

| Fact | Where |
| --- | --- |
| User install root: `%LOCALAPPDATA%\UniversalDownloader\bin` | `services/extractor.py:18-20` (`USER_EXTRACTOR_DIR`) |
| Package lands as `<root>\yt_dlp\` (whole package, not a `.whl`) | `services/extractor_update.py:96-109` |
| Active version = `yt_dlp.version.__version__` of the **loaded module** | `extractor_update.py:25-26` |
| On-disk user version = regex on `<root>\yt_dlp\version.py` | `extractor_update.py:29-36` |
| Version compare = digit tuples, e.g. `2026.10.26` → `(2026, 10, 26)` | `extractor_update.py:21-22`, used at `:122` |
| Source of truth: PyPI JSON `https://pypi.org/pypi/yt-dlp/json` | `extractor_update.py:15`, fetched at `:51-55` |
| Download: first `bdist_wheel` in `urls` whose filename starts `yt_dlp-` | `extractor_update.py:130-139` |
| No-op when latest ≤ active | `extractor_update.py:122-128` |
| Download caps: 40 MB streamed, 150 MB uncompressed, 5000 members | `extractor_update.py:16-18`, `:143-153`, `:64-68` |
| Fallback to bundled copy is an import hook, installed **only** if `<root>\yt_dlp\__init__.py` exists | `extractor.py:22-35` |
| Bundled pin for the installer build | `backend/requirements.txt:3` (`yt-dlp>=2026.8.19`) |

### Comparison semantics (important)

`_version_key` strips every non-digit run and compares tuples. `2026.08.19` and `2026.8.19` both
map to `(2026, 8, 19)`; `2026.10.26 > 2026.8.19` (covered by the test in §3). Strings without
digits map to `(0,)`. Nightly-style four-part versions (`2026.10.26.123456`) compare correctly
against three-part ones because tuples of unequal length compare element-wise first.

`before["active_version"]` is **not** the bundled version — it is whichever `yt_dlp` this process
imported. In the shipping app that is the user copy when present (`extractor.py:24-35` runs before
`import yt_dlp` at `:37`), so:

- Fresh install, no user copy → active = bundled; `update_extractor` compares PyPI latest against
  the bundled version.
- After install, before restart → active = old, user = new, `restart_required: true`
  (`extractor_update.py:47`, `:156-164`). Clicking Update again re-downloads the same wheel
  (latest > active), which is wasteful but harmless.
- After restart → active = user = latest, `source: "user"`, `restart_required: false`; Update
  returns `"yt-dlp is already up to date"`.

The field name `_bundled_version` is misleading: it returns the *loaded* version. See gap 3.

### Install and fallback mechanics

`_install_wheel` (`extractor_update.py:58-111`):

1. Reject non-zip (`:59-62`); enforce member count and summed declared sizes (`:64-68`).
2. Create a staging dir **inside** the user dir (`tempfile.mkdtemp(..., dir=user_dir)`, `:72`) so
   the final rename is same-volume.
3. Copy only members under `yt_dlp/`; reject absolute paths, `..`, and targets outside staging
   (`:75-91`). Directory entries are recreated.
4. Require `staging/yt_dlp/__init__.py` (`:93-94`).
5. `yt_dlp` → `yt_dlp.backup` (`:100-101`), staging → `yt_dlp` (`:103`), restore backup on failure
   (`:104-107`), delete backup on success (`:108`), always delete staging (`:110-111`).

At the next process start, `extractor.py:24-35` inserts `_UserYtDlpFinder` at the front of
`sys.meta_path`, so `yt_dlp` and every `yt_dlp.*` resolve from the user dir even under PyInstaller.
If the user dir has no `yt_dlp/__init__.py` the finder is never installed and the bundled copy is
used — that is the "missing" fallback. There is no explicit "broken" fallback (gap 2).

## 2. Backend surface and what the UI does

| Fact | Where |
| --- | --- |
| `GET /api/system/extractor` → `get_extractor_status()` | `api/routes.py:488-490` |
| `POST /api/system/update-extractor` → `await update_extractor()` | `api/routes.py:493-496` |
| Error mapping: `ValueError`→400, `httpx.HTTPError`→502 "Could not reach PyPI: …", other→500 | `api/routes.py:497-502` |
| Status payload: `active_version`, `user_version`, `source`, `location`, `restart_required` | `extractor_update.py:39-48` |
| POST is behind the session-token middleware when `APP_SESSION_TOKEN` is set | `app/main.py:75-97` |
| Frontend client `getExtractorStatus` / `updateExtractor` (surfaces `detail` on error) | `frontend/src/lib/api.ts:534-554` |
| Settings loads status once on mount, ignores failures | `SettingsView.tsx:128-142` |
| "Update extractor" handler: disable → call → replace status → show `message` | `SettingsView.tsx:144-163` |
| Subtitle: `yt-dlp <active>[ (installed)]` + `· <user> ready after restart` | `SettingsView.tsx:209-217` |
| Row + button (`Updating…` while pending) and `role="status"` note | `SettingsView.tsx:499-514` |

The UI is a two-state button: it calls the POST, renders the server's `message` verbatim, and
refreshes the subtitle from the response. It does not poll, does not offer a restart, and does not
show download progress. On 400/500 the note shows the backend's `detail` string.

Observed on this machine (dev state, 2026-10-27):

```
{"active_version": "2026.10.21", "user_version": "2026.10.21",
 "source": "user", "location": "C:\\Users\\Dataria\\AppData\\Local\\UniversalDownloader\\bin",
 "restart_required": false}
```

PyPI reported `2026.10.26` with exactly one wheel (`yt_dlp-2026.10.26-py3-none-any.whl`), so the
button is currently a real one-version update, not a no-op. The same machine also reproduces the
"installed but not restarted" state when `extractor_update` is imported before `extractor` (§5).

## 3. What the tests actually verify

`backend/tests/test_extractor.py:49` imports `_version_key`; the only test that touches the
updater is:

| Test | Covers |
| --- | --- |
| `TestExtractor.test_version_key_orders_releases` (`tests/test_extractor.py:1044-1046`) | ordering `2026.10.26 > 2026.8.19`, and zero-padded equality `2026.08.19 == (2026, 8, 19)` |

Repo-wide grep for `extractor_update|update-extractor|get_extractor_status|update_extractor`
returns only `routes.py`, `tests/test_extractor.py:49` and the doc architecture file. So **untested**:
`get_extractor_status` (both branches), `_user_version` parsing, wheel selection, size/member caps,
every path-traversal check in `_install_wheel`, the backup/restore sequence, the no-op branch, the
40 MB stream cap, and both HTTP endpoints. There are no API-route tests (`backend/tests` has no
`test_api*.py`) and no frontend tests for the Settings row.

## 4. Test run

```
> cd backend
> .venv\Scripts\python.exe -m pytest tests/test_extractor.py -k "version_key" -q
.                                                                        [100%]
1 passed, 83 deselected in 0.72s
```

Whole module, for import health around the extractor:

```
> .venv\Scripts\python.exe -m pytest tests/test_extractor.py -q
....................................................             [ 61%]
................................                                 [100%]
84 passed, 28 subtests passed in 1.17s
```

The suite proves the version comparator and that `extractor.py` still imports with the user-copy
finder in place on this machine. It proves nothing about install correctness.

## 5. Manual verification procedure (human, ~2 minutes)

1. Note the current state (no token needed for GET):
   ```powershell
   Invoke-RestMethod http://127.0.0.1:<backend-port>/api/system/extractor
   ```
   or read it in Settings → *Extractor engine*.
2. In Settings, click **Update** next to *Extractor engine*. Expect the button to read
   `Updating…` briefly, then the note:
   - `yt-dlp updated. Restart the app to use the new extractor.` and subtitle
     `yt-dlp <old> · <new> ready after restart`.
   - `yt-dlp is already up to date` if there is no newer PyPI release.
   - on failure: `Could not reach PyPI: …` (502) or `Extractor update failed: …` (500).
3. Confirm on disk without restarting:
   ```powershell
   Get-Content "$env:LOCALAPPDATA\UniversalDownloader\bin\yt_dlp\version.py" | Select-String __version__
   ```
   It must show the new version, and `<root>\yt_dlp.backup` must be gone.
4. Restart the app (quit fully; the extractor has no restart button). Then re-check status. Expect
   `active_version == user_version == <new>` and `source: "user"`, subtitle
   `yt-dlp <new> (installed)`, `restart_required: false`. That is the proof the user copy is
   actually the active one — `location` being populated means nothing on its own.
5. Click **Update** again: expect `yt-dlp is already up to date` (no download).
6. Roll back by deleting the user copy and restarting:
   ```powershell
   Remove-Item -Recurse -Force "$env:LOCALAPPDATA\UniversalDownloader\bin\yt_dlp"
   Remove-Item -Recurse -Force "$env:LOCALAPPDATA\UniversalDownloader\bin\yt_dlp.backup" -ErrorAction SilentlyContinue
   ```
   After restart, status shows the bundled version and `source: "bundled"`. There is no in-app
   rollback; the backup directory is deleted on success (`extractor_update.py:108`).

Dev note: importing `app.services.extractor_update` before `app.services.extractor` makes status
report the bundled version even when a user copy exists. The shipping order is safe because
`routes.py:23` imports `extractor` before `:38` imports `extractor_update` — see gap 3.

## 6. Gaps (not fixed)

Ordered by what would hurt first. None of these block the Phase 2 goal.

1. **No integrity check on the downloaded wheel.** PyPI JSON exposes `digests.sha256` for each
   file (confirmed present for the current release) but the code only reads `url`
   (`extractor_update.py:130-139`). It also never confirms the wheel filename matches
   `info.version`. Trust rests on HTTPS, the 40 MB cap, and path sanitising (`:79-85`). A
   compromised account, mirror, or TLS-terminating proxy ships code that executes inside the app
   at next start, with the user's cookies and filesystem.
2. **A bad wheel can brick startup with no in-app recovery.** The install asserts only that
   `yt_dlp/__init__.py` exists (`:93-94`) — it never imports the staged package or checks its
   version. Because the finder shadows the bundled copy at next start (`extractor.py:24-35`), a
   syntax/import error in the user copy means the backend does not start, so Settings (and the
   fix) is unreachable; recovery requires Explorer/PowerShell. A *partial* user copy is worse in a
   quieter way: `PathFinder.find_spec` returns `None` for a missing submodule, so that submodule
   silently resolves from the bundled copy (mixed versions) instead of failing loudly.
3. **Correctness depends on import order.** `extractor_update.py:11` imports `yt_dlp` *before*
   `:13` imports `extractor` (which installs the finder). Anything that imports
   `extractor_update` first gets the bundled version in `_bundled_version()` while `_user_version()`
   reads the user copy, so status can say `restart_required: true` and the update decision compares
   against the wrong version. Reproducible:
   `python -c "from app.services.extractor_update import get_extractor_status; print(get_extractor_status())"`
   reported `active_version 2026.08.19 / user 2026.10.21 / restart_required true`, while importing
   `app.services.extractor` first reported `2026.10.21 / source user / false`. Today only
   `routes.py` imports it, so the UI is correct; a new entry point (CLI, worker, test) would not be.
4. **No total deadline, no progress, no cancel.** There is a 30 s connect/read timeout for the JSON
   (`:52`) and 60 s per-read on the stream (`:143`), so a stalled download is bounded in bytes
   (40 MB) but not in wall time; a slow-drip server can hold the request for a long time. The UI
   only says `Updating…` (`SettingsView.tsx:506`) with no progress bar or cancel.
5. **No concurrency guard.** Nothing locks `_install_wheel` (`:58-111`). Two POSTs (two windows,
   or curl) can interleave the backup/staging renames (`:96-108`) and leave `yt_dlp` missing or
   half-written. An update is also allowed while downloads are running; on Windows a lazy import
   in a queued job can make `os.replace` fail, which surfaces as a 500 after the target was
   already moved to `yt_dlp.backup` (rollback at `:104-107` usually recovers, but the running
   process is left inconsistent).
6. **No startup recovery for an interrupted install.** If the process dies between `:101` and
   `:103`, the next start silently uses the bundled copy and leaves `yt_dlp.backup` orphaned; the
   next successful update deletes it (`:98-99`, `:108`), discarding the last good copy. And if the
   user copy exists at the latest version but is broken, Update returns
   `"yt-dlp is already up to date"` (`:122-128`) and never re-downloads — only manual deletion
   recovers.
7. **Zip-bomb guard trusts header metadata.** `:67-68` sums `member.file_size` from the archive
   directory; actual decompressed bytes are not counted, so a wheel with lying headers can exceed
   the 150 MB budget (still bounded by the 40 MB download cap and the 5000-member limit). Low
   severity while PyPI is the only source.
8. **A stale user copy permanently shadows a newer bundled copy.** The finder does not compare
   versions (`extractor.py:24-35`), and `active_version` is the loaded user version, so status
   cannot reveal that the bundled copy is newer. Harmless while the bundled pin is only a floor
   (`requirements.txt:3`), but it means "bundled fallback" is not a version-aware fallback.
9. **Restart UX.** The only restart affordance in the app is the installer relaunch
   (`desktop/main.js:629-633`); the extractor path just tells the user to restart. Status is read
   once on Settings mount, so a second window keeps showing `ready after restart` after the
   restart happened elsewhere.

## Verdict

**Yes — sufficient for the Phase 2 goal ("fix extractors without shipping a 264 MB installer").**
The runtime path is real: PyPI JSON → single ≤40 MB wheel → sanitised extraction → same-volume swap
into `%LOCALAPPDATA%` → import hook prefers it on next start → delete the directory to roll back.
No rebuild, no installer, no 264 MB download; the whole update is a single wheel
(3.0 MB for `2026.10.26`, measured) capped at 40 MB.

**Smallest remaining gap:** verify the wheel before committing it — compare the bytes against
`digests.sha256` from the same PyPI response, and import `yt_dlp.version` from the staging dir (or
at least parse the staged `version.py`) and confirm it equals `latest`, keeping `yt_dlp.backup`
until the new copy passes. That converts gaps 1 and 2 from "silently trust the download" into a
checkable install and is roughly 15 lines in `extractor_update.py`. It needs approval and was not
done in 2.F.
