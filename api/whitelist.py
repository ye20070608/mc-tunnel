"""Whitelist management API blueprint.

Allows listing, adding, and removing Minecraft player names from the
server whitelist. All endpoints require JWT authentication; state-changing
POST endpoints also require CSRF protection.
"""

from flask import Blueprint, current_app, jsonify, request

from api.middleware.auth import get_current_user, jwt_required
from api.middleware.csrf import csrf_protect
from core.mcserver.whitelist import WhitelistManager

whitelist_bp = Blueprint("whitelist", __name__, url_prefix="/api/whitelist")


def _get_adapter():
    """Return the MC adapter from the current app, or None."""
    return getattr(current_app, "mc_adapter", None)


def _get_whitelist_manager():
    """Return a WhitelistManager wrapping the current MC adapter, or None."""
    adapter = _get_adapter()
    if adapter is None:
        return None
    return WhitelistManager(adapter)


def _get_audit_logger():
    """Return the audit logger from the current app, or None."""
    return getattr(current_app, "audit_logger", None)


def _validate_player_name(name: str) -> bool:
    """Basic Minecraft player name validation.

    Valid player names are 1-16 characters, alphanumeric + underscore.
    """
    if not name or len(name) > 16:
        return False
    return all(c.isalnum() or c == "_" for c in name)


@whitelist_bp.route("/list", methods=["GET"])
@jwt_required
def list_whitelist():
    """Return the current whitelist entries."""
    wl_mgr = _get_whitelist_manager()
    if wl_mgr is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503
    try:
        entries = wl_mgr.list() or []
        return jsonify({"success": True, "whitelist": entries, "count": len(entries)})
    except Exception as e:
        current_app.logger.error("Failed to list whitelist: {}", e)
        return jsonify({"error": "whitelist_error", "message": str(e)}), 500


@whitelist_bp.route("/add", methods=["POST"])
@jwt_required
@csrf_protect
def add():
    """Add a player to the whitelist.

    Request body (JSON or form): ``{"name": "PlayerName"}``
    """
    data = request.get_json(silent=True) or request.form
    player_name: str = (data or {}).get("name", "").strip()

    if not _validate_player_name(player_name):
        return jsonify({"error": "invalid_input", "message": "Invalid player name (1-16 alphanumeric characters)"}), 400

    wl_mgr = _get_whitelist_manager()
    if wl_mgr is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        result = wl_mgr.add(player_name)
        # Audit log
        audit = _get_audit_logger()
        if audit is not None:
            try:
                audit.log(
                    operator=get_current_user() or "unknown",
                    action="whitelist_add",
                    ip=request.remote_addr or "",
                    details=f"Added '{player_name}' to whitelist",
                )
            except Exception:
                pass
        return jsonify({"success": result, "message": f"'{player_name}' added to whitelist"})
    except Exception as e:
        current_app.logger.error("Failed to add '{}' to whitelist: {}", player_name, e)
        return jsonify({"error": "add_failed", "message": str(e)}), 500


@whitelist_bp.route("/remove", methods=["POST"])
@jwt_required
@csrf_protect
def remove():
    """Remove a player from the whitelist.

    Request body (JSON or form): ``{"name": "PlayerName"}``
    """
    data = request.get_json(silent=True) or request.form
    player_name: str = (data or {}).get("name", "").strip()

    if not _validate_player_name(player_name):
        return jsonify({"error": "invalid_input", "message": "Invalid player name"}), 400

    wl_mgr = _get_whitelist_manager()
    if wl_mgr is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        result = wl_mgr.remove(player_name)
        # Audit log
        audit = _get_audit_logger()
        if audit is not None:
            try:
                audit.log(
                    operator=get_current_user() or "unknown",
                    action="whitelist_remove",
                    ip=request.remote_addr or "",
                    details=f"Removed '{player_name}' from whitelist",
                )
            except Exception:
                pass
        return jsonify({"success": result, "message": f"'{player_name}' removed from whitelist"})
    except Exception as e:
        current_app.logger.error("Failed to remove '{}' from whitelist: {}", player_name, e)
        return jsonify({"error": "remove_failed", "message": str(e)}), 500
