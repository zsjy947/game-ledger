@echo off
rem Build a standalone double-click exe folder with PyInstaller
rem Output: release\SwitchPriceTracker\  (portable - copy anywhere and run)
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
rem    - distpath release : final folder is release\SwitchPriceTracker\
rem    - workpath/specpath build : intermediates stay inside build\ (gitignored)
rem    - add-data sources are absolute (%~dp0) because specpath relocates
rem      the spec file and relative data paths would resolve against it
rem    - static ships app.js + style.css only; static\games.js is the Android
rem      branch contract and is NOT used by the desktop app (catalog comes
rem      from /api/games/catalog), so it is excluded to avoid duplicate data
if exist "release\SwitchPriceTracker\data" (
    echo [NOTE] Data found in release\SwitchPriceTracker\data.
    echo        Rebuilding will DELETE that folder - back it up first if needed.
    pause
)
echo Building, please wait (1-3 minutes)...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --distpath release --workpath build --specpath build --icon "%~dp0scripts\icon.ico" --name "SwitchPriceTracker" --add-data "%~dp0switch_price_tracker\templates;switch_price_tracker\templates" --add-data "%~dp0switch_price_tracker\static\app.js;switch_price_tracker\static" --add-data "%~dp0switch_price_tracker\static\style.css;switch_price_tracker\static" --add-data "%~dp0switch_price_tracker\assets;switch_price_tracker\assets" --collect-all webview --collect-all clr_loader --collect-all pythonnet --hidden-import webview.platforms.edgechromium --hidden-import webview.platforms.winforms "%~dp0launcher.py"
if errorlevel 1 (
    echo [ERROR] Build failed. See the log above.
    pause
    exit /b 1
)

echo.
echo Build complete! Output folder: release\SwitchPriceTracker\
echo Double-click SwitchPriceTracker.exe to open the app window.
echo The whole folder is portable - copy it anywhere and it still runs.
echo Data is stored in the data subfolder next to the exe.

rem 3. Pack the portable folder into a single zip (handy for GitHub release assets)
echo Creating portable zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'release\SwitchPriceTracker' -DestinationPath 'release\SwitchPriceTracker-portable.zip' -Force"
if errorlevel 1 (
    echo [WARN] Failed to create the zip. The portable folder above still works.
) else (
    echo Zip created: release\SwitchPriceTracker-portable.zip
)
pause
endlocal
