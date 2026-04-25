import hashlib
import hmac
import os
import secrets


def _resolve_session_secret():
    """Return a secure secret for HMAC session tokens.
    Production (RENDER or FLASK_ENV=production): SESSION_SECRET must be set.
    Dev: generates an ephemeral random secret per process — sessions don't
    survive restarts but no key reuse across deployments."""
    secret = os.environ.get('SESSION_SECRET')
    if secret:
        return secret
    is_production = os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production'
    if is_production:
        raise RuntimeError(
            "SESSION_SECRET environment variable is required in production. "
            "Set it to a long random string (e.g. `openssl rand -hex 32`)."
        )
    print("WARNING: SESSION_SECRET not set; using ephemeral dev secret. "
          "Sessions will not persist across restarts.")
    return secrets.token_hex(32)


_SESSION_SECRET = _resolve_session_secret()


def make_session_token(username):
    """Generate an HMAC token for a username to prevent session forgery."""
    return hmac.new(_SESSION_SECRET.encode(), username.encode(), hashlib.sha256).hexdigest()


def verify_session(session_data):
    """Verify that session data contains a valid HMAC token."""
    if not session_data or not isinstance(session_data, dict):
        return False
    username = session_data.get('username')
    token = session_data.get('token')
    if not username or not token:
        return False
    return hmac.compare_digest(token, make_session_token(username))