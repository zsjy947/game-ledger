@echo off
rem Switch cartridge price tracker - double-click launcher (no CLI needed)
cd /d "%~dp0"
setlocal
title Switch Price Tracker

rem 1. Locate a usable Python (prefer the py launcher)
set "PY_CMD="
py -3 --version >nul 2>nul && set "PY_CMD=py -3"
if not defined PY_CMD (
    python --version >nul 2>nul && set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [ERROR] Python not found. Install Python 3.10+ from
    echo         https://www.python.org/downloads/
    echo         and tick "Add Python to PATH" during setup, then run again.
    pause
    exit /b 1
)

rem 2. Prepare the virtual environment (first run only)
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [First run] Creating virtual environment, please wait...
    %PY_CMD% -m venv "%~dp0.venv"
)
if not exist "%VENV_PY%" (
    echo [ERROR] Failed to create .venv. Delete the .venv folder and try again.
    pause
    exit /b 1
)

rem 3. Install dependencies if missing (first run only, needs internet)
"%VENV_PY%" -c "import flask" >nul 2>nul
if errorlevel 1 (
    "%VENV_PY%" -m pip --version >nul 2>nul || "%VENV_PY%" -m ensurepip --upgrade >nul 2>nul
    echo [First run] Installing dependencies, please wait...
    "%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies. Check your network and run again.
        pause
        exit /b 1
    )
)

rem 4. Start the app (Python opens the browser automatically)
"%VENV_PY%" "%~dp0run.py"
if errorlevel 1 pause
endlocal
