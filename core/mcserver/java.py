"""
Java 检测模块 — 查找 Java 安装路径并校验版本兼容性。

用法:
    from core.mcserver.java import detect_java, check_java_version
    path = detect_java(java_path_candidate="")
    check_java_version(path)  # >= 17 才通过
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from loguru import logger

MIN_JAVA_VERSION = 17
RECOMMENDED_VERSION_URL = "https://adoptium.net/download/"


def detect_java(java_path: str = "") -> str:
    """检测并返回可用的 Java 可执行文件路径。

    查找优先级：
    1. 调用者指定的 java_path（config.yaml）
    2. 系统 PATH（shutil.which）
    3. JAVA_HOME 环境变量

    Args:
        java_path: 用户配置中指定的路径（空则跳过）

    Returns:
        java 可执行文件的绝对路径

    Raises:
        FileNotFoundError: 未找到 Java 安装
    """
    # 1. 用户显式指定（config.yaml）—— 优先使用，失效则降级到 PATH
    if java_path:
        p = Path(java_path)
        if p.exists():
            logger.info(f"Java (config): {p}")
            return str(p.resolve())
        else:
            logger.warning(f"配置的 java_path 不存在: {java_path}，降级使用 PATH 查找")

    # 2. 系统 PATH
    java = shutil.which("java") or shutil.which("java.exe")
    if java:
        logger.info(f"Java (PATH): {java}")
        return java

    # 3. JAVA_HOME 兜底
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        for candidate in (
            Path(java_home) / "bin" / "java",
            Path(java_home) / "bin" / "java.exe",
        ):
            if candidate.exists():
                logger.info(f"Java (JAVA_HOME): {candidate}")
                return str(candidate)

    # 没找到
    raise FileNotFoundError(
        "未检测到 Java 安装。请确保满足以下任一条件:\n"
        "  1. 在 config.yaml 中设置 mc.java_path\n"
        "  2. 将 Java 加入系统 PATH 环境变量\n"
        "  3. 设置 JAVA_HOME 环境变量\n"
        f"下载 JDK 17+: {RECOMMENDED_VERSION_URL}"
    )


def get_java_version(java_path: str) -> tuple[int, int]:
    """获取 Java 版本号。

    Java 8+ 的 -version 输出格式示例:
        openjdk version "17.0.9" 2023-10-17
        java version "1.8.0_391"

    Returns:
        (major, minor) — 如 (17, 0)
    """
    try:
        result = subprocess.run(
            [java_path, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        # Java 将版本信息输出到 stderr
        output = result.stderr + result.stdout

        # 匹配版本号: "17.0.9" 或 "1.8.0_391"
        match = re.search(r'"(\d+)\.(\d+)\.', output)
        if not match:
            # 再试: 旧格式 "1.8"
            match = re.search(r'version "(\d+)\.(\d+)', output)

        if match:
            major = int(match.group(1))
            minor = int(match.group(2))
            # 旧版命名: 1.8 → major=8
            if major == 1:
                major = minor
                minor = 0
            return major, minor

    except subprocess.TimeoutExpired:
        logger.warning(f"Java -version 超时: {java_path}")
    except FileNotFoundError:
        raise FileNotFoundError(f"无法执行 Java: {java_path}")
    except Exception as e:
        logger.warning(f"解析 Java 版本失败: {e}")

    return 0, 0


def check_java_version(java_path: str) -> tuple[int, int]:
    """校验 Java 版本 ≥ MIN_JAVA_VERSION。

    Returns:
        (major, minor) 版本号

    Raises:
        SystemExit: 版本不兼容
    """
    major, minor = get_java_version(java_path)

    if major == 0:
        logger.error(f"无法确定 Java 版本: {java_path}")
        logger.error(f"请确认 {java_path} 是有效的 Java 可执行文件")
        sys.exit(1)

    if major < MIN_JAVA_VERSION:
        logger.error(
            f"Java 版本不兼容: 当前 {major}.{minor}, "
            f"需要 >= {MIN_JAVA_VERSION}"
        )
        logger.error(f"Minecraft 1.18+ 需要 Java 17 或更高版本")
        logger.error(f"下载地址: {RECOMMENDED_VERSION_URL}")
        sys.exit(1)

    logger.info(f"Java 版本: {major}.{minor} (最低要求 {MIN_JAVA_VERSION}) ✓")
    return major, minor
