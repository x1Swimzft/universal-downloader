# Third-Party Notices

Universal Downloader's own code is MIT-licensed (see `LICENSE`). The installer
and portable zip also contain the third-party software below, which remains
under its own license. This list was drafted by hand: **regenerate the full
dependency lists before each release** (see "Release checklist").

## 1. FFmpeg / ffprobe — GPL v3

- Files: `ffmpeg.exe`, `ffprobe.exe` (in `bin/` of the app)
- Build: `ffmpeg version 2026-10-01-git-0b01ed76aa-essentials_build-www.gyan.dev`
  (Windows build by Gyan Doshi, configured with `--enable-gpl --enable-version3`,
  includes libx264, libx265, libvidstab)
- License: GNU General Public License v3 — https://www.gnu.org/licenses/gpl-3.0.html
- Copyright: the FFmpeg developers and the authors of the linked libraries
- Project / source code: https://ffmpeg.org/download.html and
  https://github.com/FFmpeg/FFmpeg (commit `0b01ed76aa`)
- Build provider: https://www.gyan.dev/ffmpeg/builds/
- The full license text and README from the build archive are shipped next to
  the executables in `bin/ffmpeg-LICENSE.txt` and `bin/ffmpeg-README.txt`.

Universal Downloader runs ffmpeg as a separate program (it does not link to
it). The GPL applies to the ffmpeg binaries and does not change the license of
Universal Downloader's own code. You may replace the bundled ffmpeg with any
other build by overwriting these files.

Corresponding source: the source for the exact build above is available at the
FFmpeg repository link and commit listed here. Libraries compiled into the
build (x264, x265, etc.) are listed in the build's README and are available
from their upstream projects.

## 2. Application components

| Component | Used for | License |
|---|---|---|
| yt-dlp | Media extraction (inside the backend engine) | The Unlicense (https://github.com/yt-dlp/yt-dlp) |
| Electron | Desktop shell | MIT (https://github.com/electron/electron). Chromium and other notices ship in `LICENSES.chromium.html`; do not remove it. |
| Python 3.11 | Backend runtime (frozen) | PSF License |
| PyInstaller | Freezing the backend | GPL-2.0 with a bootloader exception that allows distributing frozen apps under any license |
| FastAPI, Pydantic | Backend API | MIT |
| Starlette, Uvicorn, httpx | Backend server and HTTP client | BSD-3-Clause |
| APScheduler | Background task scheduling | MIT |
| certifi | SSL root certificates (shipped unmodified) | MPL-2.0 |
| Next.js, React, Tailwind CSS | User interface | MIT |
| Inter (variable) | UI typeface, bundled at `frontend/public/fonts/InterVariable.woff2` | SIL Open Font License 1.1 (https://github.com/rsms/inter) |

certifi is distributed in binary form without modification under the Mozilla Public License 2.0 (MPL-2.0). Source code is available at https://github.com/certifi/python-certifi.

Versions and the complete transitive list: see `third_party_python.md` and
`third_party_node.md` generated for each release.

## 3. Trademarks and disclaimer

YouTube, TikTok, Instagram, X, Facebook, SoundCloud and other names are
trademarks of their owners and are used only to describe supported sites.
Universal Downloader is not affiliated with or endorsed by them. You are
responsible for complying with the terms of the sites you download from and
with copyright law. The software is provided for personal use.

## 4. Release checklist (for the maintainer)

1. Python deps: `pip install pip-licenses`, then
   `pip-licenses --format=markdown --with-urls > third_party_python.md`
   (run in the backend venv that PyInstaller uses). Review every entry.
   Watch for **GPL/LGPL packages bundled inside `backend-engine.exe`**
   (for example `mutagen`, an optional yt-dlp dependency, is GPL-2.0+). If one
   is present, either exclude it in the PyInstaller spec or comply with its terms.
2. Node deps: `npx license-checker --production --markdown > third_party_node.md`
   (in `frontend/` and `desktop/`).
3. Copy `LICENSE` and the ffmpeg archive's `LICENSE`/`README.txt` into the
   installer, and keep `LICENSES.chromium.html` from Electron.
4. Keep the exact ffmpeg commit/build URL in this file in sync with the binary
   (`ffmpeg -version`). Consider uploading the matching source archive to the
   GitHub Release so the source stays available even if the build site changes.
