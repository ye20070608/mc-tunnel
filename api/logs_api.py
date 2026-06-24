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


@logs_bp.route("/recent", methods=["GET"])
@jwt_required
def recent():
    """Return recent server log lines (raw text, like the console window).

    Reads ``logs/latest.log`` directly and returns raw lines.

    Query params:
      - limit (int, default 500): max lines to return (newest).
    """
    limit: int = max(1, min(request.args.get("limit", 500, type=int), 2000))

    try:
        log_path = Path("logs/latest.log")
        if log_path.is_file():
            raw = log_path.read_text(encoding="utf-8", errors="replace")
            lines = raw.splitlines()
        else:
            lines = []

        # Return newest lines
        if len(lines) > limit:
            lines = lines[-limit:]

        return jsonify({"success": True, "lines": lines, "count": len(lines)})
    except Exception as e:
        current_app.logger.error("Failed to retrieve logs: {}", e)
        return jsonify({"error": "log_error", "message": str(e)}), 500


@logs_bp.route("/export", methods=["GET"])
@jwt_required
def export():
    """Export the FULL server log file as a downloadable plain-text file.

    Reads ``logs/latest.log`` entirely — no truncation, no filtering.
    """
    try:
        log_path = Path("logs/latest.log")
        if log_path.is_file():
            raw = log_path.read_text(encoding="utf-8", errors="replace")
        else:
            raw = ""

        return Response(
            raw,
            mimetype="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=server_logs.txt",
                "Content-Length": str(len(raw.encode("utf-8"))),
            },
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
