import asyncio
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

from bot.config import Config
from bot.db_manager import GuildDatabaseManager
from bot.web.app import create_app
from bot.web.auth import create_session_token, verify_session_token


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


def test_auth_token_hashing():
    secret = "my-secret-key"
    token = create_session_token(secret)
    assert verify_session_token(token, secret) is True
    assert verify_session_token(token, "wrong-key") is False
    assert verify_session_token("invalid.token", secret) is False
    assert verify_session_token(None, secret) is False


def test_login_flow(temp_env):
    mock_bot, app, client = temp_env

    # 1. Access protected route unauthenticated -> redirects to /login
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"

    # 2. Access login page
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "DASHBOARD_TOKEN" in resp.text

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

    # Add manual transaction (Credit)
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

