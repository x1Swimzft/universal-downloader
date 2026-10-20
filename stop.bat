@echo off
setlocal enabledelayedexpansion

echo Stopping Universal Downloader instances...

for /L %%p in (8000,1,8010) do (
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr /r /c:":%%p .*LISTENING"') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)

for /L %%p in (3000,1,3010) do (
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr /r /c:":%%p .*LISTENING"') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)

taskkill /F /IM electron.exe >nul 2>&1

echo Stopped all Universal Downloader instances.
