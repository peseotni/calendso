"""Optional single-password authentication (session cookie + feed token)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from . import settings_store
from .config import get_config

COOKIE = "studio_session"
SESSION_DAYS = 30
PUBLIC_PATHS = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout"}
# Paths that accept ?token=<feed token> (podcast apps cannot log in).
TOKEN_PATHS = re.compile(r"^/feeds/|^/api/books/\d+/(?:files/\d+|cover)$")
ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_hash(password: str, stored: str) -> bool:
    try:
        _algo, iterations, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _password_fingerprint() -> str:
    env = get_config().password
    source = env if env else settings_store.current().password_hash
    return hashlib.sha256((source or "").encode()).hexdigest()[:16]


def auth_enabled() -> bool:
    return bool(get_config().password or settings_store.current().password_hash)


def check_password(password: str) -> bool:
    env = get_config().password
    if env:
        return hmac.compare_digest(password.encode(), env.encode())
    stored = settings_store.current().password_hash
    return bool(stored) and verify_hash(password, stored)


def _sign(payload: str) -> str:
    key = get_config().get_secret_key().encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def create_session_token() -> str:
    payload = json.dumps({"exp": int(time.time()) + SESSION_DAYS * 86400, "pw": _password_fingerprint()})
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{encoded}.{_sign(encoded)}"


def valid_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    encoded, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(encoded)):
        return False
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, TypeError):
        return False
    return payload.get("exp", 0) > time.time() and payload.get("pw") == _password_fingerprint()


def valid_feed_token(token: str | None) -> bool:
    expected = settings_store.current().feed_token
    return bool(token and expected) and hmac.compare_digest(token, expected)


def _cookie(scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            cookie = SimpleCookie()
            try:
                cookie.load(value.decode("latin-1"))
            except Exception:  # noqa: BLE001
                return None
            morsel = cookie.get(COOKIE)
            return morsel.value if morsel else None
    return None


class AuthMiddleware:
    """Pure ASGI middleware (keeps streaming/range responses untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path: str = scope.get("path", "")
        protected = path.startswith("/api/") or path.startswith("/feeds/")
        if not protected or path in PUBLIC_PATHS or not auth_enabled():
            return await self.app(scope, receive, send)
        if valid_session(_cookie(scope)):
            return await self.app(scope, receive, send)
        if TOKEN_PATHS.match(path) and scope.get("method") in ("GET", "HEAD"):
            query = parse_qs(scope.get("query_string", b"").decode())
            if valid_feed_token((query.get("token") or [None])[0]):
                return await self.app(scope, receive, send)
        body = json.dumps({"detail": "Authentication required"}).encode()
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
