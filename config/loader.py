"""
配置加载器 — YAML 读取、校验、默认值填充。

用法:
    from config.loader import load_config
    cfg = load_config("config/config.yaml")
    print(cfg.mc.port)
"""

from __future__ import annotations

import shutil
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


# ---------------------------------------------------------------------------
# 配置数据类
# ---------------------------------------------------------------------------

@dataclass
class MCConfig:
    version: str = "1.20.1"
    port: int = 25565
    max_players: int = 20
    java_path: str = ""
    jvm_args: str = "-Xmx4G -Xms2G"
    server_jar: str = ""
    auto_restart: bool = True
    restart_max_retries: int = 3


@dataclass
class WebConfig:
    admin_port: int = 8443
    session_timeout: int = 3600
    csrf_enabled: bool = True
    rate_limit: str = "10/minute"
    ssl_enabled: bool = True
    ssl_cert: str = "config/certs/cert.pem"
    ssl_key: str = "config/certs/key.pem"


@dataclass
class AdminAccount:
    username: str = ""
    password_hash: str = ""


@dataclass
class TunnelMapping:
    local_port: int = 0
    remote_port: int = 0
    protocol: str = "tcp"
    auth_pass: str = ""         # 樱花 Frp 每个代理的独立认证密码


@dataclass
class TunnelConfig:
    server_addr: str = ""
    server_port: int = 7000
    token: str = ""
    protocol: str = "tcp"
    enabled_ports: list[str] = field(default_factory=lambda: ["mc", "intro", "admin"])
    mapping: dict[str, TunnelMapping] = field(default_factory=dict)
    # Sakura Frp 专用字段
    user: str = ""                   # 樱花 Frp 用户 ID（非空 = 樱花模式）
    sakura_mode: bool = False
    login_fail_exit: bool = False
    auth_pass: str = ""              # 每个代理的认证密码


@dataclass
class WorldConfig:
    level_name: str = "worlds/world"           # 活跃世界路径（相对于工作目录）
    seed: str = ""                          # 留空 = 随机种子
    gamemode: str = "survival"              # survival / creative / adventure / spectator
    difficulty: str = "easy"                # peaceful / easy / normal / hard
    pvp: bool = True
    hardcore: bool = False
    spawn_protection: int = 16
    max_players: int = 20
    motd: str = "A Minecraft Server"
    allow_nether: bool = True
    allow_end: bool = True
    enable_command_block: bool = False
    allow_flight: bool = False
    online_mode: bool = True
    whitelist_enabled: bool = True
    view_distance: int = 10
    simulation_distance: int = 10


@dataclass
class Config:
    mc: MCConfig = field(default_factory=MCConfig)
    web: WebConfig = field(default_factory=WebConfig)
    admins: list[AdminAccount] = field(default_factory=list)
    tunnel: TunnelConfig = field(default_factory=TunnelConfig)
    world: WorldConfig = field(default_factory=WorldConfig)


# ---------------------------------------------------------------------------
# 加载与合并
# ---------------------------------------------------------------------------

DEFAULTS_PATH = Path(__file__).resolve().parent / "defaults.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    """读取 YAML 文件，返回字典。文件不存在返回空字典。"""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(default: dict, override: dict) -> dict:
    """深合并：override 的值覆盖 default 的值。"""
    result = deepcopy(default)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _dict_to_config(data: dict[str, Any]) -> Config:
    """将字典转换为 Config 数据类。"""
    mc_data = data.get("mc", {})
    mc = MCConfig(
        version=mc_data.get("version", "1.20.1"),
        port=mc_data.get("port", 25565),
        max_players=mc_data.get("max_players", 20),
        java_path=mc_data.get("java_path", ""),
        jvm_args=mc_data.get("jvm_args", "-Xmx4G -Xms2G"),
        server_jar=mc_data.get("server_jar", ""),
        auto_restart=mc_data.get("auto_restart", True),
        restart_max_retries=mc_data.get("restart_max_retries", 3),
    )

    web_data = data.get("web", {})
    web = WebConfig(
        admin_port=web_data.get("admin_port", 8443),
        session_timeout=web_data.get("session_timeout", 3600),
        csrf_enabled=web_data.get("csrf_enabled", True),
        rate_limit=web_data.get("rate_limit", "10/minute"),
        ssl_enabled=web_data.get("ssl_enabled", True),
        ssl_cert=web_data.get("ssl_cert", "config/certs/cert.pem"),
        ssl_key=web_data.get("ssl_key", "config/certs/key.pem"),
    )

    admins = [
        AdminAccount(username=a.get("username", ""), password_hash=a.get("password_hash", ""))
        for a in data.get("admins", [])
        if a.get("username")
    ]

    tunnel_data = data.get("tunnel", {})
    mapping_raw = tunnel_data.get("mapping", {})
    mapping = {
        k: TunnelMapping(
            local_port=v.get("local_port", 0),
            remote_port=v.get("remote_port", 0),
            protocol=v.get("protocol", "tcp"),
            auth_pass=v.get("auth_pass", ""),
        )
        for k, v in mapping_raw.items()
    }
    tunnel = TunnelConfig(
        server_addr=tunnel_data.get("server_addr", ""),
        server_port=tunnel_data.get("server_port", 7000),
        token=tunnel_data.get("token", ""),
        protocol=tunnel_data.get("protocol", "tcp"),
        enabled_ports=tunnel_data.get("enabled_ports", ["mc", "admin"]),
        mapping=mapping,
        # Sakura Frp fields
        user=tunnel_data.get("user", ""),
        sakura_mode=tunnel_data.get("sakura_mode", False),
        login_fail_exit=tunnel_data.get("login_fail_exit", False),
        auth_pass=tunnel_data.get("auth_pass", ""),
    )

    world_data = data.get("world", {})
    world = WorldConfig(
        level_name=world_data.get("level_name", "worlds/world"),
        seed=world_data.get("seed", ""),
        gamemode=world_data.get("gamemode", "survival"),
        difficulty=world_data.get("difficulty", "easy"),
        pvp=world_data.get("pvp", True),
        hardcore=world_data.get("hardcore", False),
        spawn_protection=world_data.get("spawn_protection", 16),
        max_players=world_data.get("max_players", 20),
        motd=world_data.get("motd", "A Minecraft Server"),
        allow_nether=world_data.get("allow_nether", True),
        allow_end=world_data.get("allow_end", True),
        enable_command_block=world_data.get("enable_command_block", False),
        allow_flight=world_data.get("allow_flight", False),
        online_mode=world_data.get("online_mode", True),
        view_distance=world_data.get("view_distance", 10),
        simulation_distance=world_data.get("simulation_distance", 10),
    )

    return Config(mc=mc, web=web, admins=admins, tunnel=tunnel, world=world)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def load_config(config_path: str | Path) -> Config:
    """加载配置文件，合并默认值。

    1. 若用户配置文件不存在，从 defaults.yaml 复制
    2. 深合并：用户配置覆盖默认值
    3. 基础校验
    """
    config_path = Path(config_path)

    # 首次运行：复制默认配置
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if DEFAULTS_PATH.exists():
            shutil.copy(DEFAULTS_PATH, config_path)
            logger.info(f"首次运行，已创建配置文件: {config_path}")
            logger.info("请编辑此文件后重新运行程序")
            sys.exit(0)
        else:
            logger.warning(f"默认配置模板不存在: {DEFAULTS_PATH}")

    # 加载默认值
    defaults = _load_yaml(DEFAULTS_PATH)

    # 加载用户配置
    user_config = _load_yaml(config_path)

    # 深合并
    merged = _deep_merge(defaults, user_config)

    # 转换数据类
    cfg = _dict_to_config(merged)

    # 校验
    errors = validate(cfg)
    if errors:
        for err in errors:
            logger.error(err)
        sys.exit(1)

    logger.debug(f"配置已加载: {config_path}")
    return cfg


def validate(cfg: Config) -> list[str]:
    """基础配置校验，返回错误信息列表。"""
    errors: list[str] = []

    # 端口校验
    if not (1 <= cfg.mc.port <= 65535):
        errors.append(f"mc.port 无效: {cfg.mc.port}")

    if not (1 <= cfg.web.admin_port <= 65535):
        errors.append(f"web.admin_port 无效: {cfg.web.admin_port}")

    # 端口冲突检测
    ports = [
        ("mc.port", cfg.mc.port),
        ("web.admin_port", cfg.web.admin_port),
    ]
    seen: dict[int, str] = {}
    for name, port in ports:
        if port in seen:
            errors.append(f"端口冲突: {name}({port}) 与 {seen[port]}({port})")
        seen[port] = name

    # 玩家数
    if cfg.mc.max_players < 1:
        errors.append(f"mc.max_players 必须 >= 1，当前值: {cfg.mc.max_players}")

    # World config validation
    valid_gamemodes = ("survival", "creative", "adventure", "spectator")
    if cfg.world.gamemode not in valid_gamemodes:
        errors.append(
            f"world.gamemode 无效: {cfg.world.gamemode}，"
            f"有效值: {', '.join(valid_gamemodes)}"
        )
    valid_difficulties = ("peaceful", "easy", "normal", "hard")
    if cfg.world.difficulty not in valid_difficulties:
        errors.append(
            f"world.difficulty 无效: {cfg.world.difficulty}，"
            f"有效值: {', '.join(valid_difficulties)}"
        )

    return errors


# ---------------------------------------------------------------------------
# Config manager (read/write support for admin operations)
# ---------------------------------------------------------------------------


class ConfigManager:
    """Read/write access to the YAML config file for admin operations.

    Used by the admin API to persist changes such as password updates.
    """

    def __init__(self, config_path: str | Path = "config/config.yaml") -> None:
        """Initialise with the path to the YAML config file.

        Args:
            config_path: Path to the application config file.
        """
        self.config_path = Path(config_path)

    def update_admin_password(self, username: str, new_hash: str) -> bool:
        """Update an admin account's password hash in the config file.

        Uses a temp-file + ``os.replace()`` pattern for atomic writes,
        preventing file corruption if the write is interrupted.

        Args:
            username: Admin username to update.
            new_hash: New BCrypt hash to store.

        Returns:
            True on success.

        Raises:
            ValueError: If *username* is not found in the config.
        """
        import os
        import tempfile

        with open(self.config_path, "r", encoding="utf-8") as fh:
            config: dict[str, Any] = yaml.safe_load(fh) or {}

        admins: list[dict[str, Any]] = config.get("admins", [])
        found = False
        for admin in admins:
            if admin.get("username") == username:
                admin["password_hash"] = new_hash
                found = True
                break

        if not found:
            raise ValueError(f"Admin '{username}' not found in config")

        # Atomic write: temp file → os.replace
        config_dir = os.path.dirname(self.config_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.dump(config, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
            os.replace(tmp_path, self.config_path)
        except Exception:
            os.unlink(tmp_path)
            raise

        return True


def ensure_config_exists(config_path: str | Path) -> bool:
    """检查用户配置是否存在，不存在则从默认值创建。
    返回 True 表示配置已就绪。
    """
    config_path = Path(config_path)
    if config_path.exists():
        return True

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if DEFAULTS_PATH.exists():
        shutil.copy(DEFAULTS_PATH, config_path)
        return True
    return False
