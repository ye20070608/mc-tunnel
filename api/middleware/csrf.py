"""CSRF protection middleware for Flask API routes.

Provides:
  - csrf_protect decorator for state-changing endpoints
  - generate_csrf_token for creating new tokens

Tokens are validated from the X-CSRF-Token header (JSON API requests)
or the ``csrf_token`` form field (HTML form submissions).
"""

import hashlib
import hmac
import time
from functools import wraps
from typing import Optional

from flask import current_app, request, jsonify


def generate_csrf_token(secret: str) -> str:
    """Create a time-bound CSRF token.

    Format: ``<timestamp>.<hmac_hex>`` where the HMAC signs the
    timestamp with the given secret.

    Args:
        secret: Secret key for HMAC signing (typically the app's SECRET_KEY).

    Returns:
        A CSRF token string valid for the session.
    """
    timestamp: str = str(int(time.time()))
    mac: str = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{timestamp}.{mac}"


def _verify_csrf_token(token: str, secret: str, max_age: int = 7200) -> bool:
    """Validate a CSRF token.

    Checks HMAC integrity and that the token is not older than max_age
    seconds (default 2 hours).

    Args:
        token: The token string (``<timestamp>.<hmac>``).
        secret: Secret key used at generation time.
        max_age: Maximum token age in seconds.

    Returns:
        True if valid, False otherwise.
    """
    try:
        timestamp_str, mac = token.rsplit(".", 1)
        expected: str = hmac.new(
            secret.encode("utf-8"),
            timestamp_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return False
        age: float = time.time() - float(timestamp_str)
        return age <= max_age
    except (ValueError, TypeError):
        return False


def csrf_protect(f):
    """Decorator that validates a CSRF token on state-changing requests.

    Reads the token from:
      1. The ``X-CSRF-Token`` request header (preferred for JSON APIs).
      2. The ``csrf_token`` form field (HTML forms).

    On failure returns a 403 JSON response.

    This decorator is intended for POST / PUT / PATCH / DELETE endpoints.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        # Skip CSRF check when the feature is disabled
        if not current_app.config.get("CSRF_ENABLED", True):
            return f(*args, **kwargs)

        token: Optional[str] = request.headers.get("X-CSRF-Token")
        if not token:
            token = request.form.get("csrf_token")

        if not token:
            return jsonify({"error": "csrf_required", "message": "CSRF token is missing"}), 403

        secret: str = current_app.config.get("SECRET_KEY", "")
        if not _verify_csrf_token(token, secret):
            return jsonify({"error": "csrf_invalid", "message": "CSRF token is invalid or expired"}), 403

        return f(*args, **kwargs)

    return decorated
