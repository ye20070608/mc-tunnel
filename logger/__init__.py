"""
日志初始化模块 — 基于 Loguru。

用法:
    from logger import setup_logger, logger
    setup_logger("INFO", "logs")
    logger.info("hello")
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logger(level: str = "INFO", log_dir: str = "logs") -> None:
    """初始化日志系统。

    - 控制台输出：彩色，按指定级别过滤
    - 文件输出：按天轮转，保留 7 天
    """
    # 移除默认 handler
    logger.remove()

    # 控制台输出
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
    )

    # 文件输出
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_path / "mc-tunnel.log",
        level=level,
        rotation="00:00",       # 每天午夜轮转
        retention="7 days",     # 保留 7 天
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    )

    # 操作日志单独记录
    logger.add(
        log_path / "audit.log",
        level="INFO",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        filter=lambda record: record["extra"].get("audit", False),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {extra[user]:<12} | {extra[ip]:<16} | {message}",
    )

    logger.debug(f"日志已初始化，级别={level}，目录={log_dir}")
