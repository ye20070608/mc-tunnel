"""Logs API blueprint — retrieve MC server logs, export, and clear them.

All endpoints require JWT authentication.
"""

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, Response

from api.middleware.auth import jwt_required
from api.middleware.csrf import csrf_protect

logs_bp = Blueprint("logs", __name__, url_prefix="/api/logs")


def _get_adapter():
    """Return the MC adapter from the current app, or None."""
    return getattr(current_app, "mc_adapter", None)


_LEVELS = {"info", "warn", "warning", "error", "debug"}


@logs_bp.route("/recent", methods=["GET"])
@jwt_required
def recent():
    """Return recent server log entries.

    Reads from PaperMC's ``logs/latest.log`` (falls back to the in-memory
    console buffer if the file does not exist).

    Query params:
      - level (str): filter by level (info, warn, error, debug).
      - limit (int, default 100): max entries to return (max 1000).
    """
    level: str = request.args.get("level", "").strip().lower()
    limit: int = min(request.args.get("limit", 100, type=int), 1000)

    if level and level not in _LEVELS:
        return jsonify({"error": "invalid_input", "message": f"Invalid log level. Supported: {', '.join(sorted(_LEVELS))}"}), 400

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        logs = adapter.get_logs(limit=limit) or []

        if level:
            norm_level = "warn" if level == "warning" else level
            logs = [entry for entry in logs if entry.get("level", "").lower() == norm_level]

        return jsonify({"success": True, "logs": logs, "count": len(logs)})
    except Exception as e:
        current_app.logger.error("Failed to retrieve logs: {}", e)
        return jsonify({"error": "log_error", "message": str(e)}), 500


@logs_bp.route("/export", methods=["GET"])
@jwt_required
def export():
    """Export server logs as a downloadable plain-text file.

    Reads the raw ``logs/latest.log`` file for the most complete export.
    Falls back to the in-memory console buffer.

    Query params:
      - level (str): optional filter by level.
      - limit (int, default 5000): max lines to export (max 50000).
    """
    level: str = request.args.get("level", "").strip().lower()
    limit: int = min(request.args.get("limit", 5000, type=int), 50000)

    adapter = _get_adapter()
    if adapter is None:
        return jsonify({"error": "not_available", "message": "MC adapter not available"}), 503

    try:
        # Try reading the raw log file first (preserves original formatting)
        log_path = Path("logs/latest.log")
        if log_path.is_file():
            raw = log_path.read_text(encoding="utf-8", errors="replace")
            lines = raw.splitlines()
        else:
            # Fallback to parsed logs
            logs = adapter.get_logs(limit=limit) or []
            lines = [f"[{e.get('time', '')}] [{e.get('level', 'INFO')}] {e.get('message', '')}" for e in logs]

        if level:
            norm_level = "warn" if level == "warning" else level.upper()
            lines = [l for l in lines if f" {norm_level}]" in l or f" {norm_level}:" in l]

        # Apply limit (most recent lines)
        if len(lines) > limit:
            lines = lines[-limit:]

        content: str = "\n".join(lines)
        return Response(
            content,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=server_logs.txt"},
        )
    except Exception as e:
        current_app.logger.error("Failed to export logs: {}", e)
        return jsonify({"error": "export_error", "message": str(e)}), 500


@logs_bp.route("/clear", methods=["POST"])
@jwt_required
@csrf_protect
def clear():
    """Clear (truncate) the server log file.

    Truncates ``logs/latest.log``.  The Minecraft server will continue
    writing to the file after it is cleared.
    """
    log_path = Path("logs/latest.log")
    try:
        if log_path.is_file():
            log_path.write_text("", encoding="utf-8")
        return jsonify({"success": True, "message": "Server logs cleared"})
    except OSError as e:
        current_app.logger.error("Failed to clear logs: {}", e)
        return jsonify({"error": "clear_error", "message": str(e)}), 500
