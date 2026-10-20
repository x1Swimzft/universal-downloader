@echo off
title Universal Downloader Launcher
echo Starting Universal Downloader...

start "Backend API (Port 8000)" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --port 8000 --host 127.0.0.1 --reload"
start "Frontend UI (Port 3000)" cmd /k "cd /d %~dp0frontend && npm run dev"

echo Servers starting!
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
timeout /t 3 >nul
start http://localhost:3000
exit
