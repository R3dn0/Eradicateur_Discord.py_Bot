import hashlib
import hmac
import time
from typing import Annotated

from fastapi import Cookie, HTTPException, Request, Response, status

SESSION_COOKIE_NAME = "eradicateur_session"
SESSION_MAX_AGE = 86400 * 30  # 30 days


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


def create_session_token(token: str) -> str:
    payload = f"auth:{int(time.time())}"
    return _sign_data(payload, token)


def verify_session_token(session_cookie: str | None, token: str | None) -> bool:
    if not token:
        # If no token is configured, access is disabled or open
        return False
    if not session_cookie:
        return False
    verified = _verify_data(session_cookie, token)
    return verified is not None


def set_auth_cookie(response: Response, token: str) -> None:
    session_val = create_session_token(token)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_val,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True if exclusively HTTPS, False allows local/SSH tunneling
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
    )


async def require_auth(
    request: Request,
    eradicateur_session: Annotated[str | None, Cookie()] = None,
) -> bool:
    bot = getattr(request.app.state, "bot", None)
    expected_token = getattr(bot.config, "dashboard_token", None) if bot else None

    # Check Authorization header (for API / curl access)
    auth_header = request.headers.get("Authorization")
    if auth_header and expected_token:
        if auth_header.startswith("Bearer "):
            provided_token = auth_header[7:].strip()
        else:
            provided_token = auth_header.strip()
        if hmac.compare_digest(provided_token, expected_token):
            return True

    # Check cookie session
    if verify_session_token(eradicateur_session, expected_token):
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

