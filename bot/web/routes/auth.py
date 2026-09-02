import hmac
import logging
import secrets

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.web.auth import (
    check_login_rate_limit,
    clear_auth_cookie,
    create_csrf_token,
    decode_user_session_token,
    exchange_discord_code,
    fetch_discord_user,
    get_discord_oauth_url,
    is_user_authorized,
    record_login_failure,
    record_login_success,
    set_user_auth_cookie,
    verify_csrf_token,
)
from bot.web.i18n import get_web_locale, translate_web

logger = logging.getLogger("eradicateur_bot.web.auth")
router = APIRouter(tags=["Auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    bot = request.app.state.bot
    templates = request.app.state.templates
    secret = getattr(bot.config, "session_secret", None) if bot else None
    expected_token = getattr(bot.config, "dashboard_token", None) if bot else None

    session_cookie = request.cookies.get("eradicateur_session")
    if decode_user_session_token(session_cookie, secret):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    if secret:
        request.state.csrf_token = create_csrf_token(secret)

    discord_oauth_enabled = bool(
        getattr(bot.config, "discord_client_id", None)
        and getattr(bot.config, "discord_redirect_uri", None)
    )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "bot": bot,
            "error": None,
            "discord_oauth_enabled": discord_oauth_enabled,
            "password_login_enabled": bool(expected_token),
        },
    )


@router.get("/auth/discord/login")
async def discord_login(request: Request):
    bot = request.app.state.bot
    state = secrets.token_urlsafe(32)
    oauth_url = get_discord_oauth_url(bot, state)
    if not oauth_url:
        return RedirectResponse(url="/login?error=discord_not_configured")

    response = RedirectResponse(url=oauth_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="discord_oauth_state",
        value=state,
        max_age=300,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/auth/discord/callback")
async def discord_callback(request: Request, code: str = "", state: str = ""):
    bot = request.app.state.bot
    templates = request.app.state.templates
    secret = getattr(bot.config, "session_secret", None)
    stored_state = request.cookies.get("discord_oauth_state")

    locale = get_web_locale(request)
    if not state or not stored_state or state != stored_state:
        logger.warning("Discord OAuth2 state mismatch")
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "bot": bot,
                "error": str(translate_web("auth_err_state_mismatch", locale=locale)),
                "discord_oauth_enabled": True,
                "password_login_enabled": bool(getattr(bot.config, "dashboard_token", None)),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not code:
        return RedirectResponse(url="/login?error=no_code")

    # Exchange authorization code
    token_data = await exchange_discord_code(bot, code)
    if not token_data or "access_token" not in token_data:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "bot": bot,
                "error": str(translate_web("auth_err_discord_exchange", locale=locale)),
                "discord_oauth_enabled": True,
                "password_login_enabled": bool(getattr(bot.config, "dashboard_token", None)),
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Fetch user profile
    discord_user = await fetch_discord_user(token_data["access_token"])
    if not discord_user or "id" not in discord_user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "bot": bot,
                "error": str(translate_web("auth_err_discord_profile", locale=locale)),
                "discord_oauth_enabled": True,
                "password_login_enabled": bool(getattr(bot.config, "dashboard_token", None)),
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user_id = int(discord_user["id"])
    username = discord_user.get("username", f"User {user_id}")
    display_name = discord_user.get("global_name") or username
    avatar_hash = discord_user.get("avatar")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png"
        if avatar_hash
        else None
    )

    # Check Whitelist authorization
    if not is_user_authorized(bot, user_id):
        logger.warning(
            "Unauthorized Discord login attempt: %s (ID: %s)",
            display_name,
            user_id,
        )
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "bot": bot,
                "error": str(translate_web("auth_err_unauthorized", locale=locale, display_name=display_name, user_id=user_id)),
                "discord_oauth_enabled": True,
                "password_login_enabled": bool(getattr(bot.config, "dashboard_token", None)),
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # User authorized -> create session
    user_payload = {
        "id": user_id,
        "username": username,
        "display_name": display_name,
        "avatar": avatar_url,
        "roles": ["admin"],
    }

    logger.info("Authorized Discord login: %s (ID: %s)", display_name, user_id)
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    is_https = request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
    set_user_auth_cookie(response, user_payload, secret, secure=is_https)
    response.delete_cookie("discord_oauth_state")
    return response


@router.post("/login")
async def login_submit(
    request: Request,
    token: str = Form(...),
    csrf_token: str = Form(""),
):
    bot = request.app.state.bot
    templates = request.app.state.templates
    secret = getattr(bot.config, "session_secret", None)
    expected_token = getattr(bot.config, "dashboard_token", None) if bot else None

    # Rate limiting check (max 5 attempts per minute per IP)
    locale = get_web_locale(request)
    if not check_login_rate_limit(request, max_attempts=5, window_seconds=60):
        logger.warning("Rate limit exceeded for login attempt")
        if secret:
            request.state.csrf_token = create_csrf_token(secret)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "bot": bot,
                "error": str(translate_web("auth_err_rate_limit", locale=locale)),
                "discord_oauth_enabled": bool(getattr(bot.config, "discord_client_id", None)),
                "password_login_enabled": bool(expected_token),
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # Validate CSRF token for login if token is configured
    if secret and csrf_token:
        if not verify_csrf_token(csrf_token, secret):
            logger.warning("Invalid CSRF token during login")

    # Constant-time comparison to prevent timing attacks
    if not expected_token or not hmac.compare_digest(token.strip(), expected_token.strip()):
        record_login_failure(request)
        if secret:
            request.state.csrf_token = create_csrf_token(secret)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "bot": bot,
                "error": str(translate_web("auth_err_invalid_token", locale=locale)),
                "discord_oauth_enabled": bool(getattr(bot.config, "discord_client_id", None)),
                "password_login_enabled": bool(expected_token),
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    record_login_success(request)
    logger.info("Successful password login to dashboard")

    user_payload = {
        "id": 0,
        "username": "Admin",
        "display_name": "Web Dashboard Admin",
        "avatar": None,
        "roles": ["admin"],
    }

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    is_https = request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
    set_user_auth_cookie(response, user_payload, secret, secure=is_https)
    return response


@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    clear_auth_cookie(response)
    return response


@router.get("/set-language/{lang}")
async def set_language(request: Request, lang: str):
    referer = request.headers.get("Referer", "/")
    # Prevent open redirect
    if not referer.startswith("/") and not referer.startswith(str(request.base_url)):
        referer = "/"
    response = RedirectResponse(url=referer, status_code=status.HTTP_302_FOUND)
    if lang in ["fr", "en"]:
        response.set_cookie(
            key="dashboard_lang",
            value=lang,
            max_age=365 * 24 * 3600,
            httponly=False,
            samesite="lax",
        )
    return response


