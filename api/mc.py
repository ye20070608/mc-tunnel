"""MC server control API blueprint.

All endpoints require JWT authentication. State-changing endpoints
(POST) also require CSRF protection.
"""

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from api.middleware.auth import jwt_required
from api.middleware.csrf import csrf_protect
from api.whitelist import _validate_player_name
from core.audit.logger import AuditLogger

mc_bp = Blueprint("mc", __name__, url_prefix="/api/mc")


def _get_adapter():
    """Return the MC adapter from the current app, or None."""
    return getattr(current_app, "mc_adapter", None)


@mc_bp.route("/start", methods=["POST"])
@jwt_required
@csrf_protect
def start():
    """Start the Minecraft server."""
    current_app.logger.info(
        "API: /api/mc/start called (ip={}, content_type={}, is_json={})",
        request.remote_addr,
        request.content_type,
        request.is_json,
    )
    adapter = _get_adapter()
    if adapter is None:
        current_app.logger.error("API: /api/mc/start — MC adapter not available")
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        result = adapter.start()
        current_app.logger.info("API: /api/mc/start — result={}", result)
        return jsonify({"success": True, "message": "Server start initiated", "data": result or {}})
    except Exception as e:
        current_app.logger.error("API: /api/mc/start — failed: {}", e)
        return jsonify({"error": "start_failed", "message": str(e)}), 500


@mc_bp.route("/stop", methods=["POST"])
@jwt_required
@csrf_protect
def stop():
    """Stop the Minecraft server."""
    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        result = adapter.stop()
        return jsonify({"success": True, "message": "Server stop initiated", "data": result or {}})
    except Exception as e:
        current_app.logger.error("Failed to stop MC server: {}", e)
        return jsonify({"error": "stop_failed", "message": str(e)}), 500


@mc_bp.route("/restart", methods=["POST"])
@jwt_required
@csrf_protect
def restart():
    """Restart the Minecraft server."""
    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        result = adapter.restart()
        return jsonify({"success": True, "message": "Server restart initiated", "data": result or {}})
    except Exception as e:
        current_app.logger.error("Failed to restart MC server: {}", e)
        return jsonify({"error": "restart_failed", "message": str(e)}), 500


@mc_bp.route("/status", methods=["GET"])
@jwt_required
def status():
    """Return current MC server status (players, TPS, memory, uptime, etc.)."""
    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        data = adapter.get_status() or {}
        return jsonify({"success": True, "data": data})
    except Exception as e:
        current_app.logger.error("Failed to get MC server status: {}", e)
        return jsonify({"error": "status_error", "message": str(e)}), 500


@mc_bp.route("/players", methods=["GET"])
@jwt_required
def players():
    """Return the list of online players with ping, gamemode, and join time."""
    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        player_list = adapter.get_players() or []
        # Inject IP information
        player_ips = {}
        try:
            player_ips = adapter.get_player_ips() or {}
        except Exception:
            pass

        # Determine whitelist membership (read whitelist.json directly, no RCON)
        whitelisted_names: set[str] = set()
        try:
            import json
            wl_path = Path("whitelist.json")
            if wl_path.is_file():
                wl_data = json.loads(wl_path.read_text(encoding="utf-8"))
                if isinstance(wl_data, list):
                    for entry in wl_data:
                        if isinstance(entry, dict) and "name" in entry:
                            whitelisted_names.add(entry["name"].lower())
        except Exception:
            pass

        for p in player_list:
            p["ip"] = player_ips.get(p.get("name", ""), "")
            p["in_whitelist"] = p.get("name", "").lower() in whitelisted_names
        return jsonify({"success": True, "players": player_list, "count": len(player_list)})
    except Exception as e:
        current_app.logger.error("Failed to get player list: {}", e)
        return jsonify({"error": "players_error", "message": str(e)}), 500


@mc_bp.route("/kick", methods=["POST"])
@jwt_required
@csrf_protect
def kick():
    """Kick a player from the server by name."""
    data = request.get_json(silent=True) or request.form
    player_name = (data or {}).get("name", "").strip()
    if not player_name:
        return jsonify({"error": "invalid_input", "message": "Player name is required"}), 400
    if not _validate_player_name(player_name):
        return jsonify({"error": "invalid_input", "message": "Invalid player name"}), 400

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        result = adapter.kick_player(player_name)
        return jsonify({"success": True, "message": f"Player '{player_name}' kicked", "data": result or {}})
    except Exception as e:
        current_app.logger.error("Failed to kick player '{}': {}", player_name, e)
        return jsonify({"error": "kick_failed", "message": str(e)}), 500


@mc_bp.route("/op", methods=["POST"])
@jwt_required
@csrf_protect
def op_player():
    """Grant operator (OP) status to a player."""
    data = request.get_json(silent=True) or request.form
    player_name = (data or {}).get("name", "").strip()
    if not player_name:
        return jsonify({"error": "invalid_input", "message": "Player name is required"}), 400
    if not _validate_player_name(player_name):
        return jsonify({"error": "invalid_input", "message": "Invalid player name"}), 400

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        result = adapter.op_player(player_name)
        return jsonify({"success": True, "message": f"'{player_name}' is now a server operator"})
    except Exception as e:
        current_app.logger.error("Failed to op player '{}': {}", player_name, e)
        return jsonify({"error": "op_failed", "message": str(e)}), 500


@mc_bp.route("/console", methods=["GET"])
@jwt_required
def console():
    """Return recent Minecraft server console output."""
    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        limit = request.args.get("limit", 100, type=int)
        lines = adapter.get_console_output(limit)
        return jsonify({"success": True, "lines": lines, "count": len(lines)})
    except Exception as e:
        current_app.logger.error("Failed to get console output: {}", e)
        return jsonify({"error": "console_error", "message": str(e)}), 500


@mc_bp.route("/deop", methods=["POST"])
@jwt_required
@csrf_protect
def deop_player():
    """Revoke operator (OP) status from a player."""
    data = request.get_json(silent=True) or request.form
    player_name = (data or {}).get("name", "").strip()
    if not player_name:
        return jsonify({"error": "invalid_input", "message": "Player name is required"}), 400
    if not _validate_player_name(player_name):
        return jsonify({"error": "invalid_input", "message": "Invalid player name"}), 400

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        result = adapter.deop_player(player_name)
        return jsonify({"success": True, "message": f"'{player_name}' is no longer a server operator"})
    except Exception as e:
        current_app.logger.error("Failed to deop player '{}': {}", player_name, e)
        return jsonify({"error": "deop_failed", "message": str(e)}), 500


@mc_bp.route("/command", methods=["POST"])
@jwt_required
@csrf_protect
def command():
    """Send a command to the Minecraft server via RCON.

    Request body::

        {"command": "list"}
    """
    data = request.get_json(silent=True) or request.form
    cmd = (data or {}).get("command", "").strip()
    if not cmd:
        return jsonify({"error": "invalid_input", "message": "Command is required"}), 400

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        response = adapter.send_command(cmd)
        # Record to audit log
        try:
            audit = AuditLogger()
            audit.log(
                operator=request.headers.get("X-Operator", "admin"),
                action="rcon_command",
                details={"command": cmd},
            )
        except Exception:
            pass
        return jsonify({"success": True, "response": response, "command": cmd})
    except Exception as e:
        current_app.logger.error("Failed to execute command '{}': {}", cmd, e)
        return jsonify({"error": "command_failed", "message": str(e)}), 500
