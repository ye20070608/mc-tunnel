"""Logs API blueprint — retrieve MC server logs, export, and clear them.

All endpoints require JWT authentication.
"""

import io
import zipfile
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
    """Export ALL log files as a downloadable ZIP archive.

    Collects every file under the ``logs/`` directory (``latest.log``,
    ``audit.log``, ``mc-tunnel.log``, rotated ``*.log.gz``, etc.) and
    packs them into an in-memory zip.  No truncation, no filtering.
    """
    try:
        logs_dir = Path("logs").resolve()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if logs_dir.is_dir():
                for fp in sorted(logs_dir.iterdir()):
                    # Skip symlinks to prevent reading outside logs/
                    if fp.is_symlink():
                        continue
                    if not fp.is_file():
                        continue
                    # Resolve to verify we stay within logs/
                    try:
                        resolved = fp.resolve()
                        if not str(resolved).startswith(str(logs_dir)):
                            continue
                    except (OSError, ValueError):
                        continue
                    # Read as binary so .gz files stay intact
                    zf.write(fp, fp.name)

        data = buf.getvalue()
        return Response(
            data,
            mimetype="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=server_logs_all.zip",
                "Content-Length": str(len(data)),
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
