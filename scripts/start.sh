#!/usr/bin/env bash
# ============================================================
#  MC隧道控制器 — Linux/macOS 一键启动脚本
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

# 检查虚拟环境（不仅要存在，还要能正常运行）
VENV_OK=0
if [ -f "venv/bin/python" ]; then
    venv/bin/python --version >/dev/null 2>&1 && VENV_OK=1
fi

if [ $VENV_OK -eq 0 ]; then
    if [ -f "venv/bin/python" ]; then
        echo "[警告] 虚拟环境已损坏（原始 Python 可能被移动/卸载），正在重建..."
        rm -rf venv
    else
        echo "[信息] 未找到 Python 虚拟环境，正在创建..."
    fi
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "[错误] 创建虚拟环境失败，请确保 Python 3 已安装"
        exit 1
    fi
    echo "[信息] 正在安装依赖..."
    venv/bin/python -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[错误] 依赖安装失败"
        exit 1
    fi
    echo "[信息] 环境初始化完成。"
fi

# 配置文件提示
if [ ! -f "config/config.yaml" ]; then
    echo "[提示] 未找到 config/config.yaml，将使用默认配置"
    echo
fi

# 创建日志目录
mkdir -p logs

echo "============================================================"
echo "  MC隧道控制器 v1.0"
echo "  一体化 Minecraft 服务器穿透控制软件"
echo "============================================================"
echo
echo "  Python: venv/bin/python"
echo "  配置:   config/config.yaml"
echo "  日志:   logs/mc-tunnel.log"
echo
echo "  管理后台 + 介绍页: https://127.0.0.1:8443"
echo "============================================================"
echo

echo "[启动] 正在启动 MC 隧道控制器..."
exec venv/bin/python main.py "$@"
