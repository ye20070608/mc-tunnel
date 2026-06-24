@echo off
chcp 65001 >nul
title MC Tunnel Controller

setlocal enabledelayedexpansion

cd /d "%~dp0.."

if not exist "venv\Scripts\python.exe" (
    echo [INFO] Python virtual environment not found, creating...
    where py >nul 2>nul && (py -3 -m venv venv) || (python -m venv venv)
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to create virtual environment
        echo Make sure Python is installed and added to PATH
        pause
        exit /b 1
    )
    echo [INFO] Installing dependencies...
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [INFO] Setup complete.
)

if not exist "config\config.yaml" (
    echo [INFO] config\config.yaml not found, using defaults
    echo First-time setup: open http://127.0.0.1:8443 - Setup Wizard
    echo.
)

if not exist "logs" mkdir logs

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

echo [START] Launching MC Tunnel Controller...
echo.
venv\Scripts\python.exe main.py %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Program exited with code %ERRORLEVEL%
    echo Check logs\mc-tunnel.log for details
)
pause
