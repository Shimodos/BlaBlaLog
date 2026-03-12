@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   VoiceScribe Build Script
echo ============================================
echo.

:: Check prerequisites
py -3.11 --version >nul 2>&1 || (echo ERROR: Python 3.11 not found && exit /b 1)
where node >nul 2>&1 || (echo ERROR: Node.js not found in PATH && exit /b 1)
where npm >nul 2>&1 || (echo ERROR: npm not found in PATH && exit /b 1)

:: Store the root directory
set "ROOT=%~dp0"
set "PYTHON=py -3.11"
set "VENV=%ROOT%backend\.venv"

:: Create venv if needed
if not exist "%VENV%\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv "%VENV%"
)
call "%VENV%\Scripts\activate.bat"

echo [1/5] Installing Python dependencies...
cd /d "%ROOT%backend"
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install Python dependencies
    exit /b 1
)
pip install pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install PyInstaller
    exit /b 1
)

echo.
echo [2/5] Building Python backend with PyInstaller...
pyinstaller --noconfirm voicescribe.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    exit /b 1
)
echo Python backend built: backend\dist\voicescribe-backend\

echo.
echo [3/5] Installing frontend dependencies...
cd /d "%ROOT%frontend"
call npm install
if errorlevel 1 (
    echo ERROR: npm install failed
    exit /b 1
)

echo.
echo [4/5] Building frontend (Vite)...
call npm run build
if errorlevel 1 (
    echo ERROR: Vite build failed
    exit /b 1
)

echo.
echo [5/5] Packaging Electron app with electron-builder...
:: Copy Python backend into frontend resources so electron-builder bundles it
if not exist "%ROOT%frontend\resources\backend" mkdir "%ROOT%frontend\resources\backend"
xcopy /E /Y /Q "%ROOT%backend\dist\voicescribe-backend\*" "%ROOT%frontend\resources\backend\"
if errorlevel 1 (
    echo ERROR: Failed to copy backend to frontend resources
    exit /b 1
)

call npx electron-builder --win
if errorlevel 1 (
    echo ERROR: electron-builder failed
    exit /b 1
)

cd /d "%ROOT%"

echo.
echo ============================================
echo   Build complete!
echo ============================================
echo.
echo Installer location:
dir /b "frontend\dist\VoiceScribe Setup*.exe" 2>nul || echo   (check frontend\dist\ for output)
echo.
pause
