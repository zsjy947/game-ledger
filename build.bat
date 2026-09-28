@echo off
rem Build a standalone double-click exe folder with PyInstaller
rem Output: release\GameLedger\  (portable - copy anywhere and run)
cd /d "%~dp0"
setlocal
title Build GameLedger

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [TIP] Please run the app once first ^(double-click start.bat first^)
    echo        so the virtual environment gets initialized, then build again.
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
rem 2b. Preserve user data: PyInstaller --noconfirm wipes the whole output
rem     folder, so move data\ aside first and restore it after the build.
set "DATA_DIR=release\GameLedger\data"
set "DATA_BAK=release\GameLedger-data-backup"
if exist "%DATA_DIR%" (
    if exist "%DATA_BAK%" rmdir /s /q "%DATA_BAK%"
    move "%DATA_DIR%" "%DATA_BAK%" >nul 2>&1
    if exist "%DATA_DIR%" (
        echo [ERROR] Could not move the data folder aside.
        echo         Close the app if it is running, then build again.
        pause
        exit /b 1
    )
    echo [OK] Existing data folder moved aside - it will be restored after the build.
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

rem 2c. Restore the user data folder that was moved aside before the build
if exist "%DATA_BAK%" (
    if exist "%DATA_DIR%" rmdir /s /q "%DATA_DIR%"
    move "%DATA_BAK%" "%DATA_DIR%" >nul
    echo [OK] Data folder restored to %DATA_DIR% - your records are safe.
)

rem 3. Pack the portable folder into a single zip (handy for GitHub release assets)
rem    The user's data subfolder is excluded - a release zip must not ship
rem    personal records or the cover cache.
echo Creating portable zip...
"%VENV_PY%" "%~dp0scripts\make_portable_zip.py"
if errorlevel 1 (
    echo [WARN] Failed to create the zip. The portable folder above still works.
) else (
    echo Zip ready: release\GameLedger-portable.zip ^(user data excluded^)
)
pause
endlocal
