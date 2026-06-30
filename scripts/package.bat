@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   MC 隧道控制器 — 分发打包脚本
echo ============================================
echo.

:: 1. 检查 exe 是否存在
if not exist "dist\mc-tunnel.exe" (
    echo [ERROR] dist\mc-tunnel.exe 未找到，请先运行:
    echo         python -m PyInstaller --clean mc-tunnel.spec
    exit /b 1
)

:: 2. 版本号
for /f "tokens=2 delims= " %%v in ('git describe --tags --always 2^>nul') do set VERSION=%%v
if "%VERSION%"=="" set VERSION=v1.0.0
set RELEASE_DIR=dist\mc-tunnel-%VERSION%

echo [INFO] 版本: %VERSION%
echo [INFO] 输出: %RELEASE_DIR%

:: 3. 创建发布目录
if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%\config"
mkdir "%RELEASE_DIR%\frp"
mkdir "%RELEASE_DIR%\docs"

:: 4. 复制文件
echo [INFO] 复制 mc-tunnel.exe ...
copy /y "dist\mc-tunnel.exe" "%RELEASE_DIR%\" >nul

echo [INFO] 复制 config\defaults.yaml ...
copy /y "config\defaults.yaml" "%RELEASE_DIR%\config\" >nul

echo [INFO] 复制文档 ...
copy /y "README.md" "%RELEASE_DIR%\" >nul
copy /y "LICENSE" "%RELEASE_DIR%\" >nul
copy /y "docs\user-guide.md" "%RELEASE_DIR%\docs\" >nul

:: 5. 创建 frp 占位说明
(
echo frp 内网穿透客户端 — 请将 frpc.exe 放入此目录
echo.
echo 下载地址:
echo   标准 frp:  https://github.com/fatedier/frp/releases
echo   樱花 Frp:  https://www.natfrp.com/
) > "%RELEASE_DIR%\frp\README.txt"

:: 6. 创建启动说明
(
echo MC 隧道控制器 %VERSION%
echo ====================================
echo.
echo 快速开始:
echo   1. 编辑 config\config.yaml 填入你的配置
echo   2. （可选）将 frpc.exe 放入 frp\ 目录
echo   3. 双击 mc-tunnel.exe 启动
echo   4. 浏览器打开 https://127.0.0.1:8443/dashboard
echo     默认账号: admin / admin
echo.
echo 详细说明见 docs\user-guide.md
) > "%RELEASE_DIR%\使用说明.txt"

:: 7. 打包 zip
echo [INFO] 打包 %RELEASE_DIR%.zip ...
powershell -NoProfile -Command "Compress-Archive -Path '%RELEASE_DIR%' -DestinationPath '%RELEASE_DIR%.zip' -Force"

echo.
echo ============================================
echo   打包完成！
echo   %RELEASE_DIR%.zip
echo ============================================
echo.
echo 用户安装步骤:
echo   1. 解压 zip 到任意目录
echo   2. 编辑 config\config.yaml
echo   3. 放入 frpc.exe 到 frp\（如需穿透）
echo   4. 双击 mc-tunnel.exe
echo ============================================
