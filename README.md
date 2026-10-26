# Universal Downloader ⚡

Native Windows 11 Desktop Application & Web Downloader for YouTube (up to 4K), TikTok (No Watermark), Instagram Reels, Facebook, Twitter/X, and SoundCloud.

![Universal Downloader](https://img.shields.io/badge/Platform-Windows%2011-blue?logo=windows)
![Version](https://img.shields.io/badge/Release-v0.3.0-green)
![Electron](https://img.shields.io/badge/Electron-33.4.11-47848F?logo=electron)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688?logo=fastapi)
![Next.js](https://img.shields.io/badge/Next.js-14.2.35-black?logo=nextdotjs)

---

## 🌟 Key Features

* **Native Windows 11 Desktop Shell**: Built with Electron, runs completely offline from the desktop without opening separate terminal windows.
* **System Tray & Clipboard Watcher**: Minimizes to the Windows system tray and automatically detects copied media URLs from supported platforms.
* **Real-time Download Queue**: Download multiple links simultaneously (concurrency limited to 3) with live progress bars, speed, and status over Server-Sent Events (SSE).
* **Direct Stream Piping**: Streams single-stream MP4 files directly to the client without redundant disk caching.
* **Full HD / 4K & Audio Extraction**: Automatically handles Node.js runtime challenges with `yt-dlp` and merges video/audio with bundled FFmpeg.
* **Headless API for Streamers**: `POST /api/rio/quick-fetch` for automated background asset downloads directly to disk.

---

## 🚀 Quick Download (Windows 11)

Download the latest pre-packaged standalone release from the [`release/`](release/) directory:
* **Installer**: `Universal Downloader Setup 0.3.0.exe` (One-click desktop setup)
* **Portable**: `Universal Downloader-0.3.0-win.zip` (Extract & run `Universal Downloader.exe` directly)

> **No dependencies needed:** Everything (Python engine, FFmpeg, and UI) is completely bundled.

---

## 🛠️ Architecture & Tech Stack

```text
universal-downloader/
├── desktop/             # Electron Desktop Shell & System Tray Manager
├── backend/             # FastAPI + yt-dlp + FFmpeg Sidecar Engine
└── frontend/            # Next.js 14 + Tailwind CSS + TypeScript UI
```

* **Desktop Shell**: Electron 33.4.11 + System Tray + Single Instance Lock
* **Backend**: Python 3.11.9, FastAPI, Uvicorn, APScheduler, yt-dlp
* **Frontend**: Next.js 14.2.35 (Static Export / Dev Server), Tailwind CSS
* **Media Processing**: FFmpeg Essentials (bundled)

---

## 💻 Developer Guide

### 1. Requirements (For building from source)
* Windows 10/11
* Node.js v18+ (tested on v26)
* Python 3.11+
* FFmpeg in system PATH

### 2. Development Setup

#### Backend:
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000 --host 127.0.0.1
```

#### Frontend:
```powershell
cd frontend
npm install
npm run dev
```

#### Desktop Shell:
```powershell
cd desktop
npm install
npm start
```

### 3. Build Standalone Release
```powershell
# 1. Export static frontend
cd frontend
npm run build

# 2. Package standalone desktop application
cd ..\desktop
npm run dist
```
The output `.exe` and `.zip` will be generated in `desktop/dist-release/`.

---

## 📄 License

Intended for personal use. Source code is licensed under the [MIT License](LICENSE).
Third-party software notices and licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
