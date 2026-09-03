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
    create_user_session_token,
    decode_user_session_token,
    verify_csrf_token,
    verify_session_token,
)


from bot.dev_logs import setup_dev_logging


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
            dashboard_dev_users=[135489084385787905],
        )
        setup_dev_logging(data_dir, 10)
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
    assert "/balances/111/history" in resp.text
    assert "/balances/222/history" in resp.text

    # 4. Request with filter=zero -> 111 appears, 222 does not
    resp = client.get(f"/guild/{guild_id}/balances?filter_type=zero", headers=auth_headers)
    assert resp.status_code == 200
    assert "/balances/111/history" in resp.text
    assert "/balances/222/history" not in resp.text

    # 5. Request with filter=nonzero -> 222 appears, 111 does not
    resp = client.get(f"/guild/{guild_id}/balances?filter_type=nonzero", headers=auth_headers)
    assert resp.status_code == 200
    assert "/balances/222/history" in resp.text
    assert "/balances/111/history" not in resp.text

    # 6. Search specifically for 111 with filter=zero
    resp = client.get(f"/guild/{guild_id}/balances?q=111&filter_type=zero", headers=auth_headers)
    assert resp.status_code == 200
    assert "/balances/111/history" in resp.text


def test_departed_guild_members_filtering(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    class FakeMember:
        def __init__(self, uid, name):
            self.id = uid
            self.name = name
            self.display_name = name
            self.bot = False

    class FakeGuild:
        def __init__(self):
            self.id = guild_id
            self.name = "Test Guild"
            self.icon = None
            self.members = [FakeMember(1001, "ActiveMember")]
            self.member_count = 1

        def get_member(self, uid):
            return next((m for m in self.members if m.id == uid), None)

    mock_bot.get_guild = lambda gid: FakeGuild() if gid == guild_id else None

    # User 1001 is in guild, has 0 balance (default)
    # User 2002 is departed, has 500 balance
    # User 3003 is departed, has 0 balance (was credited then debited)
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": 2002, "operation": "credit", "amount": 500, "reason": "leftover"},
        headers=auth_headers,
    )
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": 3003, "operation": "credit", "amount": 100, "reason": "bonus"},
        headers=auth_headers,
    )
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": 3003, "operation": "debit", "amount": 100, "reason": "clear"},
        headers=auth_headers,
    )

    # 1. Filter ALL -> ActiveMember (1001) and Departed with balance (2002) appear. Departed with 0 balance (3003) does NOT appear.
    resp = client.get(f"/guild/{guild_id}/balances?filter_type=all", headers=auth_headers)
    assert resp.status_code == 200
    assert "/balances/1001/history" in resp.text
    assert "/balances/2002/history" in resp.text
    assert "/balances/3003/history" not in resp.text

    # 2. Filter LEFT -> Only 2002 appears
    resp = client.get(f"/guild/{guild_id}/balances?filter_type=left", headers=auth_headers)
    assert resp.status_code == 200
    assert "/balances/2002/history" in resp.text
    assert "/balances/1001/history" not in resp.text
    assert "/balances/3003/history" not in resp.text

    # 3. Filter ZERO -> Only 1001 appears
    resp = client.get(f"/guild/{guild_id}/balances?filter_type=zero", headers=auth_headers)
    assert resp.status_code == 200
    assert "/balances/1001/history" in resp.text
    assert "/balances/2002/history" not in resp.text


async def test_user_session_token_and_auth(temp_env):
    mock_bot, app, client = temp_env
    secret = "secret-dashboard-token"

    # Set allowed users whitelist in bot config
    object.__setattr__(mock_bot.config, "dashboard_allowed_users", [135489084385787905, 656540896040452107])

    from bot.web.auth import create_user_session_token, decode_user_session_token, is_user_authorized

    # 1. Test whitelist check
    assert await is_user_authorized(mock_bot, 135489084385787905) is True
    assert await is_user_authorized(mock_bot, 656540896040452107) is True
    assert await is_user_authorized(mock_bot, 999999999999999999) is False

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
    client.cookies.set("eradicateur_session", cookie_val)
    resp = client.get("/", follow_redirects=True)
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

    # Check member history (in default dev mode)
    resp = client.get(
        f"/guild/{guild_id}/balances/999888/history",
        cookies={"eradicateur_session": user_cookie, "dev_simulated_role": "dev"},
    )
    assert "DEV 😎" in resp.text

    # Perform transaction in leader simulated role
    resp = client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "csrf_token": csrf,
            "discord_id": 999888,
            "operation": "credit",
            "amount": 100000,
            "reason": "Leader bonus",
        },
        cookies={"eradicateur_session": user_cookie, "dev_simulated_role": "leader"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Check member history in leader mode: author should show real username/display_name and not Dev
    resp = client.get(
        f"/guild/{guild_id}/balances/999888/history",
        cookies={"eradicateur_session": user_cookie, "dev_simulated_role": "leader"},
    )
    assert "Leader bonus" in resp.text
    assert "Redn0" in resp.text


def test_db_audit_logging_and_logs_view(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Credit without reason fails with 400
    resp_bad = client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "discord_id": 777666,
            "operation": "credit",
            "amount": 100000,
            "reason": "",
        },
        headers=auth_headers,
    )
    assert resp_bad.status_code == 400

    # 2. Perform a valid manual credit transaction
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "discord_id": 777666,
            "operation": "credit",
            "amount": 100000,
            "reason": "Reward test",
        },
        headers=auth_headers,
    )

    # 3. Perform a manual debit transaction without specifying a reason (should default to "Manual withdrawal")
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "discord_id": 777666,
            "operation": "debit",
            "amount": 20000,
            "reason": "",
        },
        headers=auth_headers,
    )

    # 4. View guild logs via /guild/{guild_id}/logs?log_type=guild
    resp = client.get(f"/guild/{guild_id}/logs?log_type=guild", headers=auth_headers)
    assert resp.status_code == 200
    assert "[Dash]" in resp.text
    assert "BALANCE_CREDIT" in resp.text
    assert "BALANCE_DEBIT" in resp.text
    assert "777666" in resp.text

    # 5. Global logs (bot.log) should NOT contain this guild action
    resp_global = client.get(f"/guild/{guild_id}/logs?log_type=global", headers=auth_headers)
    assert resp_global.status_code == 200
    assert "BALANCE_CREDIT" not in resp_global.text

    # 6. Check history contains [Dash] prefix and default reason
    resp_hist = client.get(f"/guild/{guild_id}/balances/777666/history", headers=auth_headers)
    assert resp_hist.status_code == 200
    assert "[Dash] Reward test" in resp_hist.text
    assert "[Dash] Manual withdrawal" in resp_hist.text


def test_dev_category_access_control(temp_env):
    mock_bot, app, client = temp_env
    secret = "secret-dashboard-token"
    guild_id = 123456

    object.__setattr__(mock_bot.config, "dashboard_allowed_users", [135489084385787905, 656540896040452107])
    object.__setattr__(mock_bot.config, "dashboard_dev_users", [135489084385787905])

    from bot.web.auth import create_user_session_token

    # 1. Dev user (135489084385787905)
    dev_cookie = create_user_session_token(
        {"id": 135489084385787905, "username": "redn0", "display_name": "Redn0", "avatar": None, "roles": ["admin"]},
        secret,
    )

    # 2. Non-dev authorized user (656540896040452107)
    non_dev_cookie = create_user_session_token(
        {"id": 656540896040452107, "username": "other_officer", "display_name": "Other", "avatar": None, "roles": ["officer"]},
        secret,
    )

    # Dev user on logs page sees DEV switcher buttons (Global Logs, System Errors)
    resp_dev_logs = client.get(f"/guild/{guild_id}/logs", cookies={"eradicateur_session": dev_cookie})
    assert resp_dev_logs.status_code == 200
    assert "Global Logs (bot.log)" in resp_dev_logs.text
    assert "System Errors (errors.log)" in resp_dev_logs.text
    assert "border-amber-800" in resp_dev_logs.text

    # Dev user can view global logs
    resp_dev_global = client.get(f"/guild/{guild_id}/logs?log_type=global", cookies={"eradicateur_session": dev_cookie})
    assert resp_dev_global.status_code == 200
    assert "Global Logs" in resp_dev_global.text

    # Non-dev user on logs page sees only standard Guild Logs, no dev switcher buttons
    resp_non_dev_logs = client.get(f"/guild/{guild_id}/logs", cookies={"eradicateur_session": non_dev_cookie})
    assert resp_non_dev_logs.status_code == 200
    assert "Global Logs (bot.log)" not in resp_non_dev_logs.text
    assert "System Errors (errors.log)" not in resp_non_dev_logs.text

    # Non-dev user trying to access log_type=global falls back to guild logs
    resp_non_dev_force_global = client.get(f"/guild/{guild_id}/logs?log_type=global", cookies={"eradicateur_session": non_dev_cookie})
    assert resp_non_dev_force_global.status_code == 200
    assert "Global Logs (bot.log)" not in resp_non_dev_force_global.text

    # Non-dev user cannot access /guild/{guild_id}/dev (403)
    resp_non_dev = client.get(f"/guild/{guild_id}/dev", cookies={"eradicateur_session": non_dev_cookie})
    assert resp_non_dev.status_code == 403


def test_multi_file_log_reading_and_stream(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    from pathlib import Path

    logs_dir = Path(mock_bot.config.data_dir) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create primary log file and rotated backup (.1)
    primary_log = logs_dir / f"guild_{guild_id}.log"
    backup_log = logs_dir / f"guild_{guild_id}.log.1"

    primary_log.write_text("2026-09-01 12:00:00 INFO bot: Primary log line 1\n", encoding="utf-8")
    backup_log.write_text("2026-09-01 11:00:00 INFO bot: Backup log line 2\n", encoding="utf-8")

    # 2. View logs page - both primary and backup lines must be present seamlessly
    resp = client.get(f"/guild/{guild_id}/logs", headers=auth_headers)
    assert resp.status_code == 200
    assert "Primary log line 1" in resp.text
    assert "Backup log line 2" in resp.text

    # 3. Stream endpoint test
    resp_stream = client.get(f"/guild/{guild_id}/logs/stream?log_type=guild", headers=auth_headers)
    assert resp_stream.status_code == 200
    assert "Primary log line 1" in resp_stream.text
    assert "Backup log line 2" in resp_stream.text


def test_language_switch_and_i18n(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Default language is French
    resp_fr = client.get(f"/guild/{guild_id}/logs", headers=auth_headers)
    assert resp_fr.status_code == 200
    assert "Tableau de bord Admin" in resp_fr.text
    assert "Vue d'ensemble" in resp_fr.text
    assert "Soldes & Joueurs" in resp_fr.text

    # 2. Switch language to English via /set-language/en
    resp_set = client.get("/set-language/en", headers={"Referer": f"/guild/{guild_id}/logs"}, follow_redirects=False)
    assert resp_set.status_code == 302
    assert "dashboard_lang=en" in resp_set.headers.get("set-cookie", "")

    # 3. Request with English cookie
    resp_en = client.get(
        f"/guild/{guild_id}/logs",
        headers=auth_headers,
        cookies={"dashboard_lang": "en"},
    )
    assert resp_en.status_code == 200
    assert "Admin Dashboard" in resp_en.text
    assert "Overview" in resp_en.text
    assert "Balances & Players" in resp_en.text


def test_create_payout_web_and_channel_config(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Update payout channel config via Web
    resp = client.post(
        f"/guild/{guild_id}/config/roles",
        data={
            "officer_role_id": "1111",
            "leader_role_id": "2222",
            "pay_add_permission_level": "officer",
            "payout_channel_id": "555555",
        },
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Check config page has payout channel
    resp = client.get(f"/guild/{guild_id}/config", headers=auth_headers)
    assert resp.status_code == 200
    assert "555555" in resp.text

    # 2. Create Payout via Web
    resp = client.post(
        f"/guild/{guild_id}/payouts/create",
        data={
            "bag_silvers": 2000000,
            "item_market_value": 10000000,
            "activity_cost": 500000,
            "participant_ids": "1001, 1002",
        },
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/payouts/1" in resp.headers["location"]

    # Check payout details page
    resp = client.get(f"/guild/{guild_id}/payouts/1", headers=auth_headers)
    assert resp.status_code == 200
    assert "Payout #1" in resp.text
    assert "1001" in resp.text
    assert "1002" in resp.text

    # 3. Create Payout with 0 silvers and 0 item value
    resp_zero = client.post(
        f"/guild/{guild_id}/payouts/create",
        data={
            "bag_silvers": 0,
            "item_market_value": 0,
            "activity_cost": 0,
            "participant_ids": "1001, 1002",
        },
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp_zero.status_code == 303
    assert "/payouts/2" in resp_zero.headers["location"]


def test_dashboard_role_permissions(temp_env):
    from bot.web.auth import create_user_session_token
    mock_bot, app, client = temp_env
    guild_id = 123456
    secret = mock_bot.config.session_secret

    officer_role = type("MockRole", (), {"id": 1111, "name": "Officer", "is_default": lambda s: False})()
    leader_role = type("MockRole", (), {"id": 2222, "name": "Leader", "is_default": lambda s: False})()

    class MockGuildMember:
        def __init__(self, uid: int, name: str, roles: list):
            self.id = uid
            self.name = name
            self.roles = roles
            self.guild_permissions = type("Perms", (), {"administrator": False})()

        def get_role(self, rid: int):
            return next((r for r in self.roles if r.id == rid), None)

    officer_member = MockGuildMember(101, "OfficerUser", [officer_role])
    leader_member = MockGuildMember(202, "LeaderUser", [leader_role])
    regular_member = MockGuildMember(303, "RegularUser", [])

    class MockDiscordGuild:
        def __init__(self):
            self.id = guild_id
            self.name = "Test Guild"
            self.owner_id = 999
            self.roles = [officer_role, leader_role]
            self.text_channels = []
            self.icon = None
            self.member_count = 3
            self.members = [officer_member, leader_member, regular_member]

        def get_member(self, uid: int):
            return next((m for m in self.members if m.id == uid), None)

    mock_bot.get_guild = lambda gid: MockDiscordGuild() if gid == guild_id else None

    # Setup roles in DB
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    resp = client.post(
        f"/guild/{guild_id}/config/roles",
        data={
            "officer_role_id": "1111",
            "leader_role_id": "2222",
            "pay_add_permission_level": "officer",
            "payout_channel_id": "",
        },
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Officer Session
    officer_token = create_user_session_token(
        {"id": 101, "username": "OfficerUser", "display_name": "Officer User", "avatar": None, "roles": []},
        secret,
    )

    # Leader Session
    leader_token = create_user_session_token(
        {"id": 202, "username": "LeaderUser", "display_name": "Leader User", "avatar": None, "roles": []},
        secret,
    )

    # Regular Member Session
    regular_token = create_user_session_token(
        {"id": 303, "username": "RegularUser", "display_name": "Regular User", "avatar": None, "roles": []},
        secret,
    )

    # 1. Access to /config:
    # Officer is forbidden
    client.cookies.set("eradicateur_session", officer_token)
    resp = client.get(f"/guild/{guild_id}/config")
    assert resp.status_code == 403

    # Leader can access
    client.cookies.set("eradicateur_session", leader_token)
    resp = client.get(f"/guild/{guild_id}/config")
    assert resp.status_code == 200

    # 2. Activity Pool modification:
    # Officer is forbidden
    client.cookies.set("eradicateur_session", officer_token)
    resp = client.post(
        f"/guild/{guild_id}/activity-pool/add",
        data={"label": "Tank"},
        headers={"X-CSRF-Token": create_csrf_token(secret)},
    )
    assert resp.status_code == 403

    # Leader can modify
    client.cookies.set("eradicateur_session", leader_token)
    resp = client.post(
        f"/guild/{guild_id}/activity-pool/add",
        data={"label": "Tank"},
        headers={"X-CSRF-Token": create_csrf_token(secret)},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # 3. Payout creation:
    # Officer can create payout
    client.cookies.set("eradicateur_session", officer_token)
    resp = client.post(
        f"/guild/{guild_id}/payouts/create",
        data={
            "bag_silvers": 1000000,
            "item_market_value": 0,
            "activity_cost": 0,
            "participant_ids": "101, 202",
        },
        headers={"X-CSRF-Token": create_csrf_token(secret)},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Regular member cannot create payout
    client.cookies.set("eradicateur_session", regular_token)
    resp = client.post(
        f"/guild/{guild_id}/payouts/create",
        data={
            "bag_silvers": 1000000,
            "item_market_value": 0,
            "activity_cost": 0,
            "participant_ids": "101, 202",
        },
        headers={"X-CSRF-Token": create_csrf_token(secret)},
    )
    assert resp.status_code == 403

    # 4. Balances transactions when pay_add_permission_level == 'leader':
    client.cookies.set("eradicateur_session", leader_token)
    client.post(
        f"/guild/{guild_id}/config/roles",
        data={
            "officer_role_id": "1111",
            "leader_role_id": "2222",
            "pay_add_permission_level": "leader",
            "payout_channel_id": "",
        },
        headers={"X-CSRF-Token": create_csrf_token(secret)},
        follow_redirects=False,
    )

    # Officer cannot execute manual transactions when level is 'leader'
    client.cookies.set("eradicateur_session", officer_token)
    resp = client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": "101", "operation": "credit", "amount": "50000", "reason": "Bonus"},
        headers={"X-CSRF-Token": create_csrf_token(secret)},
    )
    assert resp.status_code == 403

    # Leader can execute manual transactions
    client.cookies.set("eradicateur_session", leader_token)
    resp = client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": "101", "operation": "credit", "amount": "50000", "reason": "Bonus"},
        headers={"X-CSRF-Token": create_csrf_token(secret)},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_dev_role_simulation(temp_env):
    from bot.web.auth import create_user_session_token
    mock_bot, app, client = temp_env
    guild_id = 123456
    secret = mock_bot.config.session_secret

    # Dev user session
    dev_token = create_user_session_token(
        {"id": 135489084385787905, "username": "redn0", "display_name": "Redn0", "avatar": None, "roles": ["admin"]},
        secret,
    )
    client.cookies.set("eradicateur_session", dev_token)

    # 1. By default, dev has full powers
    resp = client.get(f"/guild/{guild_id}")
    assert resp.status_code == 200
    assert "Dev Role :" in resp.text
    assert "⚡ Dev (Pleins pouvoirs)" in resp.text

    resp_cfg = client.get(f"/guild/{guild_id}/config")
    assert resp_cfg.status_code == 200

    # 2. Dev switches to "officer" simulation via /set-dev-role/officer
    resp_switch = client.get("/set-dev-role/officer?redirect=/guild/123456", follow_redirects=False)
    assert resp_switch.status_code == 303
    assert "dev_simulated_role=officer" in resp_switch.headers.get("set-cookie", "")

    # With officer simulation, dev is forbidden from /config
    client.cookies = {"eradicateur_session": dev_token, "dev_simulated_role": "officer"}
    resp_cfg_sim = client.get(f"/guild/{guild_id}/config")
    assert resp_cfg_sim.status_code == 403

    # But dev can still see overview and switch role back in navbar, and DB path is hidden
    resp_ov = client.get(f"/guild/{guild_id}")
    assert resp_ov.status_code == 200
    assert "Dev Role :" in resp_ov.text
    assert "data/guilds/123456.db" not in resp_ov.text

    # 3. Dev switches to "leader" simulation
    resp_switch_ldr = client.get("/set-dev-role/leader?redirect=/guild/123456", follow_redirects=False)
    assert resp_switch_ldr.status_code == 303
    assert "dev_simulated_role=leader" in resp_switch_ldr.headers.get("set-cookie", "")

    client.cookies = {"eradicateur_session": dev_token, "dev_simulated_role": "leader"}
    resp_cfg_ldr = client.get(f"/guild/{guild_id}/config")
    assert resp_cfg_ldr.status_code == 200
    resp_ov_ldr = client.get(f"/guild/{guild_id}")
    assert "data/guilds/123456.db" not in resp_ov_ldr.text

    # 4. Dev switches back to "dev"
    client.cookies = {"eradicateur_session": dev_token, "dev_simulated_role": "dev"}
    resp_cfg_dev = client.get(f"/guild/{guild_id}/config")
    assert resp_cfg_dev.status_code == 200
    resp_ov_dev = client.get(f"/guild/{guild_id}")
    assert "data/guilds/123456.db" in resp_ov_dev.text

    # 5. Non-dev user does not see database file path in header banner
    regular_token = create_user_session_token(
        {"id": 444, "username": "regular", "display_name": "Regular", "avatar": None, "roles": []},
        secret,
    )
    client.cookies = {"eradicateur_session": regular_token}
    resp_regular = client.get(f"/guild/{guild_id}")
    assert resp_regular.status_code == 200
    assert "data/guilds/123456.db" not in resp_regular.text
    assert "btn_configure" not in resp_regular.text
    assert "Dev Role :" not in resp_regular.text


def test_transactions_history_tab_and_filters(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Create a few transactions (1 credit, 1 debit, 1 payout)
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": "111", "operation": "credit", "amount": "150000", "reason": "Bonus Guild Fight"},
        headers=auth_headers,
    )
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={"discord_id": "222", "operation": "debit", "amount": "50000", "reason": "Repair cost"},
        headers=auth_headers,
    )
    client.post(
        f"/guild/{guild_id}/payouts/create",
        data={
            "bag_silvers": 1000000,
            "item_market_value": 0,
            "activity_cost": 0,
            "participant_ids": "111, 222",
        },
        headers=auth_headers,
    )

    # 2. View Transactions page
    resp = client.get(f"/guild/{guild_id}/transactions", headers=auth_headers)
    assert resp.status_code == 200
    assert "Historique des Transactions" in resp.text
    assert "Bonus Guild Fight" in resp.text
    assert "Repair cost" in resp.text
    assert "Payout #" in resp.text
    assert "/transactions" in resp.text

    # 3. Test filter=credits
    resp_credits = client.get(f"/guild/{guild_id}/transactions?filter=credits", headers=auth_headers)
    assert resp_credits.status_code == 200
    assert "Bonus Guild Fight" in resp_credits.text
    assert "Repair cost" not in resp_credits.text

    # 4. Test filter=debits
    resp_debits = client.get(f"/guild/{guild_id}/transactions?filter=debits", headers=auth_headers)
    assert resp_debits.status_code == 200
    assert "Repair cost" in resp_debits.text
    assert "Bonus Guild Fight" not in resp_debits.text

    # 5. Test search query q=111
    resp_search = client.get(f"/guild/{guild_id}/transactions?q=111", headers=auth_headers)
    assert resp_search.status_code == 200
    assert "111" in resp_search.text

    # 6. Test HTMX partial request
    resp_htmx = client.get(
        f"/guild/{guild_id}/transactions?filter=all",
        headers={**auth_headers, "HX-Request": "true"},
    )
    assert resp_htmx.status_code == 200
    assert "transactions-table-container" in resp_htmx.text
    assert "<nav" not in resp_htmx.text  # Partial should not include full base layout


def test_activity_pool_edit_role(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Add a role to activity pool
    client.post(
        f"/guild/{guild_id}/activity-pool/add",
        data={"label": "Tank Initiator"},
        headers=auth_headers,
    )

    # 2. View activity pool page
    resp = client.get(f"/guild/{guild_id}/activity-pool", headers=auth_headers)
    assert resp.status_code == 200
    assert "Tank Initiator" in resp.text
    assert "editRoleModal" in resp.text

    # 3. Edit / rename the role
    resp_edit = client.post(
        f"/guild/{guild_id}/activity-pool/edit/1",
        data={"label": "Main Tank / Shotcaller"},
        headers=auth_headers,
        follow_redirects=True,
    )
    assert resp_edit.status_code == 200
    assert "Main Tank / Shotcaller" in resp_edit.text
    assert "Tank Initiator" not in resp_edit.text


def test_activity_pool_drag_and_drop_reorder(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Add multiple roles
    for r in ["Tank", "Healer", "DPS Fire", "DPS Frost"]:
        client.post(
            f"/guild/{guild_id}/activity-pool/add",
            data={"label": r},
            headers=auth_headers,
        )

    # 2. Test JSON reorder (drag and drop AJAX payload)
    resp_reorder = client.post(
        f"/guild/{guild_id}/activity-pool/reorder",
        json={"labels": ["DPS Frost", "Healer", "Tank", "DPS Fire"]},
        headers=auth_headers,
    )
    assert resp_reorder.status_code == 200
    assert resp_reorder.json()["success"] is True
    assert resp_reorder.json()["labels"] == ["DPS Frost", "Healer", "Tank", "DPS Fire"]

    # 3. View activity pool page to verify new order
    resp_view = client.get(f"/guild/{guild_id}/activity-pool", headers=auth_headers)
    assert resp_view.status_code == 200
    assert "DPS Frost" in resp_view.text
    assert "activityPoolList" in resp_view.text
    assert "Sortable" in resp_view.text


def test_dev_creator_signing_behavior(temp_env):
    from bot.web.auth import create_csrf_token, create_user_session_token

    mock_bot, app, client = temp_env
    guild_id = 123456
    dev_user_id = 135489084385787905
    secret = "secret-dashboard-token"

    dev_token = create_user_session_token(
        {
            "id": dev_user_id,
            "username": "superdev",
            "display_name": "SuperDev",
            "avatar": None,
            "roles": [101],
        },
        secret,
    )
    csrf = create_csrf_token(secret)

    # 1. Dev user in DEV mode creates a transaction -> created_by should be 0, displayed as "😎 DEV 😎"
    client.cookies = {"eradicateur_session": dev_token, "dev_simulated_role": "dev"}
    resp_tx_dev = client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "csrf_token": csrf,
            "discord_id": 999111,
            "operation": "credit",
            "amount": 250000,
            "reason": "Dev Bonus",
        },
        follow_redirects=True,
    )
    assert resp_tx_dev.status_code == 200

    resp_hist = client.get(f"/guild/{guild_id}/balances/999111/history")
    assert resp_hist.status_code == 200
    assert "DEV 😎" in resp_hist.text

    # 2. Dev user switches to "officer" mode and creates a transaction -> created_by should be dev_user_id
    client.cookies = {"eradicateur_session": dev_token, "dev_simulated_role": "officer"}
    resp_tx_off = client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "csrf_token": csrf,
            "discord_id": 999111,
            "operation": "credit",
            "amount": 100000,
            "reason": "Officer Bonus",
        },
        follow_redirects=True,
    )
    assert resp_tx_off.status_code == 200

    resp_hist2 = client.get(f"/guild/{guild_id}/balances/999111/history")
    assert resp_hist2.status_code == 200
    assert "SuperDev" in resp_hist2.text


def test_void_payout_triggers_debit_dm_and_format_reason(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Create a payout
    resp_create = client.post(
        f"/guild/{guild_id}/payouts/create",
        data={
            "bag_silvers": 500_000,
            "item_market_value": 1_000_000,
            "activity_cost": 100_000,
            "participant_ids": "1001, 1002",
        },
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp_create.status_code == 303

    # 2. View member history: should format distribution reason with Payout badge link
    resp_hist = client.get(f"/guild/{guild_id}/balances/1001/history", headers=auth_headers)
    assert resp_hist.status_code == 200
    assert "Payout #1" in resp_hist.text
    assert f"/guild/{guild_id}/payouts/1" in resp_hist.text

    # 3. Void the payout
    resp_void = client.post(
        f"/guild/{guild_id}/payouts/1/void",
        headers=auth_headers,
        follow_redirects=False,
    )
    assert resp_void.status_code == 303

    # 4. View member history again: should show voided Payout badge link with line-through
    resp_hist_after = client.get(f"/guild/{guild_id}/balances/1001/history", headers=auth_headers)
    assert resp_hist_after.status_code == 200
    assert "line-through" in resp_hist_after.text
    assert "Payout #1" in resp_hist_after.text


def test_session_revocation_on_logout(temp_env):
    mock_bot, app, client = temp_env
    secret = "secret-dashboard-token"
    user_data = {"id": 12345, "username": "Tester", "display_name": "Tester", "roles": ["admin"]}
    token = create_user_session_token(user_data, secret)

    # Token should be valid initially
    assert decode_user_session_token(token, secret) is not None

    # Call /logout with cookie
    resp = client.get("/logout", cookies={"eradicateur_session": token}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"

    # Token must now be rejected as revoked
    assert decode_user_session_token(token, secret) is None


def test_csv_exports(temp_env):
    mock_bot, app, client = temp_env
    auth_headers = {"Authorization": "Bearer secret-dashboard-token"}
    guild_id = 123456

    # 1. Create a transaction so balance and history have data
    client.post(
        f"/guild/{guild_id}/balances/transaction",
        data={
            "discord_id": 555666,
            "operation": "credit",
            "amount": 250000,
            "reason": "Initial loot share",
        },
        headers=auth_headers,
    )

    # 2. Export Balances CSV
    resp_bal_csv = client.get(f"/guild/{guild_id}/balances/export.csv", headers=auth_headers)
    assert resp_bal_csv.status_code == 200
    assert "text/csv" in resp_bal_csv.headers["content-type"]
    assert "555666" in resp_bal_csv.text
    assert "250000" in resp_bal_csv.text

    # 3. Export Member History CSV
    resp_hist_csv = client.get(f"/guild/{guild_id}/balances/555666/history/export.csv", headers=auth_headers)
    assert resp_hist_csv.status_code == 200
    assert "text/csv" in resp_hist_csv.headers["content-type"]
    assert "Initial loot share" in resp_hist_csv.text

    # 4. Create payout and export Payouts CSV
    client.post(
        f"/guild/{guild_id}/payouts/create",
        data={
            "bag_silvers": 100_000,
            "item_market_value": 200_000,
            "activity_cost": 20_000,
            "participant_ids": "555666",
        },
        headers=auth_headers,
    )
    resp_payout_csv = client.get(f"/guild/{guild_id}/payouts/export.csv", headers=auth_headers)
    assert resp_payout_csv.status_code == 200
    assert "text/csv" in resp_payout_csv.headers["content-type"]
    assert "100000" in resp_payout_csv.text




















