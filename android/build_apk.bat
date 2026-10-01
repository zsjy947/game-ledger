@echo off
rem One-click APK build for the Android WebView shell
rem Output: android\output\GameLedger.apk
cd /d "%~dp0"
setlocal
title Build GameLedger APK

set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [TIP] Please run the desktop app once first ^(double-click start.bat^)
    echo       so the virtual environment gets initialized, then build again.
    pause
    exit /b 1
)

"%VENV_PY%" "%~dp0build_apk.py" %*
if errorlevel 1 pause
endlocal
