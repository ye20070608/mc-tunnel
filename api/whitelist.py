"""Whitelist management API blueprint.

Endpoints for listing, adding, removing, reloading, and toggling
the Minecraft server whitelist.  All endpoints require JWT auth;
state-changing POST endpoints also require CSRF protection.
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


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _validate_player_name(name: str) -> bool:
    """Basic Minecraft player name validation.

    Valid player names are 1-16 characters, alphanumeric + underscore.
    """
    if not name or len(name) > 16:
        return False
    return all(c.isalnum() or c == "_" for c in name)


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@whitelist_bp.route("/list", methods=["GET"])
@jwt_required
def list_whitelist():
    """Return the current whitelist with online status and metadata.

    Cross-references ``whitelist.json``, ``whitelist_meta.json``, the
    online player list, and IP tracking.
    """
    wl_mgr = _get_whitelist_manager()
    if wl_mgr is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        entries = wl_mgr.list() or []
    except Exception as e:
        current_app.logger.error("Failed to list whitelist: {}", e)
        return jsonify({"error": "whitelist_error", "message": str(e)}), 500

    # Cross-reference with online players
    adapter = _get_adapter()
    online_names: set[str] = set()
    player_ips: dict[str, str] = {}
    try:
        for p in (adapter.get_players() or []):
            online_names.add(p.get("name", "").lower())
    except Exception:
        pass
    try:
        player_ips = adapter.get_player_ips() or {}
    except Exception:
        pass

    for entry in entries:
        name = entry.get("name", "")
        entry["online"] = name.lower() in online_names
        entry["ip"] = player_ips.get(name, "")

    # Include whitelist enforcement status so the frontend can show the toggle state
    enabled = None
    try:
        enabled = wl_mgr.is_enabled()
    except Exception:
        pass

    return jsonify({
        "success": True,
        "whitelist": entries,
        "count": len(entries),
        "enabled": enabled,
    })


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
        operator = get_current_user() or "admin"
        result = wl_mgr.add(player_name, operator=operator)
        # Audit log
        audit = _get_audit_logger()
        if audit is not None:
            try:
                audit.log(
                    operator=operator,
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
                    operator=get_current_user() or "admin",
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


@whitelist_bp.route("/reload", methods=["POST"])
@jwt_required
@csrf_protect
def reload():
    """Reload the whitelist from disk (``whitelist reload``)."""
    wl_mgr = _get_whitelist_manager()
    if wl_mgr is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        result = wl_mgr.reload()
        return jsonify({"success": result, "message": "Whitelist reloaded"})
    except Exception as e:
        current_app.logger.error("Failed to reload whitelist: {}", e)
        return jsonify({"error": "reload_failed", "message": str(e)}), 500


@whitelist_bp.route("/toggle", methods=["POST"])
@jwt_required
@csrf_protect
def toggle():
    """Toggle whitelist enforcement on or off."""
    wl_mgr = _get_whitelist_manager()
    if wl_mgr is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        result = wl_mgr.toggle()
        # Audit log
        audit = _get_audit_logger()
        if audit is not None:
            try:
                action = "whitelist_on" if result.get("enabled") else "whitelist_off"
                audit.log(
                    operator=get_current_user() or "admin",
                    action=action,
                    ip=request.remote_addr or "",
                    details=result.get("message", ""),
                )
            except Exception:
                pass
        return jsonify({"success": True, "data": result})
    except Exception as e:
        current_app.logger.error("Failed to toggle whitelist: {}", e)
        return jsonify({"error": "toggle_failed", "message": str(e)}), 500


@whitelist_bp.route("/pending", methods=["GET"])
@jwt_required
def pending():
    """Return players recently rejected by the whitelist.

    These are candidates for quick one-click whitelist addition.
    """
    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        entries = adapter.get_pending_players() or []
        return jsonify({"success": True, "pending": entries, "count": len(entries)})
    except Exception as e:
        current_app.logger.error("Failed to get pending players: {}", e)
        return jsonify({"error": "pending_error", "message": str(e)}), 500
