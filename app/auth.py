"""Password gate for the settings page and its sensitive API calls.

The password lives in `.env` (SETTINGS_PASSWORD=...) in the project root, never in git.
Login sets an HttpOnly cookie holding an HMAC derived from the password, so sessions survive service
restarts and are invalidated automatically when the password changes.
NOTE: the site is plain HTTP on your LAN - the password is not encrypted in transit.
"""
import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request

COOKIE = "pt_session"
MAX_AGE = 7 * 24 * 3600
_fails = {}   # ip -> [timestamps]


def password() -> str:
    return os.environ.get("SETTINGS_PASSWORD", "")


def configured() -> bool:
    return bool(password())


def _token() -> str:
    return hmac.new(("plane-tracker:" + password()).encode(), b"session-v1", hashlib.sha256).hexdigest()


def is_authed(request: Request) -> bool:
    if not configured():
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), _token())


def require_auth(request: Request):
    """Open when no password is configured (fresh install); otherwise needs a valid session."""
    if not is_authed(request):
        raise HTTPException(401, "login required")


def require_strict(request: Request):
    """For dangerous actions (Wi-Fi): refuse outright unless a password has been set AND entered."""
    if not configured():
        raise HTTPException(403, "Set SETTINGS_PASSWORD in the .env file to enable this feature")
    require_auth(request)


def check_login(request: Request, supplied: str) -> str:
    """Returns the session token, or raises 401/429. Throttles guessing per client IP."""
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 60]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many attempts - wait a minute")
    if not configured() or not hmac.compare_digest(supplied.encode(), password().encode()):
        recent.append(now)
        _fails[ip] = recent
        raise HTTPException(401, "Wrong password")
    _fails.pop(ip, None)
    return _token()
