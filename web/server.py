"""Flask web server — application factory and single-port runner.

Provides:
  - create_app ........... Base application factory (shared setup).
  - create_admin_app ..... App for admin dashboard + API + intro page (port 8443).
  - run_server ........... Starts the app on a single port using a daemon thread.

Usage::

    from web.server import run_server
    run_server(config, logger, mc_adapter, tunnel_manager, audit_logger)
"""

import os
import threading
from typing import Any

from flask import Flask, jsonify, render_template, request

from api.middleware.auth import jwt_required

from api.router import register_routes
from core.ssl import ensure_ssl_cert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_common_data(config: dict) -> dict:
    """Assemble the ``data`` dict injected into every Jinja2 template.

    The shape follows ``docs/前端设计/data.json`` so that templates can
    reference ``{{data.server.onlinePlayers}}``, ``{{data.intro.serverName}}``,
    etc. Static values come from config; dynamic values are placeholders
    that the frontend updates via AJAX polling.
    """
    mc_cfg = config.get("mc", {})
    web_cfg = config.get("web", {})
    intro_data = config.get("intro", {})
    tunnel_cfg = config.get("tunnel", {})

    return {
        "server": {
            "status": "unknown",
            "version": mc_cfg.get("version", "1.20.1"),
            "motd": intro_data.get("motd", ""),
            "onlinePlayers": 0,
            "maxPlayers": mc_cfg.get("max_players", 20),
            "tps": 20.0,
            "port": mc_cfg.get("port", 25565),
            "memory": {"used": "0G", "max": "4G", "percent": 0},
            "uptime": "N/A",
            "cpu": "N/A",
            "autoRestart": mc_cfg.get("auto_restart", True),
        },
        "intro": {
            "serverName": intro_data.get("server_name", "MC Server"),
            "slogan": intro_data.get("slogan", ""),
            "description": intro_data.get("description", ""),
            "rules": intro_data.get("rules", []),
            "features": intro_data.get("features", []),
            "version": mc_cfg.get("version", "1.20.1"),
        },
        "tunnel": {
            "status": "disconnected",
            "server": tunnel_cfg.get("server_addr", "N/A"),
            "uptime": "N/A",
            "activeTunnels": 0,
            "mappings": [],
        },
        "config": {
            "mcPort": mc_cfg.get("port", 25565),
            "adminPort": web_cfg.get("admin_port", 8443),
            "maxPlayers": mc_cfg.get("max_players", 20),
            "jvmArgs": mc_cfg.get("jvm_args", ""),
            "autoRestart": mc_cfg.get("auto_restart", True),
            "sessionTimeout": web_cfg.get("session_timeout", 3600),
        },
    }


def _get_jwt_secret(config: dict) -> str:
    """Return the JWT signing key, generating a random one if absent."""
    secret: str = config.get("web", {}).get("jwt_secret", "")
    if not secret:
        secret = os.urandom(32).hex()
    return secret


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {}


def create_app(config: dict, logger) -> Flask:
    """Base Flask application factory with shared configuration.

    Sets up:
      - Secret keys (session, JWT, CSRF)
      - Common template context processor (``data``)
      - Error handlers (404, 500)
      - Session configuration

    Args:
        config: Application configuration dict (loaded from YAML).
        logger: Loguru or standard logger instance.

    Returns:
        Configured Flask application.
    """
    app = Flask(__name__)

    # --- Configuration ---
    web_cfg = config.get("web", {})
    secret_key: str = config.get("web", {}).get("secret_key", os.urandom(24).hex())
    jwt_secret: str = _get_jwt_secret(config)

    app.config["SECRET_KEY"] = secret_key
    app.config["JWT_SECRET"] = jwt_secret
    app.config["CSRF_ENABLED"] = web_cfg.get("csrf_enabled", True)
    app.config["CONFIG"] = config
    app.config["SESSION_COOKIE_NAME"] = "mc_tunnel_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if config.get("web", {}).get("ssl_enabled", True):
        app.config["SESSION_COOKIE_SECURE"] = True

    # Upload size limit (50 MB) — protects plugin upload endpoint
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    # Store logger
    app.logger = logger

    # --- Template context ---
    common_data: dict = _make_common_data(config)

    @app.context_processor
    def inject_common() -> dict:
        return {"data": common_data}

    # --- API request logger (via after_request — non-invasive) ---
    @app.after_request
    def _log_api(response):
        if request.path.startswith("/api/") and logger is not None:
            if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                logger.info(
                    "API: {} {} → {}",
                    request.method,
                    request.path,
                    response.status_code,
                )
            else:
                logger.debug(
                    "API: {} {} → {}",
                    request.method,
                    request.path,
                    response.status_code,
                )
        return response

    # --- Error handlers (return JSON for API paths, HTML otherwise) ---
    @app.errorhandler(404)
    def not_found(_e) -> tuple:
        if request.path.startswith("/api/"):
            return jsonify({"error": "not_found", "message": "Resource not found"}), 404
        return render_template("intro.html"), 404

    @app.errorhandler(413)
    def request_too_large(_e) -> tuple:
        if request.path.startswith("/api/"):
            return jsonify({"error": "too_large", "message": "文件过大，上传限制为 50 MB"}), 413
        return "<h1>413 — Request Entity Too Large</h1>", 413

    @app.errorhandler(500)
    def server_error(_e) -> tuple:
        if request.path.startswith("/api/"):
            return jsonify({"error": "server_error", "message": "Internal server error"}), 500
        return "<h1>500 — Internal Server Error</h1>", 500

    return app


def create_admin_app(
    config: dict,
    logger,
    mc_adapter=None,
    tunnel_manager=None,
    audit_logger=None,
    config_manager=None,
) -> Flask:
    """Create the admin dashboard application (port 8443).

    Serves:
      - GET  /login  ...... Login page (no auth required).
      - GET  /  ........... Admin dashboard (requires JWT auth).
      - All ``/api/*`` endpoints with JWT + CSRF protection.

    Args:
        config: Application configuration dict.
        logger: Logger instance.
        mc_adapter: MC server control adapter.
        tunnel_manager: Tunnel configuration manager.
        audit_logger: Audit log writer.
        config_manager: Config file read/write for admin operations.

    Returns:
        Configured Flask application with all routes registered.
    """
    app = create_app(config, logger)

    # --- Register all admin API blueprints (includes public_bp) ---
    register_routes(app, mc_adapter, tunnel_manager, audit_logger, config_manager)

    # --- Public page routes (no auth) ---

    @app.route("/intro")
    def intro_page():
        """Render the server introduction page (public, no auth)."""
        return render_template("intro.html")

    # --- Auth page routes ---

    @app.route("/login")
    def login_page():
        """Render the admin login page."""
        return render_template("login.html")

    @app.route("/")
    @app.route("/dashboard")
    @jwt_required
    def admin_dashboard():
        """Render the admin dashboard page (requires JWT auth)."""
        return render_template("admin.html")

    @app.route("/setup")
    @jwt_required
    def setup_wizard():
        """Render the 5-step configuration wizard (requires JWT auth)."""
        return render_template("setup.html")

    return app


# ---------------------------------------------------------------------------
# Dual-port runner
# ---------------------------------------------------------------------------

def run_server(
    config: dict,
    logger,
    mc_adapter=None,
    tunnel_manager=None,
    audit_logger=None,
    config_manager=None,
) -> None:
    """Start the Flask app on a single port with optional SSL.

    Runs in a daemon thread so the calling process can continue
    (monitoring MC server, tunnel, etc.).

    If ``ssl_enabled`` is True (the default), auto-generates a
    self-signed certificate on first run and serves via HTTPS.
    Falls back to HTTP if certificate generation fails.

    Args:
        config: Application configuration dict.
        logger: Logger instance.
        mc_adapter: MC server control adapter.
        tunnel_manager: Tunnel configuration manager.
        audit_logger: Audit log writer.
        config_manager: Config file read/write for admin operations.
    """
    app: Flask = create_admin_app(
        config, logger, mc_adapter, tunnel_manager, audit_logger, config_manager,
    )

    admin_port: int = config.get("web", {}).get("admin_port", 8443)
    web_cfg = config.get("web", {})
    ssl_enabled = web_cfg.get("ssl_enabled", True)

    # Build SSL context
    ssl_context = None
    scheme = "http"
    if ssl_enabled:
        cert_path = web_cfg.get("ssl_cert", "config/certs/cert.pem")
        key_path = web_cfg.get("ssl_key", "config/certs/key.pem")
        try:
            ensure_ssl_cert(cert_path, key_path, logger)
        except (FileNotFoundError, ValueError, OSError) as exc:
            logger.error("SSL setup failed: {}", exc)
            logger.warning("Falling back to HTTP (no SSL)")
        else:
            ssl_context = (str(cert_path), str(key_path))
            scheme = "https"

    server_thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1",
            port=admin_port,
            debug=False,
            use_reloader=False,
            ssl_context=ssl_context,
        ),
        daemon=True,
        name="web-server",
    )

    server_thread.start()

    logger.info("Web server listening on {}://127.0.0.1:{}", scheme, admin_port)
    logger.info("  - 介绍页:    {}://127.0.0.1:{}/intro", scheme, admin_port)
    logger.info("  - 管理后台:  {}://127.0.0.1:{}/dashboard", scheme, admin_port)
    if ssl_enabled and ssl_context is not None:
        logger.info("  - HTTPS enabled (self-signed certificate)")
    elif ssl_enabled:
        logger.info("  - HTTPS was requested but SSL setup failed; running HTTP")
    logger.info(
        "Production deployment: replace app.run() with waitress (Windows) or gunicorn (Linux)."
    )
