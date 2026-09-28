@echo off
rem Build a standalone double-click exe folder with PyInstaller
rem Output: release\GameLedger\  (portable - copy anywhere and run)
cd /d "%~dp0"
setlocal
title Build GameLedger

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
rem    - distpath release : final folder is release\GameLedger\
rem    - workpath/specpath build : intermediates stay inside build\ (gitignored)
rem    - add-data sources are absolute (%~dp0) because specpath relocates
rem      the spec file and relative data paths would resolve against it
rem    - static ships app.js + style.css only; static\games.js is the Android
rem      branch contract and is NOT used by the desktop app (catalog comes
rem      from /api/games/catalog), so it is excluded to avoid duplicate data
if exist "release\GameLedger\data" (
    echo [NOTE] Data found in release\GameLedger\data.
    echo        Rebuilding will DELETE that folder - back it up first if needed.
    pause
)
echo Building, please wait (1-3 minutes)...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --distpath release --workpath build --specpath build --icon "%~dp0scripts\icon.ico" --name "GameLedger" --add-data "%~dp0game_ledger\templates;game_ledger\templates" --add-data "%~dp0game_ledger\static\app.js;game_ledger\static" --add-data "%~dp0game_ledger\static\style.css;game_ledger\static" --add-data "%~dp0game_ledger\assets;game_ledger\assets" --collect-all webview --collect-all clr_loader --collect-all pythonnet --hidden-import webview.platforms.edgechromium --hidden-import webview.platforms.winforms "%~dp0launcher.py"
if errorlevel 1 (
    echo [ERROR] Build failed. See the log above.
    pause
    exit /b 1
)

echo.
echo Build complete! Output folder: release\GameLedger\
echo Double-click GameLedger.exe to open the app window.
echo The whole folder is portable - copy it anywhere and it still runs.
echo Data is stored in the data subfolder next to the exe.

rem 3. Pack the portable folder into a single zip (handy for GitHub release assets)
echo Creating portable zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'release\GameLedger' -DestinationPath 'release\GameLedger-portable.zip' -Force"
if errorlevel 1 (
    echo [WARN] Failed to create the zip. The portable folder above still works.
) else (
    echo Zip created: release\GameLedger-portable.zip
)
pause
endlocal
