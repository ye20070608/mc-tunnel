"""API route registration for the admin Flask application.

Calls to ``register_routes`` set up all API blueprints on the provided
Flask app instance together with their injected dependencies.
"""

from flask import Flask

from api.mc import mc_bp
from api.admin import admin_bp
from api.tunnel import tunnel_bp
from api.whitelist import whitelist_bp
from api.logs_api import logs_bp
from api.public import public_bp
from api.server import server_bp


def register_routes(
    app: Flask,
    mc_adapter=None,
    tunnel_manager=None,
    audit_logger=None,
    config_manager=None,
) -> None:
    """Register all API blueprints with the given Flask app.

    Stores the injected dependencies as app attributes so that
    blueprint views can access them via ``current_app``.

    Args:
        app: The Flask application instance (typically the admin app).
        mc_adapter: Adapter for MC server control (start/stop/status).
        tunnel_manager: Manager for frp tunnel configuration.
        audit_logger: Logger for sensitive-operation audit records.
        config_manager: Config file read/write for admin operations.
    """
    # Store dependencies on the app for blueprint access
    app.mc_adapter = mc_adapter
    app.tunnel_manager = tunnel_manager
    app.audit_logger = audit_logger
    app.config_manager = config_manager

    # Register all blueprints
    app.register_blueprint(mc_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(tunnel_bp)
    app.register_blueprint(whitelist_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(server_bp)
