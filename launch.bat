@echo off
setlocal enabledelayedexpansion
title Universal Downloader Launcher
set "BASE_DIR=%~dp0"

if exist "%BASE_DIR%desktop\node_modules\electron\dist\electron.exe" (
    if "%1"=="" (
        echo Starting Universal Downloader Desktop App...
        start "" "%BASE_DIR%desktop\node_modules\electron\dist\electron.exe" "%BASE_DIR%desktop"
        exit
    )
)

echo [1/3] Finding free port for Backend (8000-8010)...
set BACKEND_PORT=8000
:find_backend_port
netstat -ano | findstr /r /c:":%BACKEND_PORT% .*LISTENING" >nul
if not errorlevel 1 (
    set /a BACKEND_PORT+=1
    if !BACKEND_PORT! leq 8010 goto find_backend_port
    echo Error: No free backend port found (8000-8010).
    pause
    exit /b 1
)

echo [2/3] Finding free port for Frontend (3000-3010)...
set FRONTEND_PORT=3000
:find_frontend_port
netstat -ano | findstr /r /c:":%FRONTEND_PORT% .*LISTENING" >nul
if not errorlevel 1 (
    set /a FRONTEND_PORT+=1
    if !FRONTEND_PORT! leq 3010 goto find_frontend_port
    echo Error: No free frontend port found (3000-3010).
    pause
    exit /b 1
)

set NEXT_PUBLIC_API_URL=http://127.0.0.1:!BACKEND_PORT!
echo Backend Port: !BACKEND_PORT! ^| Frontend Port: !FRONTEND_PORT!

echo [3/3] Launching Backend and Frontend...
start "Universal-Backend" /min cmd /c "cd /d %BASE_DIR%backend && .venv\Scripts\python -m uvicorn app.main:app --port !BACKEND_PORT! --host 127.0.0.1"
start "Universal-Frontend" /min cmd /c "cd /d %BASE_DIR%frontend && set PORT=!FRONTEND_PORT!&& set NEXT_PUBLIC_API_URL=!NEXT_PUBLIC_API_URL!&& npm run dev"

ping 127.0.0.1 -n 4 >nul
start http://localhost:!FRONTEND_PORT!

echo Done! Universal Downloader is ready on port !FRONTEND_PORT!.
ping 127.0.0.1 -n 2 >nul
exit
