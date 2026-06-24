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


def _find_java_in_path() -> str | None:
    """在系统 PATH 中查找 java 可执行文件。

    Windows 下会自动补全 .exe 后缀。
    """
    # Python 3.12+ 的 shutil.which 可带 path 参数，但这里先查系统 PATH
    java = shutil.which("java") or shutil.which("java.exe")
    return java


def _find_java_via_java_home() -> str | None:
    """通过 JAVA_HOME 环境变量查找 java。"""
    java_home = os.environ.get("JAVA_HOME", "")
    if not java_home:
        return None

    candidates = [
        Path(java_home) / "bin" / "java",
        Path(java_home) / "bin" / "java.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _find_common_install_paths() -> str | None:
    """在常见安装路径中查找 Java。"""
    if sys.platform == "win32":
        # Use environment variables for localized Program Files paths
        # (e.g. German "Programme", French "Programmes", Chinese "程序文件")
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        prog_w6432 = os.environ.get("ProgramW6432", prog_files)

        java_vendors = [
            "Eclipse Adoptium",
            "Java",
            "Eclipse Temurin",
            "Amazon Corretto",
            "Microsoft",
        ]
        search_roots = [Path(prog_w6432) / v for v in java_vendors]
        # Also check ProgramFiles (x86) on 64-bit systems for 32-bit Java
        if prog_files != prog_w6432:
            search_roots.extend(Path(prog_files) / v for v in java_vendors)

        for root in search_roots:
            if not root.exists():
                continue
            # 递归查找 java.exe（深度 3）
            for java_exe in root.glob("*/bin/java.exe"):
                return str(java_exe)
            for java_exe in root.glob("*/*/bin/java.exe"):
                return str(java_exe)

    elif sys.platform == "linux":
        # Linux 常见路径
        candidates = [
            "/usr/lib/jvm",
            "/usr/local/lib/jvm",
        ]
        for root in candidates:
            root_path = Path(root)
            if not root_path.exists():
                continue
            for java_bin in root_path.glob("*/bin/java"):
                return str(java_bin)
    return None


def detect_java(java_path: str = "") -> str:
    """检测并返回可用的 Java 可执行文件路径。

    查找优先级：
    1. 调用者指定的 java_path
    2. JAVA_HOME 环境变量
    3. 系统 PATH
    4. 常见安装路径扫描

    Args:
        java_path: 用户配置中指定的路径（空则跳过）

    Returns:
        java 可执行文件的绝对路径

    Raises:
        FileNotFoundError: 未找到 Java 安装
    """
    # 1. 指定路径
    if java_path:
        p = Path(java_path)
        if p.exists():
            logger.info(f"Java: {p}")
            return str(p.resolve())
        else:
            raise FileNotFoundError(f"配置的 java_path 不存在: {java_path}")

    # 2. JAVA_HOME
    found = _find_java_via_java_home()
    if found:
        logger.info(f"Java (JAVA_HOME): {found}")
        return found

    # 3. PATH
    found = _find_java_in_path()
    if found:
        logger.info(f"Java (PATH): {found}")
        return found

    # 4. 扫描常见路径
    found = _find_common_install_paths()
    if found:
        logger.info(f"Java (自动扫描): {found}")
        return found

    # 没找到
    raise FileNotFoundError(
        "未检测到 Java 安装。请确保满足以下任一条件:\n"
        "  1. 在 config.yaml 中设置 mc.java_path\n"
        "  2. 设置 JAVA_HOME 环境变量\n"
        "  3. 将 Java 加入系统 PATH\n"
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
