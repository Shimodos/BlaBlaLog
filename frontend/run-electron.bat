@echo off
set ELECTRON_RUN_AS_NODE=
cd /d "%~dp0"
echo Starting Electron from %cd%...
echo Python venv: %~dp0..\backend\.venv\Scripts\python.exe
node_modules\electron\dist\electron.exe .
echo Exit code: %ERRORLEVEL%
pause
