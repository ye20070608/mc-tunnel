"""
Mojang EULA 确认模块。

Minecraft 服务端启动前必须在 eula.txt 中将 eula 设为 true。
本模块负责检查 EULA 状态，并在首次运行时引导用户确认。
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

MOJANG_EULA_URL = "https://aka.ms/MinecraftEULA"


def check_eula(server_dir: str | Path) -> bool:
    """检查 eula.txt 是否已同意。

    Args:
        server_dir: 服务端目录（eula.txt 所在目录）

    Returns:
        True 表示已同意
    """
    eula_path = Path(server_dir) / "eula.txt"

    if not eula_path.exists():
        logger.debug("eula.txt 不存在")
        return False

    content = eula_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip().lower()
        if line.startswith("eula=true"):
            return True

    return False


def prompt_eula() -> bool:
    """在控制台提示用户阅读并确认 Mojang EULA。

    Returns:
        True 表示用户同意
    """
    print()
    print("=" * 60)
    print("  Minecraft 服务端需要您同意 Mojang EULA（最终用户许可协议）")
    print()
    print(f"  请阅读: {MOJANG_EULA_URL}")
    print()
    print("  输入 Y 表示您已阅读并同意 Mojang EULA")
    print("  输入 N 或直接回车表示不同意（程序将退出）")
    print("=" * 60)
    print()

    try:
        answer = input("  您是否同意 Mojang EULA？(Y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if answer in ("y", "yes"):
        logger.info("用户已同意 Mojang EULA")
        return True
    else:
        logger.warning("用户未同意 Mojang EULA")
        return False


def write_eula(server_dir: str | Path) -> Path:
    """写入 eula.txt（eula=true）。

    Returns:
        eula.txt 的路径
    """
    eula_path = Path(server_dir) / "eula.txt"
    eula_path.write_text(
        f"# 通过 MC隧道控制器 自动生成\n"
        f"# 用户已确认同意 Mojang EULA ({MOJANG_EULA_URL})\n"
        f"# {Path(__file__).name}\n"
        f"eula=true\n",
        encoding="utf-8",
    )
    logger.info(f"EULA 已确认: {eula_path}")
    return eula_path
