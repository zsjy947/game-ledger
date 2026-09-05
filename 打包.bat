@echo off
rem Build a standalone double-click exe folder with PyInstaller
cd /d "%~dp0"
setlocal
title Build Switch Price Tracker

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [TIP] Please run the app once first (double-click the launcher bat)
    echo       so the virtual environment gets initialized, then build again.
    pause
    exit /b 1
)

rem 1. Ensure PyInstaller is available (first build needs internet)
"%VENV_PY%" -m pip --version >nul 2>nul || "%VENV_PY%" -m ensurepip --upgrade >nul
"%VENV_PY%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [First build] Downloading PyInstaller, please wait...
    "%VENV_PY%" -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller. Check your network and try again.
        pause
        exit /b 1
    )
)

rem 2. Build (one-folder mode: fast startup, fewer antivirus false positives)
if exist "dist\SwitchPriceTracker\data" (
    echo [NOTE] Data found in dist\SwitchPriceTracker\data.
    echo        Rebuilding will DELETE that folder - back it up first if needed.
    pause
)
echo Building, please wait (1-3 minutes)...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --icon "scripts\icon.ico" --name "SwitchPriceTracker" --add-data "switch_price_tracker\templates;switch_price_tracker\templates" --add-data "switch_price_tracker\static;switch_price_tracker\static" --add-data "switch_price_tracker\assets;switch_price_tracker\assets" --collect-all webview --collect-all clr_loader --collect-all pythonnet --hidden-import webview.platforms.edgechromium --hidden-import webview.platforms.winforms launcher.py
if errorlevel 1 (
    echo [ERROR] Build failed. See the log above.
    pause
    exit /b 1
)

echo.
echo Build complete! Output folder: dist\SwitchPriceTracker\
echo Double-click SwitchPriceTracker.exe to open the app window.
echo Data is stored in the data subfolder next to the exe (portable).
pause
endlocal
