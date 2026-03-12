@echo off
title VoiceScribe
cd /d "%~dp0"

:: Clear ELECTRON_RUN_AS_NODE if set
set ELECTRON_RUN_AS_NODE=

echo ============================================
echo    VoiceScribe
echo ============================================
echo.

:: Check that dist exists
if not exist "frontend\dist\index.html" (
    echo [ERROR] Frontend not built. Run: cd frontend ^&^& npx vite build
    pause
    exit /b 1
)

:: Check electron
if not exist "frontend\node_modules\electron\dist\electron.exe" (
    echo [ERROR] Electron not installed. Run: cd frontend ^&^& npm install
    pause
    exit /b 1
)

:: Check python venv
if not exist "backend\.venv\Scripts\python.exe" (
    echo [ERROR] Python venv not found
    pause
    exit /b 1
)

echo Starting VoiceScribe...
echo.

:: Launch Electron directly
cd /d "%~dp0frontend"
start "" "node_modules\electron\dist\electron.exe" "."

echo VoiceScribe started! This window will close in 3 seconds.
timeout /t 3 /nobreak >nul
