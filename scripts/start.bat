@echo off
chcp 65001 >nul
title MC Tunnel Controller

setlocal enabledelayedexpansion

cd /d "%~dp0.."

set NEED_DEPS=0

rem ── 1. Check if venv python works ──────────────────────────
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        rem Venv python works — check if key dependency is installed
        set PYTHONUTF8=1
        venv\Scripts\python.exe -c "import loguru" >nul 2>&1
        if !ERRORLEVEL! NEQ 0 set NEED_DEPS=1
    ) else (
        echo [WARN] Virtual environment is broken ^(base Python moved or removed^)
        echo [INFO] Removing old venv and recreating...
        rmdir /s /q venv
        set NEED_DEPS=1
        call :do_create_venv
        if !ERRORLEVEL! NEQ 0 exit /b 1
    )
) else (
    echo [INFO] Python virtual environment not found, creating...
    set NEED_DEPS=1
    call :do_create_venv
    if !ERRORLEVEL! NEQ 0 exit /b 1
)

rem ── 2. Install dependencies if needed ──────────────────────
if !NEED_DEPS! EQU 1 (
    echo [INFO] Installing dependencies...
    set PYTHONUTF8=1
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [INFO] Setup complete.
)

rem ── 3. First-run config check ──────────────────────────────
if not exist "config\config.yaml" (
    echo [INFO] config\config.yaml not found, using defaults
    echo First-time setup: open http://127.0.0.1:8443 - Setup Wizard
    echo.
)

if not exist "logs" mkdir logs

rem ── 4. Banner ──────────────────────────────────────────────
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

rem ── 5. Launch ──────────────────────────────────────────────
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

rem ── Helper: create virtual environment ─────────────────────
:do_create_venv
    where py >nul 2>nul && (py -3 -m venv venv) || (python -m venv venv)
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to create virtual environment
        echo Make sure Python is installed and added to PATH
        exit /b 1
    )
    exit /b 0
