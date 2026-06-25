"""
MC隧道控制器 (mc-tunnel) — 主入口。

一体化 Minecraft 服务端穿透管理软件。
启动流程:
  1. 初始化日志
  2. 加载 / 创建配置
  3. 检测 Java 环境
  4. 选择/确认 MC 版本
  5. 确保 MC 服务端 JAR 就绪（自动下载或使用已有）
  6. Mojang EULA 确认
  7. 启动进程管理 + frp 穿透 + Web 服务

用法:
    python main.py                    # 交互式启动（首次运行引导选择版本）
    python main.py --version 1.21     # 指定版本启动
    python main.py --version 1.20.4   # 切换到其他版本
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure the working directory is the project root (where this file lives).
# This makes all relative paths (logs/, config/, server.properties, etc.)
# work correctly regardless of where the user launched the process from.
_PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(str(_PROJECT_ROOT))

# 确保终端输出使用 UTF-8（Windows 中文系统需 chcp 65001 配合）
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from logger import setup_logger, logger
from config.loader import load_config
from core.mcserver.java import detect_java, check_java_version
from core.mcserver.downloader import (
    ensure_server_jar,
    switch_version,
    list_stable_versions,
    _find_existing_jar,
)
from core.mcserver.eula import check_eula, prompt_eula, write_eula


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="MC隧道控制器 — 一体化 MC 服务器穿透管理"
    )
    parser.add_argument(
        "--version", "-v",
        type=str,
        default=None,
        help="指定 PaperMC 版本（如 1.21、1.20.4），留空则使用配置或交互式选择",
    )
    return parser.parse_args()


def _interactive_select_version() -> str:
    """交互式版本选择。

    从 PaperMC API 拉取可用版本列表，展示推荐版本供用户选择。

    Returns:
        用户选择的版本号字符串
    """
    print()
    print("=" * 50)
    print("  获取 PaperMC 可用版本列表...")

    try:
        versions = list_stable_versions(limit=15)
    except Exception as e:
        logger.warning(f"无法获取版本列表: {e}")
        print("  无法连接 PaperMC API，使用默认版本 1.20.1")
        return "1.20.1"

    if not versions:
        print("  未找到可用版本，使用默认版本 1.20.1")
        return "1.20.1"

    print(f"  可用 PaperMC 稳定版本（共 {len(versions)} 个）:")
    print()

    # 展示版本列表（多列节省空间）
    for i, v in enumerate(versions):
        marker = "  ← 最新" if i == 0 else ""
        # 推荐标记
        rec = ""
        if v in ("1.20.1", "1.20.6", "1.21"):
            rec = " [推荐]"
        print(f"  [{i + 1:2d}] {v:<10}{rec}{marker}")

    print()
    print(f"  直接回车使用推荐版本: {versions[0]}")
    print("=" * 50)

    try:
        choice = input("  请选择版本编号 (1-{}): ".format(len(versions))).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        logger.info(f"使用默认版本: {versions[0]}")
        return versions[0]

    if not choice:
        logger.info(f"使用默认版本: {versions[0]}")
        return versions[0]

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(versions):
            selected = versions[idx]
            logger.info(f"已选择版本: {selected}")
            return selected
    except ValueError:
        pass

    # 用户可能直接输入了版本号
    if choice in versions:
        logger.info(f"已选择版本: {choice}")
        return choice

    print(f"  输入无效，使用默认版本: {versions[0]}")
    return versions[0]


def main() -> None:
    """主入口。"""
    args = _parse_args()

    # ── 1. 初始化日志 ─────────────────────────────────────────
    setup_logger("INFO", "logs")
    logger.info("=" * 50)
    logger.info("MC隧道控制器 (mc-tunnel) 启动中...")

    # ── 2. 加载配置 ───────────────────────────────────────────
    # load_config 首次运行时会创建配置文件并退出
    cfg = load_config("config/config.yaml")

    # ── 2.5 首次运行：设置默认管理员密码 ──────────────────────
    _needs_init = all(
        not a.password_hash for a in cfg.admins if a.username
    )
    if _needs_init:
        import bcrypt
        from config.loader import ConfigManager

        default_hash = bcrypt.hashpw(
            b"admin", bcrypt.gensalt(rounds=12)
        ).decode("utf-8")
        cm = ConfigManager("config/config.yaml")
        cm.update_admin_password("admin", default_hash)
        cfg.admins[0].password_hash = default_hash
        logger.info("已设置默认管理员密码: admin/admin（请登录后修改！）")

    # ── 3. 检测 Java ──────────────────────────────────────────
    logger.info("检测 Java 环境...")
    try:
        java_path = detect_java(cfg.mc.java_path)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    check_java_version(java_path)

    # ── 4. 确定 MC 版本 ────────────────────────────────────────
    # 优先级：CLI --version > 配置文件 > 交互式选择
    output_dir = str(Path.cwd() / "server")

    if args.version:
        # CLI 指定版本
        target_version = args.version
        logger.info(f"使用命令行指定的版本: {target_version}")
    elif cfg.mc.version:
        # 配置文件中已有版本
        target_version = cfg.mc.version
        logger.info(f"使用配置文件版本: {target_version}")
    else:
        # 交互式选择
        target_version = _interactive_select_version()

    # 检查是否已有不同版本的 JAR，询问是否切换
    existing_jar = _find_existing_jar(target_version, output_dir)
    if existing_jar:
        # 已有当前版本 JAR
        pass
    else:
        # 没有当前版本 JAR，检查是否有其他版本
        other_jars = list(Path(output_dir).glob("paper-*.jar"))
        if other_jars and not args.version:
            other_jars.sort(reverse=True)
            current_name = other_jars[0].name
            print()
            print(f"  检测到已有 {current_name}，但配置的目标版本是 {target_version}")
            try:
                switch = input(f"  是否切换到 {target_version} 并下载？(Y/N，回车=Y): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                switch = "y"
            if switch in ("n", "no"):
                target_version = cfg.mc.version  # 保持原版本
                logger.info(f"保持当前版本: {target_version}")

    # ── 5. 确保 MC 服务端 JAR 就绪 ───────────────────────────
    logger.info(f"准备 MC 服务端 (版本: {target_version})...")
    try:
        jar_path = ensure_server_jar(
            version=target_version,
            server_jar_path=cfg.mc.server_jar,
            output_dir=output_dir,
            show_progress=True,
        )
    except Exception as e:
        logger.error(f"无法获取 MC 服务端 JAR: {e}")
        sys.exit(1)

    # ── 6. EULA 确认 ──────────────────────────────────────────
    server_dir = jar_path.parent
    if not check_eula(server_dir):
        if not prompt_eula():
            logger.error("Mojang EULA 未同意，无法启动 MC 服务端")
            sys.exit(1)
        write_eula(server_dir)

    # ── 7. 构建运行时组件 ─────────────────────────────────────
    cfg.mc.java_path = java_path
    cfg.mc.version = target_version

    # 创建审计日志
    from core.audit.logger import AuditLogger
    audit_logger = AuditLogger("logs/audit.log", logger)

    # 创建配置管理器
    from config.loader import ConfigManager
    config_manager = ConfigManager("config/config.yaml")

    # 迁移旧世界到 worlds/ 目录（首次迁移）
    from core.mcserver.worlds import WorldManager
    wm = WorldManager(server_dir="server")
    migrated = wm.migrate_existing()
    if migrated > 0:
        logger.info(f"已迁移 {migrated} 个世界到 worlds/ 目录")

    # Clean up orphaned root-level world dirs that PaperMC may have
    # regenerated because the old level-name didn't use the nested path.
    active_group = wm.get_active_world()
    import shutil as _shutil
    server_root = Path.cwd() / "server"
    for _dim in ("world", "world_nether", "world_the_end"):
        _root_dir = server_root / _dim
        _nested = server_root / "worlds" / active_group / _dim
        if _root_dir.is_dir() and _nested.is_dir():
            logger.warning(
                "发现孤立的世界目录: {} (已迁移到 {})，自动清理",
                _root_dir, _nested,
            )
            try:
                _shutil.rmtree(_root_dir)
                logger.info("已清理: {}", _root_dir)
            except OSError as exc:
                logger.warning("无法清理 {}: {}", _root_dir, exc)

    # 创建 MC 适配器
    from core.mcserver.adapter import MCServerAdapter
    mc_adapter = MCServerAdapter(cfg, logger)
    logger.info(f"MC 适配器已初始化: {jar_path}")

    # 创建隧道管理器（标准 frp 需 token，樱花 Frp 需 user）
    tunnel_manager = None
    if cfg.tunnel.server_addr and (cfg.tunnel.token or cfg.tunnel.user):
        from core.tunnel.client import FrpClient

        # Auto-detect frpc binary (prefer exact match, then wildcard)
        import platform
        _cwd = Path.cwd() / "frp"
        _frpc_path = None
        _candidates = (
            ["frpc.exe", "frpc_windows_amd64.exe", "frpc_windows_386.exe"]
            if platform.system() == "Windows"
            else ["frpc", "frpc_linux_amd64", "frpc_linux_arm64"]
        )
        for _name in _candidates:
            _test = _cwd / _name
            if _test.exists():
                _frpc_path = str(_test)
                break
        # Fallback: any frpc* binary in cwd
        if _frpc_path is None:
            _wild = sorted(_cwd.glob("frpc*"))
            if _wild:
                _frpc_path = str(_wild[0])
        # Last resort: try PATH
        if _frpc_path is None:
            _frpc_path = "frpc.exe" if platform.system() == "Windows" else "frpc"

        tunnel_manager = FrpClient(cfg, logger=logger, frp_binary=_frpc_path)
        logger.info(f"使用 frpc: {_frpc_path}")
        if cfg.tunnel.user:
            logger.info(f"隧道管理器已初始化 (樱花): {cfg.tunnel.server_addr}:{cfg.tunnel.server_port}")
        else:
            logger.info(f"隧道管理器已初始化: {cfg.tunnel.server_addr}:{cfg.tunnel.server_port}")
        # frpc is NOT auto-started — user controls it from the admin panel
    else:
        logger.info("未配置隧道服务器，跳过 frp 管理")

    # ── 8. 启动 Web 服务 ──────────────────────────────────────
    from dataclasses import asdict
    from web.server import run_server

    config_dict = asdict(cfg)

    logger.info("─" * 50)
    logger.info("所有前置检查通过！")
    logger.info(f"  Java:      {java_path}")
    logger.info(f"  服务端 JAR: {jar_path}")
    logger.info(f"  版本:      {target_version}")
    logger.info(f"  端口:      {cfg.mc.port}")
    logger.info(f"  JVM 参数:  {cfg.mc.jvm_args}")
    logger.info("─" * 50)
    logger.info("启动 Web 服务...")

    run_server(config_dict, logger, mc_adapter, tunnel_manager, audit_logger, config_manager)

    scheme = "https" if cfg.web.ssl_enabled else "http"
    logger.info(f"管理后台: {scheme}://127.0.0.1:{cfg.web.admin_port}/dashboard")
    logger.info(f"介绍页:   {scheme}://127.0.0.1:{cfg.web.admin_port}/intro")
    logger.info("按 Ctrl+C 停止所有服务")

    # ── 9. 保持主线程存活 ─────────────────────────────────────
    import signal
    import time

    shutdown_flag = False

    def _shutdown(signum, frame):
        nonlocal shutdown_flag
        logger.info("收到停止信号，正在关闭...")
        shutdown_flag = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while not shutdown_flag:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    logger.info("MC隧道控制器已停止")


if __name__ == "__main__":
    main()
