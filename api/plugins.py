"""Plugin management API endpoints.

Provides REST endpoints for listing, uploading, deleting, and toggling
PaperMC plugins.  All endpoints require JWT authentication; write
operations additionally require a valid CSRF token.

Registered at ``/api/server/plugins``.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from api.middleware.auth import jwt_required
from api.middleware.csrf import csrf_protect
from core.mcserver.plugins import PluginManager

plugins_bp = Blueprint("plugins", __name__, url_prefix="/api/server/plugins")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_manager() -> PluginManager:
    """Create a PluginManager pointing at the standard plugins directory."""
    return PluginManager("server/plugins")


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@plugins_bp.route("", methods=["GET"])
@jwt_required
def list_plugins():
    """List all installed plugins with metadata.

    Returns:
        JSON: ``{success, plugins, plugin_dir, count}``.
    """
    try:
        pm = _get_manager()
        plugins = pm.list_plugins()
        return jsonify({
            "success": True,
            "plugins": plugins,
            "plugin_dir": str(pm.get_plugins_dir()),
            "count": len(plugins),
        })
    except Exception as exc:
        current_app.logger.error(f"Failed to list plugins: {exc}")
        return jsonify({"error": "server_error", "message": "服务器内部错误"}), 500


@plugins_bp.route("/upload", methods=["POST"])
@jwt_required
@csrf_protect
def upload_plugin():
    """Upload a plugin jar file.

    Accepts ``multipart/form-data`` with a ``file`` field.

    Returns:
        JSON: ``{success, message, filename}``.

    Error codes:
        400 – missing file or invalid filename
        409 – plugin already exists
        413 – file too large
        500 – write error
    """
    try:
        uploaded = request.files.get("file")
        if uploaded is None:
            return jsonify({"error": "missing_file", "message": "未提供文件"}), 400

        # Validate raw filename BEFORE sanitisation (defense-in-depth)
        raw_name = (uploaded.filename or "").strip()
        if not PluginManager.validate_plugin_name(raw_name):
            return jsonify({"error": "invalid_name", "message": "文件名包含非法字符"}), 400

        if not raw_name.lower().endswith(".jar"):
            return jsonify({"error": "invalid_type", "message": "仅支持 .jar 文件"}), 400

        # Sanitise for safe filesystem use (secondary pass after our own validation)
        filename = secure_filename(raw_name)
        if not filename or not filename.lower().endswith(".jar"):
            return jsonify({"error": "invalid_name", "message": "文件名无效"}), 400

        data = uploaded.read()

        pm = _get_manager()
        try:
            pm.upload_plugin(filename, data)
        except ValueError as exc:
            # Plugin already exists or invalid name
            status = 409 if "已存在" in str(exc) else 400
            return jsonify({"error": "upload_failed", "message": str(exc)}), status

        current_app.logger.info(f"Plugin uploaded: {filename}")

        return jsonify({
            "success": True,
            "message": f"插件 {filename} 上传成功",
            "filename": filename,
        })
    except Exception as exc:
        current_app.logger.error(f"Plugin upload error: {exc}", exc_info=True)
        return jsonify({"error": "upload_error", "message": "上传失败，请重试"}), 500


@plugins_bp.route("/delete", methods=["POST"])
@jwt_required
@csrf_protect
def delete_plugin():
    """Delete a plugin jar file.

    Accepts JSON body: ``{"filename": "EssentialsX.jar"}``.

    Returns:
        JSON: ``{success, message, filename}``.
    """
    try:
        body = request.get_json(silent=True) or {}
        filename = body.get("filename", "").strip()

        if not filename:
            return jsonify({"error": "missing_filename", "message": "未指定文件名"}), 400

        pm = _get_manager()
        try:
            pm.delete_plugin(filename)
        except ValueError as exc:
            return jsonify({"error": "invalid_name", "message": str(exc)}), 400
        except FileNotFoundError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404

        current_app.logger.info(f"Plugin deleted: {filename}")

        return jsonify({
            "success": True,
            "message": f"插件 {filename} 已删除",
            "filename": filename,
        })
    except Exception as exc:
        current_app.logger.error(f"Plugin delete error: {exc}", exc_info=True)
        return jsonify({"error": "delete_error", "message": "删除失败，请重试"}), 500


@plugins_bp.route("/toggle", methods=["POST"])
@jwt_required
@csrf_protect
def toggle_plugin():
    """Toggle a plugin between enabled (.jar) and disabled (.jar.disabled).

    Accepts JSON body: ``{"filename": "EssentialsX.jar"}``.

    Returns:
        JSON: ``{success, message, filename, disabled}``.
    """
    try:
        body = request.get_json(silent=True) or {}
        filename = body.get("filename", "").strip()

        if not filename:
            return jsonify({"error": "missing_filename", "message": "未指定文件名"}), 400

        pm = _get_manager()
        try:
            pm.toggle_plugin(filename)
        except ValueError as exc:
            return jsonify({"error": "toggle_failed", "message": str(exc)}), 400
        except FileNotFoundError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404

        # Determine the new state
        now_disabled = filename.endswith(".jar")  # we toggled FROM .jar → now disabled

        current_app.logger.info(
            f"Plugin toggled: {filename} → {'disabled' if now_disabled else 'enabled'}"
        )

        return jsonify({
            "success": True,
            "message": f"插件 {'已禁用' if now_disabled else '已启用'}",
            "filename": filename,
            "disabled": now_disabled,
        })
    except Exception as exc:
        current_app.logger.error(f"Plugin toggle error: {exc}", exc_info=True)
        return jsonify({"error": "toggle_error", "message": "操作失败，请重试"}), 500
