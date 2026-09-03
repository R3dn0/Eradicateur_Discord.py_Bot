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
# In-memory revocation cache for logged-out session tokens
_revoked_tokens: dict[str, float] = {}


def revoke_session_token(token: str | None) -> None:
    """Revoke a session token upon logout."""
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    _revoked_tokens[token_hash] = now + SESSION_MAX_AGE
    if len(_revoked_tokens) > 500:
        for k, expiry in list(_revoked_tokens.items()):
            if now > expiry:
                _revoked_tokens.pop(k, None)


def is_session_token_revoked(token: str | None) -> bool:
    """Check if a session token was explicitly revoked."""
    if not token:
        return False
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expiry = _revoked_tokens.get(token_hash)
    if expiry is None:
        return False
    if time.time() > expiry:
        _revoked_tokens.pop(token_hash, None)
        return False
    return True


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
    if is_session_token_revoked(session_cookie):
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


async def is_user_authorized(bot, user_id: int, user_roles: list[int] | None = None) -> bool:
    """
    Check if a Discord user is authorized to access the dashboard.
    Enforces whitelist: DASHBOARD_ALLOWED_USERS, dev accounts, server owner, server admins, leaders, or officers.
    """
    if not bot:
        return True
    if user_id == 0 or is_dev_user(bot, user_id):
        return True
    allowed_users = getattr(bot.config, "dashboard_allowed_users", [])
    if allowed_users and user_id in allowed_users:
        return True
    if hasattr(bot, "guilds"):
        for guild in bot.guilds:
            if getattr(guild, "owner_id", None) == user_id:
                return True
            member = guild.get_member(user_id)
            if not member and hasattr(guild, "fetch_member"):
                try:
                    member = await guild.fetch_member(user_id)
                except Exception:
                    member = None
            if member and getattr(member, "guild_permissions", None) and member.guild_permissions.administrator:
                return True
            if member and hasattr(bot, "db_manager") and bot.db_manager:
                try:
                    from bot.repositories.payout_config_repository import PayoutConfigRepository

                    conn = await bot.db_manager.get_connection(guild.id)
                    payout_cfg_repo = PayoutConfigRepository(conn)
                    cfg = await payout_cfg_repo.get_config()
                    if cfg.leader_role_id and member.get_role(cfg.leader_role_id):
                        return True
                    if cfg.officer_role_id and member.get_role(cfg.officer_role_id):
                        return True
                except Exception:
                    pass
    return False


async def get_user_guild_permissions(
    bot,
    guild_id: int,
    user_id: int,
    simulated_role: str | None = None,
) -> dict:
    """
    Computes permissions for a user within a specific guild:
    - is_dev: True if user in dashboard_dev_users or API admin (id=0)
    - If user is dev, supports simulation of 'dev', 'leader', or 'officer' roles.
    - is_admin: True if is_dev or Discord server admin / owner
    - is_leader: True if is_admin or has leader_role_id
    - is_officer: True if is_leader or has officer_role_id
    - can_manage_balances: is_leader if pay_add_permission_level == "leader" else is_officer
    - can_manage_payouts: is_officer
    - can_manage_config: is_leader
    - can_manage_activity_pool: is_leader
    """
    default_full_perms = {
        "is_dev": True,
        "is_simulated": False,
        "simulated_role": "dev",
        "is_admin": True,
        "is_leader": True,
        "is_officer": True,
        "can_manage_balances": True,
        "can_manage_payouts": True,
        "can_manage_config": True,
        "can_manage_activity_pool": True,
    }

    if not bot:
        return default_full_perms

    user_is_dev = (user_id == 0 or is_dev_user(bot, user_id))

    # 1. Dev Role Simulation
    if user_is_dev:
        if simulated_role == "leader":
            return {
                "is_dev": False,
                "is_simulated": True,
                "simulated_role": "leader",
                "is_admin": True,
                "is_leader": True,
                "is_officer": True,
                "can_manage_balances": True,
                "can_manage_payouts": True,
                "can_manage_config": True,
                "can_manage_activity_pool": True,
            }
        elif simulated_role == "officer":
            pay_add_level = "officer"
            if hasattr(bot, "db_manager") and bot.db_manager:
                try:
                    from bot.repositories.payout_config_repository import PayoutConfigRepository
                    conn = await bot.db_manager.get_connection(guild_id)
                    payout_cfg_repo = PayoutConfigRepository(conn)
                    cfg = await payout_cfg_repo.get_config()
                    pay_add_level = cfg.pay_add_permission_level
                except Exception:
                    pay_add_level = "officer"

            can_manage_balances = (pay_add_level == "officer")

            return {
                "is_dev": False,
                "is_simulated": True,
                "simulated_role": "officer",
                "is_admin": False,
                "is_leader": False,
                "is_officer": True,
                "can_manage_balances": can_manage_balances,
                "can_manage_payouts": True,
                "can_manage_config": False,
                "can_manage_activity_pool": False,
            }
        else:
            return default_full_perms

    guild = bot.get_guild(guild_id) if hasattr(bot, "get_guild") else None
    member = guild.get_member(user_id) if guild else None

    # If member not in memory cache, try fetching
    if guild and not member and hasattr(guild, "fetch_member"):
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None

    # Check Discord Administrator or Guild Owner
    is_server_admin = False
    if guild and getattr(guild, "owner_id", None) == user_id:
        is_server_admin = True
    elif member and getattr(member, "guild_permissions", None) and member.guild_permissions.administrator:
        is_server_admin = True

    is_leader = is_server_admin
    is_officer = is_server_admin
    pay_add_level = "officer"

    if hasattr(bot, "db_manager") and bot.db_manager:
        try:
            from bot.repositories.payout_config_repository import PayoutConfigRepository

            conn = await bot.db_manager.get_connection(guild_id)
            payout_cfg_repo = PayoutConfigRepository(conn)
            cfg = await payout_cfg_repo.get_config()
            pay_add_level = cfg.pay_add_permission_level

            if member:
                if cfg.leader_role_id and member.get_role(cfg.leader_role_id):
                    is_leader = True
                    is_officer = True
                if cfg.officer_role_id and member.get_role(cfg.officer_role_id):
                    is_officer = True
        except Exception as e:
            logger.warning("Error fetching payout config for permissions in guild %s: %s", guild_id, e)

    can_manage_balances = is_leader if pay_add_level == "leader" else is_officer
    can_manage_payouts = is_officer
    can_manage_config = is_leader
    can_manage_activity_pool = is_leader

    return {
        "is_dev": False,
        "is_admin": is_server_admin,
        "is_leader": is_leader,
        "is_officer": is_officer,
        "can_manage_balances": can_manage_balances,
        "can_manage_payouts": can_manage_payouts,
        "can_manage_config": can_manage_config,
        "can_manage_activity_pool": can_manage_activity_pool,
    }


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
                    "CSRF token validation failed on %s %s",
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


def is_dev_user(bot, user_id: int) -> bool:
    """Check if the user ID is in the whitelist of developer accounts."""
    if not bot or not user_id:
        return False
    dev_users = getattr(bot.config, "dashboard_dev_users", None) or [135489084385787905]
    return user_id in dev_users


async def require_dev_auth(
    request: Request,
    eradicateur_session: Annotated[str | None, Cookie()] = None,
) -> bool:
    """Require user to be logged in AND belong to dashboard_dev_users."""
    await require_auth(request, eradicateur_session)
    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    bot = getattr(request.app.state, "bot", None)

    if not is_dev_user(bot, user_id):
        logger.warning("Unauthorized DEV section access attempt by Discord ID %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to Developer Discord accounts.",
        )
    return True



