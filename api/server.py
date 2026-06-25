"""Server management API blueprint — versions, worlds, server info.

All endpoints require JWT authentication.
"""

from flask import Blueprint, current_app, jsonify, request
from pathlib import Path

from api.middleware.auth import jwt_required
from api.middleware.csrf import csrf_protect

server_bp = Blueprint("server", __name__, url_prefix="/api/server")


def _get_adapter():
    return getattr(current_app, "mc_adapter", None)


# ------------------------------------------------------------------
# Installed versions
# ------------------------------------------------------------------


@server_bp.route("/versions", methods=["GET"])
@jwt_required
def list_versions():
    """Return list of installed PaperMC JAR versions."""
    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        versions = adapter.get_installed_versions()
        current = getattr(adapter, "_config", None)
        current_version = current.mc.version if current else "unknown"
        return jsonify({
            "success": True,
            "versions": versions,
            "current_version": current_version,
        })
    except Exception as e:
        current_app.logger.error("Failed to list versions: {}", e)
        return jsonify({"error": "versions_error", "message": str(e)}), 500


@server_bp.route("/versions/switch", methods=["POST"])
@jwt_required
@csrf_protect
def switch_version():
    """Switch the active PaperMC version."""
    data = request.get_json(silent=True) or request.form
    version = (data or {}).get("version", "").strip()
    if not version:
        return jsonify({"error": "invalid_input", "message": "Version is required"}), 400

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        # Stop server first
        if adapter.is_running():
            adapter.stop()

        result = adapter.switch_version(version)
        if not result:
            return jsonify({"error": "switch_failed", "message": f"Version '{version}' JAR not found"}), 404

        return jsonify({"success": True, "message": f"Switched to {version}. Server restart required."})
    except Exception as e:
        current_app.logger.error("Failed to switch version: {}", e)
        return jsonify({"error": "switch_failed", "message": str(e)}), 500


@server_bp.route("/versions/download", methods=["POST"])
@jwt_required
@csrf_protect
def download_version():
    """Download a new PaperMC version (runs in background thread)."""
    data = request.get_json(silent=True) or request.form
    version = (data or {}).get("version", "").strip()
    if not version:
        return jsonify({"error": "invalid_input", "message": "Version is required"}), 400

    from core.mcserver.downloader import get_download_progress
    prog = get_download_progress()
    if prog.get("status") == "downloading":
        return jsonify({
            "error": "already_downloading",
            "message": f"正在下载版本 {prog.get('version')}，请等待完成",
        }), 429

    import threading
    def _background_dl():
        try:
            from core.mcserver.downloader import ensure_server_jar
            ensure_server_jar(
                version=version,
                server_jar_path="",
                output_dir=".",
                show_progress=False,
            )
        except Exception as e:
            current_app.logger.error("Background download failed: {}", e)
            from core.mcserver.downloader import _mark_progress_error
            _mark_progress_error()

    t = threading.Thread(target=_background_dl, daemon=True)
    t.start()
    return jsonify({"success": True, "message": f"开始下载 PaperMC {version}，请查看进度"})


# ------------------------------------------------------------------
# World management
# ------------------------------------------------------------------


@server_bp.route("/worlds", methods=["GET"])
@jwt_required
def list_worlds():
    """Return list of world directories."""
    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        from core.mcserver.worlds import WorldManager
        wm = WorldManager()
        worlds = wm.list_worlds()
        active = wm.get_active_world()
        return jsonify({
            "success": True,
            "worlds": worlds,
            "active_world": active,
        })
    except Exception as e:
        current_app.logger.error("Failed to list worlds: {}", e)
        return jsonify({"error": "worlds_error", "message": str(e)}), 500


@server_bp.route("/worlds/create", methods=["POST"])
@jwt_required
@csrf_protect
def create_world():
    """Create a new world directory."""
    data = request.get_json(silent=True) or request.form
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "invalid_input", "message": "World name is required"}), 400

    from core.mcserver.worlds import WorldManager
    if not WorldManager.validate_world_name(name):
        return jsonify({"error": "invalid_input", "message": "Invalid world name (letters, digits, underscores, hyphens only)"}), 400

    try:
        wm = WorldManager()
        result = wm.create_world(name)
        if not result:
            return jsonify({"error": "already_exists", "message": f"World '{name}' already exists"}), 409
        return jsonify({"success": True, "message": f"World '{name}' created"})
    except Exception as e:
        current_app.logger.error("Failed to create world: {}", e)
        return jsonify({"error": "create_world_error", "message": str(e)}), 500


@server_bp.route("/worlds/delete", methods=["POST"])
@jwt_required
@csrf_protect
def delete_world():
    """Delete a world directory."""
    data = request.get_json(silent=True) or request.form
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "invalid_input", "message": "World name is required"}), 400

    from core.mcserver.worlds import WorldManager
    if not WorldManager.validate_world_name(name):
        return jsonify({"error": "invalid_input", "message": "Invalid world name"}), 400

    # Refuse to delete the active world while server is running
    adapter = _get_adapter()
    if adapter and adapter.is_running():
        wm = WorldManager()
        active = wm.get_active_world()
        # get_active_world returns "worlds/<name>", strip prefix
        active_base = active.replace("worlds/", "").replace("worlds\\", "")
        if active_base == name:
            return jsonify({"error": "active_world", "message": "Cannot delete active world while server is running"}), 409

    try:
        wm = WorldManager()
        result = wm.delete_world(name)
        if not result:
            return jsonify({"error": "not_found", "message": f"World '{name}' not found"}), 404
        return jsonify({"success": True, "message": f"World '{name}' deleted"})
    except Exception as e:
        current_app.logger.error("Failed to delete world: {}", e)
        return jsonify({"error": "delete_world_error", "message": str(e)}), 500


@server_bp.route("/worlds/rename", methods=["POST"])
@jwt_required
@csrf_protect
def rename_world():
    """Rename a world directory."""
    data = request.get_json(silent=True) or request.form
    old_name = (data or {}).get("old_name", "").strip()
    new_name = (data or {}).get("new_name", "").strip()
    if not old_name or not new_name:
        return jsonify({"error": "invalid_input", "message": "Both old_name and new_name are required"}), 400

    from core.mcserver.worlds import WorldManager
    if not WorldManager.validate_world_name(old_name) or not WorldManager.validate_world_name(new_name):
        return jsonify({"error": "invalid_input", "message": "Invalid world name"}), 400

    try:
        wm = WorldManager()
        result = wm.rename_world(old_name, new_name)
        if not result:
            return jsonify({"error": "rename_failed", "message": f"Cannot rename '{old_name}' to '{new_name}'"}), 400
        return jsonify({"success": True, "message": f"Renamed '{old_name}' to '{new_name}'"})
    except Exception as e:
        current_app.logger.error("Failed to rename world: {}", e)
        return jsonify({"error": "rename_world_error", "message": str(e)}), 500


@server_bp.route("/worlds/activate", methods=["POST"])
@jwt_required
@csrf_protect
def activate_world():
    """Set the active world in server.properties."""
    data = request.get_json(silent=True) or request.form
    name = (data or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "invalid_input", "message": "World name is required"}), 400

    from core.mcserver.worlds import WorldManager
    if not WorldManager.validate_world_name(name):
        return jsonify({"error": "invalid_input", "message": "Invalid world name"}), 400

    try:
        wm = WorldManager()
        result = wm.activate_world(name)
        if not result:
            return jsonify({"error": "not_found", "message": f"World '{name}' not found"}), 404
        return jsonify({"success": True, "message": f"Active world set to '{name}'"})
    except Exception as e:
        current_app.logger.error("Failed to activate world: {}", e)
        return jsonify({"error": "activate_world_error", "message": str(e)}), 500


# ------------------------------------------------------------------
# Server info
# ------------------------------------------------------------------


@server_bp.route("/info", methods=["GET"])
@jwt_required
def server_info():
    """Return comprehensive server info (IP, port, version, world, etc.)."""
    import socket
    from core.mcserver.worlds import WorldManager

    adapter = _get_adapter()

    # Get installed versions alongside info
    installed_versions = []
    if adapter:
        try:
            installed_versions = adapter.get_installed_versions()
        except Exception:
            pass

    # Get local IP
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # Config values
    config = getattr(adapter, "_config", None)
    port = config.mc.port if config else 25565
    version = config.mc.version if config else "unknown"

    # Read online-mode from actual server.properties, not config
    online_mode = True  # safe default
    try:
        props_path = Path("server/server.properties")
        if props_path.exists():
            for line in props_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("online-mode="):
                    online_mode = line.split("=", 1)[1].strip().lower() == "true"
                    break
    except Exception:
        pass

    # Active world
    wm = WorldManager()
    active_world = wm.get_active_world()

    # Installed versions
    versions = adapter.get_installed_versions() if adapter else []

    return jsonify({
        "success": True,
        "data": {
            "local_ip": local_ip,
            "port": port,
            "lan_address": f"{local_ip}:{port}",
            "version": version,
            "online_mode": online_mode,
            "active_world": active_world,
            "status": "running" if (adapter and adapter.is_running()) else "stopped",
            "installed_versions": versions,
        },
    })


# ------------------------------------------------------------------
# Settings (online-mode toggle, etc.)
# ------------------------------------------------------------------


@server_bp.route("/settings", methods=["POST"])
@jwt_required
@csrf_protect
def update_settings():
    """Update server settings like online-mode.

    Request body::

        {"online_mode": false}
    """
    data = request.get_json(silent=True) or request.form
    if not data:
        return jsonify({"error": "invalid_input", "message": "No data provided"}), 400

    changed = []
    adapter = _get_adapter()

    # --- online_mode ---
    if "online_mode" in data:
        import os
        new_val = bool(data["online_mode"])
        # Update server.properties
        from pathlib import Path
        props_path = Path("server/server.properties")
        if props_path.exists():
            lines = props_path.read_text(encoding="utf-8").splitlines()
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith("online-mode="):
                    lines[i] = f"online-mode={'true' if new_val else 'false'}"
                    found = True
                    break
            if not found:
                lines.append(f"online-mode={'true' if new_val else 'false'}")
            # Atomic write via temp file
            tmp_path = Path(str(props_path) + ".tmp")
            tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(str(tmp_path), str(props_path))
        # Update in-memory config
        if adapter is not None and hasattr(adapter, "_config"):
            adapter._config.world.online_mode = new_val
        changed.append("online_mode")

    if not changed:
        return jsonify({"success": False, "message": "No settings changed"})

    return jsonify({
        "success": True,
        "message": f"已更新: {', '.join(changed)}。重启服务器后生效。",
        "changed": changed,
    })
