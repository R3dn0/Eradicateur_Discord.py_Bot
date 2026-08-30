import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from typing import Annotated

import aiohttp
from fastapi import Cookie, HTTPException, Request, Response, status

logger = logging.getLogger("eradicateur_bot.web.auth")

SESSION_COOKIE_NAME = "eradicateur_session"
SESSION_MAX_AGE = 86400 * 30  # 30 days
CSRF_MAX_AGE = 86400  # 24 hours

# In-memory sliding-window rate limiter for login
_login_attempts: dict[str, list[float]] = {}


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def check_login_rate_limit(request: Request, max_attempts: int = 5, window_seconds: int = 60) -> bool:
    ip = _get_client_ip(request)
    now = time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < window_seconds]
    _login_attempts[ip] = attempts
    return len(attempts) < max_attempts


def record_login_failure(request: Request) -> None:
    ip = _get_client_ip(request)
    now = time.time()
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(now)
    if len(_login_attempts) > 1000:
        for k in list(_login_attempts.keys()):
            _login_attempts[k] = [t for t in _login_attempts[k] if now - t < 300]
            if not _login_attempts[k]:
                _login_attempts.pop(k, None)


def record_login_success(request: Request) -> None:
    ip = _get_client_ip(request)
    _login_attempts.pop(ip, None)


def _sign_data(data: str, secret: str) -> str:
    sig = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def _verify_data(signed_data: str, secret: str) -> str | None:
    try:
        data, sig = signed_data.rsplit(".", 1)
        expected_sig = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected_sig):
            return data
    except Exception:
        pass
    return None


def create_user_session_token(user_data: dict, secret: str) -> str:
    payload = {
        "id": int(user_data.get("id", 0)),
        "username": str(user_data.get("username", "Admin")),
        "display_name": str(user_data.get("display_name", user_data.get("username", "Admin"))),
        "avatar": user_data.get("avatar"),
        "roles": user_data.get("roles", []),
        "ts": int(time.time()),
    }
    raw_json = json.dumps(payload, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(raw_json.encode()).decode()
    return _sign_data(f"user:{encoded}", secret)


def decode_user_session_token(session_cookie: str | None, secret: str | None) -> dict | None:
    if not secret or not session_cookie:
        return None
    data = _verify_data(session_cookie, secret)
    if not data:
        return None

    # Modern multi-user session format
    if data.startswith("user:"):
        try:
            raw_encoded = data[5:]
            raw_json = base64.urlsafe_b64decode(raw_encoded.encode()).decode()
            payload = json.loads(raw_json)
            ts = int(payload.get("ts", 0))
            now = time.time()
            if (now - ts) > SESSION_MAX_AGE or ts > (now + 60):
                return None
            return payload
        except Exception:
            return None

    # Legacy auth:ts format (password login with created_by = 0)
    if data.startswith("auth:"):
        try:
            ts = int(data.split(":", 1)[1])
            now = time.time()
            if (now - ts) > SESSION_MAX_AGE or ts > (now + 60):
                return None
            return {
                "id": 0,
                "username": "Admin",
                "display_name": "Web Dashboard Admin",
                "avatar": None,
                "roles": ["admin"],
                "ts": ts,
            }
        except Exception:
            return None

    return None


def create_session_token(token: str) -> str:
    payload = {
        "id": 0,
        "username": "Admin",
        "display_name": "Web Dashboard Admin",
        "avatar": None,
        "roles": ["admin"],
    }
    return create_user_session_token(payload, token)


def verify_session_token(session_cookie: str | None, token: str | None) -> bool:
    return decode_user_session_token(session_cookie, token) is not None


def create_csrf_token(token: str) -> str:
    payload = f"csrf:{int(time.time())}"
    return _sign_data(payload, token)


def verify_csrf_token(csrf_token: str | None, token: str | None) -> bool:
    if not token or not csrf_token:
        return False
    data = _verify_data(csrf_token, token)
    if not data or not data.startswith("csrf:"):
        return False
    try:
        ts = int(data.split(":", 1)[1])
        now = time.time()
        if (now - ts) > CSRF_MAX_AGE or ts > (now + 60):
            return False
        return True
    except (ValueError, IndexError):
        return False


def set_user_auth_cookie(response: Response, user_data: dict, secret: str, secure: bool = False) -> None:
    session_val = create_user_session_token(user_data, secret)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_val,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def set_auth_cookie(response: Response, token: str, secure: bool = False) -> None:
    session_val = create_session_token(token)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_val,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
    )


def is_user_authorized(bot, user_id: int, user_roles: list[int] | None = None) -> bool:
    """
    Check if a Discord user is authorized to access the dashboard.
    Enforces whitelist: DASHBOARD_ALLOWED_USERS.
    Roles structure is ready for future multi-tier access control.
    """
    allowed_users = getattr(bot.config, "dashboard_allowed_users", [])
    if allowed_users:
        return user_id in allowed_users
    return False


def get_discord_oauth_url(bot, state: str) -> str | None:
    client_id = getattr(bot.config, "discord_client_id", None)
    redirect_uri = getattr(bot.config, "discord_redirect_uri", None)
    if not client_id or not redirect_uri:
        return None
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "none",
    }
    return f"https://discord.com/oauth2/authorize?{urllib.parse.urlencode(params)}"


async def exchange_discord_code(bot, code: str) -> dict | None:
    client_id = getattr(bot.config, "discord_client_id", None)
    client_secret = getattr(bot.config, "discord_client_secret", None)
    redirect_uri = getattr(bot.config, "discord_redirect_uri", None)
    if not client_id or not client_secret or not redirect_uri:
        return None

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with aiohttp.ClientSession() as session:
        async with session.post("https://discord.com/api/v10/oauth2/token", data=data, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            error_body = await resp.text()
            logger.error("Failed to exchange Discord OAuth2 code: HTTP %s - %s", resp.status, error_body)
            return None


async def fetch_discord_user(access_token: str) -> dict | None:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get("https://discord.com/api/v10/users/@me", headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def require_auth(
    request: Request,
    eradicateur_session: Annotated[str | None, Cookie()] = None,
) -> bool:
    bot = getattr(request.app.state, "bot", None)
    secret = getattr(bot.config, "session_secret", None) if bot else None
    expected_token = getattr(bot.config, "dashboard_token", None) if bot else None

    # Check Authorization header (for API / curl access)
    auth_header = request.headers.get("Authorization")
    if auth_header and expected_token:
        if auth_header.startswith("Bearer "):
            provided_token = auth_header[7:].strip()
        else:
            provided_token = auth_header.strip()
        if hmac.compare_digest(provided_token, expected_token):
            request.state.csrf_token = create_csrf_token(secret or expected_token)
            request.state.user = {
                "id": 0,
                "username": "API Admin",
                "display_name": "API Admin",
                "avatar": None,
                "roles": ["admin"],
            }
            return True

    # Check user session cookie
    user_payload = decode_user_session_token(eradicateur_session, secret)
    if user_payload:
        request.state.user = user_payload
        request.state.csrf_token = create_csrf_token(secret)

        # CSRF Protection for state-changing HTTP methods from cookie sessions
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            submitted_csrf = request.headers.get("X-CSRF-Token")
            if not submitted_csrf:
                try:
                    form = await request.form()
                    submitted_csrf = form.get("csrf_token")
                except Exception:
                    pass

            if not submitted_csrf or not verify_csrf_token(submitted_csrf, secret):
                logger.warning(
                    "CSRF token validation failed for IP %s on %s %s",
                    _get_client_ip(request),
                    request.method,
                    request.url.path,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or missing CSRF token. Please refresh the page.",
                )

        return True

    # If request is HTMX or API, return 401
    if request.headers.get("HX-Request") or request.headers.get("Accept") == "application/json":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"HX-Redirect": "/login"},
        )

    # Otherwise redirect to login
    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": "/login"},
    )


