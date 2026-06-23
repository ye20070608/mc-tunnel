"""Logs API blueprint — retrieve MC server logs and export them.

All endpoints require JWT authentication.
"""

from flask import Blueprint, current_app, jsonify, request, Response

from api.middleware.auth import jwt_required

logs_bp = Blueprint("logs", __name__, url_prefix="/api/logs")


def _get_adapter():
    """Return the MC adapter from the current app, or None."""
    return getattr(current_app, "mc_adapter", None)


_LEVELS = {"info", "warn", "warning", "error", "debug"}


@logs_bp.route("/recent", methods=["GET"])
@jwt_required
def recent():
    """Return recent log entries.

    Query params:
      - level (str): filter by level (info, warn, error, debug).
      - limit (int, default 50): max entries to return (max 500).
    """
    level: str = request.args.get("level", "").strip().lower()
    limit: int = min(request.args.get("limit", 50, type=int), 500)

    if level and level not in _LEVELS:
        return jsonify({"error": "invalid_input", "message": f"Invalid log level. Supported: {', '.join(sorted(_LEVELS))}"}), 400

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        logs = adapter.get_logs(limit=limit) or []

        if level:
            # Normalize "warning" → "warn"
            norm_level = "warn" if level == "warning" else level
            logs = [entry for entry in logs if entry.get("level", "").lower() == norm_level]

        return jsonify({"success": True, "logs": logs, "count": len(logs)})
    except Exception as e:
        current_app.logger.error("Failed to retrieve logs: {}", e)
        return jsonify({"error": "log_error", "message": str(e)}), 500


@logs_bp.route("/export", methods=["GET"])
@jwt_required
def export():
    """Export logs as a downloadable plain-text file.

    Query params:
      - level (str): optional filter by level.
      - limit (int, default 1000): max entries to export (max 10000).
    """
    level: str = request.args.get("level", "").strip().lower()
    limit: int = min(request.args.get("limit", 1000, type=int), 10000)

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        logs = adapter.get_logs(limit=limit) or []

        if level:
            norm_level = "warn" if level == "warning" else level
            logs = [entry for entry in logs if entry.get("level", "").lower() == norm_level]

        lines: list[str] = []
        for entry in logs:
            ts = entry.get("time", "")
            lvl = entry.get("level", "info").upper()
            msg = entry.get("message", "")
            lines.append(f"[{ts}] [{lvl}] {msg}")

        content: str = "\n".join(lines)
        return Response(
            content,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=server_logs.txt"},
        )
    except Exception as e:
        current_app.logger.error("Failed to export logs: {}", e)
        return jsonify({"error": "export_error", "message": str(e)}), 500
