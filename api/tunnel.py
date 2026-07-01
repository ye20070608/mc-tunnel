"""Tunnel management API blueprint.

Provides endpoints to query and update frp tunnel configuration
and connection status.
"""

import shutil
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from api.middleware.auth import jwt_required
from api.middleware.csrf import csrf_protect

tunnel_bp = Blueprint("tunnel", __name__, url_prefix="/api/tunnel")

# frpc download URLs
FRPC_DOWNLOAD_URLS = {
    "sakura": "https://www.natfrp.com/",
    "standard": "https://github.com/fatedier/frp/releases",
}


def _get_manager():
    """Return the tunnel manager from the current app, or None."""
    return getattr(current_app, "tunnel_manager", None)


def _find_frpc_binary() -> str | None:
    """Check if frpc binary exists in frp/ directory or PATH.

    Returns the found binary name, or None.
    """
    frp_dir = Path("frp")
    if frp_dir.is_dir():
        import sys
        if sys.platform == "win32":
            candidates = ["frpc.exe", "frpc_windows_amd64.exe", "frpc_windows_386.exe"]
        else:
            candidates = ["frpc", "frpc_linux_amd64", "frpc_linux_arm64"]
        for name in candidates:
            if (frp_dir / name).is_file():
                return name
        # wildcard fallback
        for f in sorted(frp_dir.glob("frpc*")):
            if f.is_file():
                return f.name
    # PATH fallback
    import sys
    target = "frpc.exe" if sys.platform == "win32" else "frpc"
    if shutil.which(target):
        return target
    return None


@tunnel_bp.route("/frpc-check", methods=["GET"])
@jwt_required
def frpc_check():
    """Check if the frpc binary is present in frp/ or PATH.

    Returns:
        found: bool — whether frpc binary was found
        path: str | null — the binary name/path if found
        download_urls: dict — download links for standard and Sakura frp
        frp_dir_exists: bool — whether frp/ directory exists
    """
    found = _find_frpc_binary()
    frp_dir_exists = Path("frp").is_dir()
    return jsonify({
        "success": True,
        "data": {
            "found": found is not None,
            "path": found,
            "frp_dir_exists": frp_dir_exists,
            "download_urls": FRPC_DOWNLOAD_URLS,
        },
    })


@tunnel_bp.route("/status", methods=["GET"])
@jwt_required
def status():
    """Return tunnel connection status and active port mappings.

    Includes connection state, server address, uptime, and the list
    of configured port mappings with their status.
    """
    manager = _get_manager()
    if manager is None:
        return jsonify({"error": "not_available", "message": "Tunnel manager not available"}), 503
    try:
        data = manager.get_status() or {}
        return jsonify({"success": True, "data": data})
    except Exception as e:
        current_app.logger.error("Failed to get tunnel status: {}", e)
        return jsonify({"error": "status_error", "message": str(e)}), 500


@tunnel_bp.route("/start", methods=["POST"])
@jwt_required
@csrf_protect
def start():
    """Manually start the frpc tunnel client."""
    manager = _get_manager()
    if manager is None:
        return jsonify({"error": "not_available", "message": "Tunnel manager not available"}), 503
    try:
        ok = manager.start()
        if ok:
            current_app.logger.info("frpc started via admin panel")
            return jsonify({"success": True, "message": "frpc started"})
        return jsonify({"error": "start_failed", "message": "frpc is already running or failed to start"}), 409
    except Exception as e:
        current_app.logger.error("Failed to start frpc: {}", e)
        return jsonify({"error": "start_error", "message": str(e)}), 500


@tunnel_bp.route("/stop", methods=["POST"])
@jwt_required
@csrf_protect
def stop():
    """Manually stop the frpc tunnel client."""
    manager = _get_manager()
    if manager is None:
        return jsonify({"error": "not_available", "message": "Tunnel manager not available"}), 503
    try:
        if not manager.is_running():
            return jsonify({"success": True, "message": "frpc is not running"})
        ok = manager.stop()
        if ok:
            current_app.logger.info("frpc stopped via admin panel")
            return jsonify({"success": True, "message": "frpc stopped"})
        return jsonify({"error": "stop_failed", "message": "Failed to stop frpc"}), 500
    except Exception as e:
        current_app.logger.error("Failed to stop frpc: {}", e)
        return jsonify({"error": "stop_error", "message": str(e)}), 500


@tunnel_bp.route("/update", methods=["POST"])
@jwt_required
@csrf_protect
def update():
    """Dynamically update tunnel port mappings.

    Expects a JSON body with mapping configuration, e.g.:
    ``{"mapping": {"mc": {"local_port": 25565, "remote_port": 25565, "protocol": "tcp"}}}``
    """
    data = request.get_json(silent=True)
    if not data or "mapping" not in data:
        return jsonify({"error": "invalid_input", "message": "Request body must include a 'mapping' object"}), 400

    manager = _get_manager()
    if manager is None:
        return jsonify({"error": "not_available", "message": "Tunnel manager not available"}), 503
    try:
        result = manager.update_mapping(list(data["mapping"].keys()))
        return jsonify({"success": True, "message": "Tunnel mapping updated", "data": result or {}})
    except Exception as e:
        current_app.logger.error("Failed to update tunnel mapping: {}", e)
        return jsonify({"error": "update_failed", "message": str(e)}), 500
