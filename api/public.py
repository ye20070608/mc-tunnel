"""Public API blueprint — no authentication required.

Serves server information that the intro page and external visitors
can consume without any credentials.
"""

from flask import Blueprint, current_app, jsonify

from core.mcserver.downloader import get_download_progress, list_all_stable_builds
from loguru import logger

public_bp = Blueprint("public", __name__, url_prefix="/api/public")


@public_bp.route("/versions", methods=["GET"])
def versions():
    """返回 PaperMC 可用版本列表（无需鉴权）。

    Response:
        {
            "versions": ["1.21", "1.20.6", "1.20.4", ...],
            "current": "1.20.4",
            "recommended": ["1.21", "1.20.6", "1.20.4"]
        }
    """
    config = current_app.config.get("CONFIG", {})
    mc_cfg = config.get("mc", {})
    current_version = mc_cfg.get("version", "1.20.1")

    try:
        versions = list_all_stable_builds(limit=30)
    except Exception as e:
        logger.warning(f"获取 PaperMC 版本列表失败: {e}")
        # 离线降级：返回内置列表
        versions = [
            "1.21", "1.20.6", "1.20.5", "1.20.4", "1.20.3", "1.20.2", "1.20.1",
            "1.20", "1.19.4", "1.19.3", "1.19.2", "1.19.1", "1.19",
            "1.18.2", "1.18.1", "1.18",
        ]

    return jsonify({
        "versions": versions,
        "current": current_version,
        "recommended": ["1.21", "1.20.6", "1.20.1"],
    })


@public_bp.route("/status", methods=["GET"])
def status():
    """Return public server information.

    Response includes:
      - Server version, MOTD, online/max players
      - Intro page content (name, slogan, description, rules, features)
      - Tunnel status summary

    Shape mirrors ``data.json`` for frontend compatibility.
    """
    config = current_app.config.get("CONFIG", {})
    mc_cfg = config.get("mc", {})
    intro_cfg = config.get("intro", {})

    # Try to get live status from the MC adapter (if this is the admin app)
    live_status = {}
    mc_adapter = getattr(current_app, "mc_adapter", None)
    if mc_adapter is not None:
        try:
            live_status = mc_adapter.get_status() or {}
        except Exception:
            live_status = {}

    # Try to get tunnel status
    tunnel_status = {}
    tunnel_manager = getattr(current_app, "tunnel_manager", None)
    if tunnel_manager is not None:
        try:
            tunnel_status = tunnel_manager.get_status() or {}
        except Exception:
            tunnel_status = {}

    online = live_status.get("onlinePlayers", 0)
    max_players = live_status.get("maxPlayers", mc_cfg.get("max_players", 20))
    tps = live_status.get("tps", 20.0)

    payload = {
        "server": {
            "status": live_status.get("status", "unknown"),
            "version": mc_cfg.get("version", "1.20.4"),
            "motd": intro_cfg.get("motd", ""),
            "onlinePlayers": online,
            "maxPlayers": max_players,
            "tps": tps,
            "port": mc_cfg.get("port", 25565),
            "memory": live_status.get("memory", {"used": "0G", "max": "0G", "percent": 0}),
            "uptime": live_status.get("uptime", "N/A"),
            "cpu": live_status.get("cpu", "N/A"),
            "autoRestart": mc_cfg.get("auto_restart", True),
        },
        "intro": {
            "serverName": intro_cfg.get("server_name", "MC Server"),
            "slogan": intro_cfg.get("slogan", ""),
            "description": intro_cfg.get("description", ""),
            "rules": intro_cfg.get("rules", []),
            "features": intro_cfg.get("features", []),
            "version": mc_cfg.get("version", "1.20.4"),
        },
        "tunnel": {
            "status": tunnel_status.get("status", "disconnected"),
            "server": tunnel_status.get("server", config.get("tunnel", {}).get("server_addr", "N/A")),
            "uptime": tunnel_status.get("uptime", "N/A"),
            "activeTunnels": tunnel_status.get("activeTunnels", 0),
            "mappings": tunnel_status.get("mappings", []),
        },
    }

    return jsonify(payload)


@public_bp.route("/download-progress", methods=["GET"])
def download_progress():
    """Return current PaperMC JAR download progress (no auth required)."""
    progress = get_download_progress()
    return jsonify({"success": True, "data": progress})
