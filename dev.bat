@echo off
setlocal

echo ============================================
echo   VoiceScribe Dev Mode
echo ============================================
echo.

set "ROOT=%~dp0"

:: Check prerequisites
where python >nul 2>&1 || (echo ERROR: Python not found in PATH && exit /b 1)
where node >nul 2>&1 || (echo ERROR: Node.js not found in PATH && exit /b 1)

echo Starting Python backend (JSON-RPC serve mode)...
start "VoiceScribe Backend" cmd /k "cd /d "%ROOT%backend" && python -m src.main serve"

echo Waiting 2 seconds for backend to initialize...
timeout /t 2 /nobreak >nul

echo Starting Electron + Vite dev server...
cd /d "%ROOT%frontend"
call npm run electron:dev

echo.
echo Dev servers stopped.
