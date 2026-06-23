"""JWT authentication middleware for Flask API routes.

Provides:
  - jwt_required decorator for protecting endpoints
  - generate_token / verify_token helper functions
  - get_current_user to retrieve the authenticated username

Page requests (Accept: text/html) that are unauthenticated receive a
302 redirect to the intro page. API requests (Accept: application/json
or /api/ prefix) receive a 401 JSON response.
"""

import time
from functools import wraps
from typing import Optional

import jwt as pyjwt
from flask import current_app, g, redirect, request, jsonify, session


def generate_token(username: str, secret: str, expiry: int = 3600) -> str:
    """Generate a signed JWT for the given username.

    Args:
        username: The authenticated user's name.
        secret: HMAC signing key (HS256).
        expiry: Token lifetime in seconds (default 3600).

    Returns:
        Encoded JWT string.
    """
    payload: dict = {
        "username": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + expiry,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def verify_token(token: str, secret: str) -> Optional[dict]:
    """Decode and validate a JWT token.

    Args:
        token: The raw JWT string.
        secret: HMAC signing key matching the one used at creation.

    Returns:
        Decoded payload dict on success, None on failure.
    """
    try:
        return pyjwt.decode(token, secret, algorithms=["HS256"])
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return None


def get_current_user() -> Optional[str]:
    """Return the username from the current request's JWT, if any."""
    return getattr(g, "current_user", None)


def jwt_required(f):
    """Decorator that enforces JWT authentication.

    Behaviour depends on the request's Accept header:
      - text/html  -> 302 redirect to intro page (unauthenticated)
      - application/json or /api/ prefix -> 401 JSON response

    The authenticated username is stored in ``g.current_user``.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        token: Optional[str] = None

        # 1) Check Authorization: Bearer <token>
        auth_header: str = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        # 2) Fall back to session cookie
        if not token:
            token = session.get("jwt_token")

        # 3) Validate
        if token:
            secret: str = current_app.config.get("JWT_SECRET", "")
            payload: Optional[dict] = verify_token(token, secret)
            if payload is not None:
                g.current_user = payload["username"]
                return f(*args, **kwargs)

        # Determine response format
        accept: str = request.headers.get("Accept", "")
        # Three ways to detect API request:
        #   1. Path starts with /api/
        #   2. Accept header requests JSON
        #   3. Flask detected JSON body (Content-Type: application/json)
        is_api: bool = (
            request.path.startswith("/api/")
            or "application/json" in accept
            or request.is_json
        )

        if is_api:
            current_app.logger.warning(
                "JWT auth failed for API request: path={}, ip={}, accept={}",
                request.path,
                request.remote_addr,
                accept,
            )
            return jsonify({"error": "unauthorized", "message": "Authentication required"}), 401

        current_app.logger.info(
            "JWT auth failed for page request: path={}, redirecting to /login",
            request.path,
        )
        return redirect("/login")

    return decorated
