@echo off
chcp 65001 >nul
title MC Tunnel Controller

setlocal enabledelayedexpansion

cd /d "%~dp0.."

set NEED_DEPS=0

rem -- 1. Make sure venv exists and works --
if not exist "venv\Scripts\python.exe" goto :no_venv

rem Try to actually run Python (not just check file existence)
set PYTHONUTF8=1
venv\Scripts\python.exe -c "print('ok')" >nul 2>&1
if !ERRORLEVEL! NEQ 0 goto :broken_venv

rem Venv is healthy -- check if dependencies are installed
venv\Scripts\python.exe -c "import loguru" >nul 2>&1
if !ERRORLEVEL! NEQ 0 set NEED_DEPS=1
goto :deps_check

:broken_venv
echo [WARN] Virtual environment is broken (base Python moved or removed)
rem Find system Python first, then delete old venv, then rebuild
call :find_system_python SYS_PY
if "!SYS_PY!"=="" (
    pause
    exit /b 1
)
echo [INFO] Removing broken venv...
rmdir /s /q venv
!SYS_PY! -m venv venv
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Failed to create virtual environment
    pause
    exit /b 1
)
set NEED_DEPS=1
goto :deps_check

:no_venv
echo [INFO] Python virtual environment not found, creating...
call :find_system_python SYS_PY
if "!SYS_PY!"=="" (
    pause
    exit /b 1
)
!SYS_PY! -m venv venv
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Failed to create virtual environment
    pause
    exit /b 1
)
set NEED_DEPS=1

rem -- 2. Install dependencies if needed --
:deps_check
if !NEED_DEPS! EQU 1 (
    echo [INFO] Installing dependencies...
    set PYTHONUTF8=1
    venv\Scripts\python.exe -m pip install --progress-bar on -r requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [INFO] Setup complete.
)

rem -- 3. First-run config check --
if not exist "config\config.yaml" (
    echo [INFO] config\config.yaml not found, using defaults
    echo First-time setup: open http://127.0.0.1:8443 - Setup Wizard
    echo.
)

if not exist "logs" mkdir logs

rem -- 4. Banner --
echo ============================================================
echo   MC Tunnel Controller v1.0
echo   Minecraft Server Tunnel Manager
echo ============================================================
echo.
echo   Python:  venv\Scripts\python.exe
echo   Config:  config\config.yaml
echo   Log:     logs\mc-tunnel.log
echo.
echo   Admin Panel + Intro: https://127.0.0.1:8443
echo ============================================================
echo.

rem -- 5. Launch --
echo [START] Launching MC Tunnel Controller...
echo.
set PYTHONUTF8=1
venv\Scripts\python.exe main.py %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Program exited with code %ERRORLEVEL%
    echo Check logs\mc-tunnel.log for details
)
pause
exit /b


rem ================================================================
rem  Helper: find an available Python on the system
rem ================================================================
:find_system_python
    where py >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "%~1=py -3"
        exit /b 0
    )
    where python >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "%~1=python"
        exit /b 0
    )
    where python3 >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "%~1=python3"
        exit /b 0
    )
    echo [ERROR] Python not found on system PATH
    echo Install Python 3 from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    set "%~1="
    exit /b 1
