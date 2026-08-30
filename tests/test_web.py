import asyncio
import shutil
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from bot.config import Config
from bot.db_manager import GuildDatabaseManager
from bot.web.app import create_app
from bot.web.auth import (
    _sign_data,
    create_csrf_token,
    create_session_token,
    verify_csrf_token,
    verify_session_token,
)


class MockBot:
    def __init__(self, data_dir: str, token: str = "secret-dashboard-token"):
        self.config = Config(
            discord_token="fake-discord-token",
            guild_id=[123456],
            data_dir=data_dir,
            log_level=10,
            dashboard_enabled=True,
            dashboard_host="0.0.0.0",
            dashboard_port=38291,
            dashboard_token=token,
        )
        self.db_manager = GuildDatabaseManager(data_dir)
        self.guilds = []

    def get_guild(self, guild_id: int):
        return None


@pytest.fixture
def temp_env():
    temp_dir = tempfile.mkdtemp()
    mock_bot = MockBot(temp_dir)
    app = create_app(mock_bot)
    client = TestClient(app)
    yield mock_bot, app, client
    # Cleanup DB connections
    asyncio.run(mock_bot.db_manager.close_all())
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_auth_token_hashing_and_expiration():
    secret = "my-secret-key"
    token = create_session_token(secret)
    assert verify_session_token(token, secret) is True
    assert verify_session_token(token, "wrong-key") is False
    assert verify_session_token("invalid.token", secret) is False
    assert verify_session_token(None, secret) is False

    # Test expired token
    old_payload = f"auth:{int(time.time()) - 86400 * 31}"  # 31 days old
    expired_token = _sign_data(old_payload, secret)
    assert verify_session_token(expired_token, secret) is False


def test_csrf_token_validation():
    secret = "my-secret-key"
    csrf = create_csrf_token(secret)
    assert verify_csrf_token(csrf, secret) is True
    assert verify_csrf_token(csrf, "wrong-secret") is False
    assert verify_csrf_token("invalid.csrf", secret) is False

    # Expired CSRF
    old_csrf = _sign_data(f"csrf:{int(time.time()) - 90000}", secret)
    assert verify_csrf_token(old_csrf, secret) is False


def test_security_headers(temp_env):
    mock_bot, app, client = temp_env
    resp = client.get("/login")
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "Content-Security-Policy" in resp.headers or "content-security-policy" in resp.headers


def test_login_flow(temp_env):
    mock_bot, app, client = temp_env

    # 1. Access protected route unauthenticated -> redirects to /login
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"

    # 2. Access login page
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Password / Token" in resp.text

    # 3. Post wrong password
    resp = client.post("/login", data={"token": "wrong_password"})
    assert resp.status_code == 401
    assert "invalide" in resp.text

    # 4. Post correct password
    resp = client.post("/login", data={"token": "secret-dashboard-token"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "eradicateur_session" in resp.cookies

    # 5. Access dashboard with session
    session_cookie = resp.cookies["eradicateur_session"]
    resp = client.get("/", cookies={"eradicateur_session": session_cookie})
    assert resp.status_code == 200


def test_bearer_token_auth(temp_env):
    mock_bot, app, client = temp_env

    # Valid Bearer
    resp = client.get("/", headers={"Authorization": "Bearer secret-dashboard-token"})
    assert resp.status_code == 200

    # Invalid Bearer
    resp = client.get("/", headers={"Authorization": "Bearer invalid"}, follow_redirects=False)
    assert resp.status_code == 302


def test_cookie_session_csrf_protection(temp_env):
    mock_bot, app, client = temp_env
    session_cookie = create_session_token("secret-dashboard-token")
    guild_id = 123456

    # 1. POST without CSRF token using cookie session -> 403 Forbidden
    resp = client.post(
        f"/guild/{guild_id}/config/rates",
        data={"tax_market": 2.0, "tax_guild": 10.0, "tax_transport": 3.0},
        cookies={"eradicateur_session": session_cookie},
    )
    assert resp.status_code == 403
    assert "CSRF" in resp.text

    # 2. POST with valid CSRF token -> 303 Redirect
    valid_csrf = create_csrf_token("secret-dashboard-token")
    resp = client.post(
        f"/guild/{guild_id}/config/rates",
        data={
            "csrf_token": valid_csrf,
            "tax_market": 2.0,
            "tax_guild": 10.0,
            "tax_transport": 3.0,
        },
        cookies={"eradicateur_session": session_cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_unknown_guild_rejection(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    unknown_gid = 99999999

    # Non-existent guild returns 404 and does not create database
    resp = client.get(f"/guild/{unknown_gid}", headers=auth_headers)
    assert resp.status_code == 404


def test_guild_overview_and_balances(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # Overview
    resp = client.get(f"/guild/{guild_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert f"Guild #{guild_id}" in resp.text

    # Balances view
    resp = client.get(f"/guild/{guild_id}/balances", headers=auth_headers)
    assert resp.status_code == 200

    # Add manual transaction (Credit) via Bearer API
    resp = client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "discord_id": 999111,
            "operation": "credit",
            "amount": 500000,
            "reason": "Test bonus",
        },
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Check member history
    resp = client.get(f"/guild/{guild_id}/balances/999111/history", headers=auth_headers)
    assert resp.status_code == 200
    assert "500 000" in resp.text
    assert "Test bonus" in resp.text


def test_config_updates(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # Update tax rates
    resp = client.post(
        f"/guild/{guild_id}/config/rates",
        data={
            "tax_market": 2.5,
            "tax_guild": 12.0,
            "tax_transport": 4.0,
        },
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Check config page
    resp = client.get(f"/guild/{guild_id}/config", headers=auth_headers)
    assert resp.status_code == 200
    assert "12.0" in resp.text or "12" in resp.text


def test_activity_pool_management(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # Add role
    resp = client.post(
        f"/guild/{guild_id}/activity-pool/add",
        data={"label": "🛡️ Tank Incub"},
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # View pool
    resp = client.get(f"/guild/{guild_id}/activity-pool", headers=auth_headers)
    assert resp.status_code == 200
    assert "Tank Incub" in resp.text

    # Clear pool
    resp = client.post(
        f"/guild/{guild_id}/activity-pool/clear",
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_zero_balances_and_filters(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Add credit of 100 to user 111, then debit of 100 (net balance = 0)
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": 111, "operation": "credit", "amount": 100, "reason": "bonus"},
        headers=auth_headers,
    )
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": 111, "operation": "debit", "amount": 100, "reason": "repay"},
        headers=auth_headers,
    )

    # 2. Add positive balance to user 222
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": 222, "operation": "credit", "amount": 500, "reason": "bonus"},
        headers=auth_headers,
    )

    # 3. Request with filter=all -> both 111 (0) and 222 (500) appear
    resp = client.get(f"/guild/{guild_id}/balances?filter_type=all", headers=auth_headers)
    assert resp.status_code == 200
    assert "111" in resp.text
    assert "222" in resp.text

    # 4. Request with filter=zero -> 111 appears, 222 does not
    resp = client.get(f"/guild/{guild_id}/balances?filter_type=zero", headers=auth_headers)
    assert resp.status_code == 200
    assert "111" in resp.text
    # 5. Request with filter=nonzero -> 222 appears, 111 does not
    resp = client.get(f"/guild/{guild_id}/balances?filter_type=nonzero", headers=auth_headers)
    assert resp.status_code == 200
    assert "222" in resp.text
    assert "111" not in resp.text

    # 6. Search specifically for 111 with filter=zero
    resp = client.get(f"/guild/{guild_id}/balances?q=111&filter_type=zero", headers=auth_headers)
    assert resp.status_code == 200
    assert "111" in resp.text


def test_discord_user_session_and_whitelist(temp_env):
    mock_bot, app, client = temp_env
    secret = "secret-dashboard-token"

    # Set allowed users whitelist in bot config
    object.__setattr__(mock_bot.config, "dashboard_allowed_users", [135489084385787905, 656540896040452107])

    from bot.web.auth import create_user_session_token, decode_user_session_token, is_user_authorized

    # 1. Test whitelist check
    assert is_user_authorized(mock_bot, 135489084385787905) is True
    assert is_user_authorized(mock_bot, 656540896040452107) is True
    assert is_user_authorized(mock_bot, 999999999999999999) is False

    # 2. Test user session creation and decoding
    user_data = {
        "id": 135489084385787905,
        "username": "redn0",
        "display_name": "Redn0",
        "avatar": "https://cdn.discordapp.com/avatars/135/abc.png",
        "roles": ["admin"],
    }
    cookie_val = create_user_session_token(user_data, secret)
    decoded = decode_user_session_token(cookie_val, secret)
    assert decoded is not None
    assert decoded["id"] == 135489084385787905
    assert decoded["display_name"] == "Redn0"

    # 3. Test browsing with Discord user session
    resp = client.get("/", cookies={"eradicateur_session": cookie_val})
    assert resp.status_code == 200
    assert "Redn0" in resp.text


def test_multi_user_transaction_created_by(temp_env):
    mock_bot, app, client = temp_env
    secret = "secret-dashboard-token"
    guild_id = 123456

    from bot.web.auth import create_csrf_token, create_user_session_token

    # Authenticate as Discord user Redn0 (ID: 135489084385787905)
    user_data = {
        "id": 135489084385787905,
        "username": "redn0",
        "display_name": "Redn0",
        "avatar": None,
        "roles": ["admin"],
    }
    user_cookie = create_user_session_token(user_data, secret)
    csrf = create_csrf_token(secret)

    # Perform manual credit transaction
    resp = client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "csrf_token": csrf,
            "discord_id": 999888,
            "operation": "credit",
            "amount": 250000,
            "reason": "Test bonus Redn0",
        },
        cookies={"eradicateur_session": user_cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Check member history
    resp = client.get(
        f"/guild/{guild_id}/balances/999888/history",
        cookies={"eradicateur_session": user_cookie},
    )
    assert resp.status_code == 200
    assert "250 000" in resp.text
    # Should record created_by = 135489084385787905
    assert "135489084385787905" in resp.text




