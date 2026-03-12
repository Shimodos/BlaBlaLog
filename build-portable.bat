@echo off
title Building VoiceScribe Portable
cd /d "%~dp0"

echo ============================================
echo    Building VoiceScribe Portable
echo ============================================
echo.

:: 1. Build frontend
echo [1/3] Building frontend...
cd /d "%~dp0frontend"
call npx vite build
if errorlevel 1 (
    echo [ERROR] Frontend build failed
    pause
    exit /b 1
)

:: 2. Create release directory
echo [2/3] Creating portable package...
set RELEASE_DIR=%~dp0release\VoiceScribe
if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"

:: Copy Electron
echo    Copying Electron runtime...
xcopy /s /e /q /y "%~dp0frontend\node_modules\electron\dist\*" "%RELEASE_DIR%\electron\" > nul

:: Copy app files
echo    Copying app files...
mkdir "%RELEASE_DIR%\app\dist"
mkdir "%RELEASE_DIR%\app\electron"
xcopy /s /e /q /y "%~dp0frontend\dist\*" "%RELEASE_DIR%\app\dist\" > nul
xcopy /s /e /q /y "%~dp0frontend\electron\*" "%RELEASE_DIR%\app\electron\" > nul
copy /y "%~dp0frontend\package.json" "%RELEASE_DIR%\app\" > nul

:: Copy backend (with venv)
echo    Copying Python backend...
xcopy /s /e /q /y "%~dp0backend\src\*" "%RELEASE_DIR%\backend\src\" > nul
copy /y "%~dp0backend\requirements.txt" "%RELEASE_DIR%\backend\" > nul

:: Copy Python venv (only essential parts)
echo    Copying Python venv (this may take a while)...
xcopy /s /e /q /y "%~dp0backend\.venv\Scripts\*" "%RELEASE_DIR%\backend\.venv\Scripts\" > nul
xcopy /s /e /q /y "%~dp0backend\.venv\Lib\*" "%RELEASE_DIR%\backend\.venv\Lib\" > nul

:: 3. Create launcher exe (actually a bat wrapped in vbs)
echo [3/3] Creating launcher...

:: Create the VBS launcher
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDirectory = CreateObject^("Scripting.FileSystemObject"^).GetParentFolderName^(WScript.ScriptFullName^)
echo Set WshEnv = WshShell.Environment^("Process"^)
echo WshEnv.Remove^("ELECTRON_RUN_AS_NODE"^)
echo WshShell.Run """electron\electron.exe"" ""app""", 0, False
) > "%RELEASE_DIR%\VoiceScribe.vbs"

:: Create a simple bat launcher too (for debugging)
(
echo @echo off
echo cd /d "%%~dp0"
echo set ELECTRON_RUN_AS_NODE=
echo electron\electron.exe app
echo pause
) > "%RELEASE_DIR%\VoiceScribe-debug.bat"

echo.
echo ============================================
echo    Build complete!
echo    Output: release\VoiceScribe\
echo    Launch: VoiceScribe.vbs (silent)
echo    Debug:  VoiceScribe-debug.bat (with console)
echo ============================================
echo.
pause
