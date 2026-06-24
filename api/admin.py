"""Admin API blueprint — authentication, password management, and audit logs.

The ``/login`` and ``/csrf-token`` endpoints are publicly accessible
(allowing the login flow to bootstrap authentication). All other routes
require JWT authentication, and state-changing POST routes also require
CSRF protection.
"""

import time

import bcrypt
from flask import Blueprint, current_app, jsonify, request, session

from api.middleware.auth import generate_token, get_current_user, jwt_required
from api.middleware.csrf import csrf_protect, generate_csrf_token

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# ---------------------------------------------------------------------------
# Rate limiter — per-IP AND per-username (critical behind frp, where all
# remote_addr look like 127.0.0.1).
# ---------------------------------------------------------------------------
_login_attempts: dict[str, list[float]] = {}       # IP → timestamps
_username_attempts: dict[str, list[float]] = {}     # username → timestamps
_USERNAME_LOCKOUT: dict[str, float] = {}             # username → locked until (epoch)
_RATE_LIMIT_WINDOW: int = 60       # seconds
_RATE_LIMIT_MAX: int = 10           # max attempts per window per IP
_USERNAME_MAX: int = 5              # max failed attempts per username per window
_USERNAME_LOCKOUT_SEC: int = 300    # lockout duration after exceeding _USERNAME_MAX


def _rate_limit(ip: str) -> bool:
    """Return True if the request is allowed, False if rate-limited (IP level)."""
    now: float = time.time()
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _RATE_LIMIT_WINDOW]
    if len(_login_attempts[ip]) >= _RATE_LIMIT_MAX:
        return False
    _login_attempts[ip].append(now)
    return True


def _username_rate_limit(username: str) -> bool:
    """Return True if login is allowed for this username, False if locked out.

    After _USERNAME_MAX failed attempts within _RATE_LIMIT_WINDOW, the
    username is locked for _USERNAME_LOCKOUT_SEC seconds.  This is the real
    protection when the panel sits behind frp (all requests share the same IP).
    """
    now: float = time.time()
    # Check lockout
    locked_until = _USERNAME_LOCKOUT.get(username, 0)
    if now < locked_until:
        return False
    # Prune + count recent failures
    if username not in _username_attempts:
        _username_attempts[username] = []
    _username_attempts[username] = [t for t in _username_attempts[username] if now - t < _RATE_LIMIT_WINDOW]
    if len(_username_attempts[username]) >= _USERNAME_MAX:
        _USERNAME_LOCKOUT[username] = now + _USERNAME_LOCKOUT_SEC
        return False
    return True


def _record_failed_attempt(username: str) -> None:
    """Record a failed login attempt against *username*."""
    now: float = time.time()
    if username not in _username_attempts:
        _username_attempts[username] = []
    _username_attempts[username].append(now)


def _check_admin_credentials(username: str, password: str) -> bool:
    """Verify credentials against the configured admin accounts.

    Passwords are stored as BCrypt hashes in the config file.
    """
    config = current_app.config.get("CONFIG", {})
    admins: list[dict] = config.get("admins", [])
    for admin in admins:
        if admin.get("username") == username:
            stored_hash: str = admin.get("password_hash", "")
            if not stored_hash:
                continue
            try:
                return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
            except (ValueError, TypeError):
                return False
    return False


def _get_audit_logger():
    """Return the audit logger from the current app, or None."""
    return getattr(current_app, "audit_logger", None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@admin_bp.route("/login", methods=["POST"])
def login():
    """Authenticate with username + password, returning a JWT token.

    Rate-limited per IP (10 attempts / 60 s) AND per username
    (5 failed attempts → 5 min lockout).  The username limiter is the
    real defence when the panel sits behind frp.
    """
    ip: str = request.remote_addr or "unknown"
    if not _rate_limit(ip):
        current_app.logger.warning("Login rate limit exceeded from IP: {}", ip)
        return jsonify({"error": "rate_limited", "message": "Too many login attempts. Please wait."}), 429

    data = request.get_json(silent=True) or request.form
    username: str = (data or {}).get("username", "").strip()
    password: str = (data or {}).get("password", "")

    if not username or not password:
        return jsonify({"error": "invalid_input", "message": "Username and password are required"}), 400

    # Username-level lockout check (critical: IP-based limit is useless behind frp)
    if not _username_rate_limit(username):
        current_app.logger.warning(
            "Login blocked — username '{}' is locked out (IP: {})", username, ip
        )
        return jsonify({
            "error": "rate_limited",
            "message": "Too many failed attempts for this account. Please wait 5 minutes.",
        }), 429

    if not _check_admin_credentials(username, password):
        _record_failed_attempt(username)
        # Add a small delay to frustrate timing-based enumeration
        time.sleep(0.5)
        return jsonify({"error": "auth_failed", "message": "Invalid username or password"}), 401

    config = current_app.config.get("CONFIG", {})
    jwt_secret: str = current_app.config.get("JWT_SECRET", "")
    session_timeout: int = config.get("web", {}).get("session_timeout", 3600)

    token: str = generate_token(username, jwt_secret, expiry=session_timeout)
    csrf_token: str = generate_csrf_token(current_app.config.get("SECRET_KEY", ""))

    # Set session cookie for page-based auth
    session["jwt_token"] = token
    session["csrf_token"] = csrf_token

    return jsonify({
        "success": True,
        "token": token,
        "csrf_token": csrf_token,
        "username": username,
        "expires_in": session_timeout,
    })


@admin_bp.route("/csrf-token", methods=["GET"])
def get_csrf_token():
    """Return a fresh CSRF token. Accessible without JWT auth."""
    secret_key: str = current_app.config.get("SECRET_KEY", "")
    token: str = generate_csrf_token(secret_key)
    return jsonify({"csrf_token": token})


@admin_bp.route("/change-password", methods=["POST"])
@jwt_required
@csrf_protect
def change_password():
    """Change the authenticated user's password.

    Requires the old password for verification. The new password is
    BCrypt-hashed before storage.
    """
    data = request.get_json(silent=True) or request.form
    old_password: str = (data or {}).get("old_password", "")
    new_password: str = (data or {}).get("new_password", "")

    if not old_password or not new_password:
        return jsonify({"error": "invalid_input", "message": "Both old_password and new_password are required"}), 400

    if len(new_password) < 6:
        return jsonify({"error": "invalid_input", "message": "New password must be at least 6 characters"}), 400

    username: str = get_current_user() or ""

    # Verify old password
    if not _check_admin_credentials(username, old_password):
        return jsonify({"error": "auth_failed", "message": "Old password is incorrect"}), 403

    # Hash new password
    new_hash: str = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    # Persist (delegate to the adapter / config manager)
    config_manager = getattr(current_app, "config_manager", None)
    if config_manager is None:
        return jsonify({"error": "not_available", "message": "Config manager not available"}), 503

    try:
        config_manager.update_admin_password(username, new_hash)
    except Exception as e:
        current_app.logger.error("Failed to update password for '{}': {}", username, e)
        return jsonify({"error": "update_failed", "message": str(e)}), 500

    # Audit log
    audit = _get_audit_logger()
    if audit is not None:
        try:
            audit.log(operator=username, action="change_password", ip=request.remote_addr or "", details=f"Password changed for user '{username}'")
        except Exception:
            pass

    return jsonify({"success": True, "message": "Password updated successfully"})


@admin_bp.route("/operation-log", methods=["GET"])
@jwt_required
def operation_log():
    """Return the operation audit log.

    Query params:
      - limit (int, default 50): max entries to return.
    """
    limit: int = request.args.get("limit", 50, type=int)

    audit = _get_audit_logger()
    if audit is None:
        return jsonify({"success": True, "logs": [], "count": 0})

    try:
        logs = audit.get_logs(limit=limit) or []
        return jsonify({"success": True, "logs": logs, "count": len(logs)})
    except Exception as e:
        current_app.logger.error("Failed to retrieve operation logs: {}", e)
        return jsonify({"error": "log_error", "message": str(e)}), 500


@admin_bp.route("/save-config", methods=["POST"])
@jwt_required
@csrf_protect
def save_config():
    """Save full application configuration from the setup wizard.

    Accepts JSON body with ``mc``, ``world``, ``tunnel``, and ``admin``
    sections.  Writes the merged config back to ``config/config.yaml``.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid_input", "message": "No config data provided"}), 400

    import yaml
    from pathlib import Path

    config_path = Path("config/config.yaml")

    try:
        # Read existing config
        if config_path.exists():
            raw: dict = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        else:
            raw = {}

        # Merge MC section
        mc_data = data.get("mc", {})
        if mc_data:
            raw.setdefault("mc", {}).update({
                k: v for k, v in mc_data.items() if k in (
                    "version", "port", "max_players", "jvm_args", "auto_restart"
                )
            })

        # Merge World section
        world_data = data.get("world", {})
        if world_data:
            raw.setdefault("world", {}).update({
                k: v for k, v in world_data.items() if k in (
                    "gamemode", "difficulty", "seed", "motd"
                )
            })

        # Merge Tunnel section
        tunnel_data = data.get("tunnel", {})
        if tunnel_data:
            raw.setdefault("tunnel", {}).update({
                "server_addr": tunnel_data.get("server_addr", ""),
                "server_port": tunnel_data.get("server_port", 7000),
            })
            # Standard frp: token
            if tunnel_data.get("mode") != "sakura":
                raw["tunnel"]["token"] = tunnel_data.get("token", "")
            # Sakura Frp: user
            if tunnel_data.get("mode") == "sakura" and tunnel_data.get("user"):
                raw["tunnel"]["user"] = tunnel_data["user"]
                raw["tunnel"]["sakura_mode"] = True
                raw["tunnel"]["login_fail_exit"] = False
            # Per-mapping overrides: remote_port + auth_pass
            mapping_data = tunnel_data.get("mapping", {})
            if mapping_data:
                raw.setdefault("tunnel", {}).setdefault("mapping", {})
                for key in ("mc_server", "mc_admin"):
                    if key in mapping_data:
                        raw["tunnel"]["mapping"].setdefault(key, {})
                        if "remote_port" in mapping_data[key]:
                            raw["tunnel"]["mapping"][key]["remote_port"] = mapping_data[key]["remote_port"]
                        if "auth_pass" in mapping_data[key]:
                            raw["tunnel"]["mapping"][key]["auth_pass"] = mapping_data[key]["auth_pass"]

        # Atomic write: temp file → os.replace
        import os
        import tempfile
        config_dir = str(config_path.parent)
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.dump(raw, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
            os.replace(tmp_path, str(config_path))
        except Exception:
            os.unlink(tmp_path)
            raise
        current_app.logger.info("Configuration saved by setup wizard")

        # Reload tunnel config so frpc uses the latest settings
        tunnel_mgr = getattr(current_app, "tunnel_manager", None)
        if tunnel_mgr is not None:
            try:
                ok = tunnel_mgr.reload_and_restart()
                if ok:
                    current_app.logger.info("隧道配置已重载并重启")
                else:
                    current_app.logger.warning("隧道重启失败，请稍后手动重启")
            except Exception as exc:
                current_app.logger.error("隧道重载异常: {}", exc)

        return jsonify({"success": True, "message": "配置已保存"})
    except Exception as e:
        current_app.logger.error("Failed to save config: {}", e)
        return jsonify({"error": "save_failed", "message": str(e)}), 500
