import aiosqlite
import pytest

from bot.repositories.bot_config_repository import (
    BotConfigRepository,
)


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "test.db"
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn


@pytest.fixture
async def repo(db):
    return BotConfigRepository(db)


@pytest.mark.asyncio
async def test_get_config_creates_defaults(repo):
    config = await repo.get_config()
    assert config.notification_opt_out_role_id is None
    assert config.updated_at is not None
    assert config.updated_by is None


@pytest.mark.asyncio
async def test_update_opt_out_role_persists(repo):
    await repo.update_opt_out_role(role_id=12345, updated_by=42)
    config = await repo.get_config()
    assert config.notification_opt_out_role_id == 12345
    assert config.updated_by == 42


@pytest.mark.asyncio
async def test_update_opt_out_role_can_clear(repo):
    await repo.update_opt_out_role(role_id=99999, updated_by=1)
    await repo.update_opt_out_role(role_id=None, updated_by=2)
    config = await repo.get_config()
    assert config.notification_opt_out_role_id is None
    assert config.updated_by == 2


@pytest.mark.asyncio
async def test_update_log_channel_persists(repo):
    await repo.update_log_channel(channel_id=98765, updated_by=42)
    config = await repo.get_config()
    assert config.log_channel_id == 98765
    assert config.updated_by == 42


@pytest.mark.asyncio
async def test_update_log_channel_can_clear(repo):
    await repo.update_log_channel(channel_id=55555, updated_by=1)
    await repo.update_log_channel(channel_id=None, updated_by=2)
    config = await repo.get_config()
    assert config.log_channel_id is None
    assert config.updated_by == 2
