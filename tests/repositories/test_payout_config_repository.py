import aiosqlite
import pytest

from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "test.db"
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn


@pytest.fixture
async def repo(db):
    return PayoutConfigRepository(db)


@pytest.mark.asyncio
async def test_get_config_creates_defaults(repo):
    config = await repo.get_config()
    assert config.tax_market == 0.02
    assert config.tax_guild == 0.10
    assert config.tax_transport == 0.03
    assert config.officer_role_id is None
    assert config.leader_role_id is None
    assert config.no_dm_role_id is None
    assert config.updated_at is not None
    assert config.updated_by is None


@pytest.mark.asyncio
async def test_update_rates_persists(repo):
    await repo.update_rates(market=0.05, guild=0.15, transport=0.07, updated_by=42)
    config = await repo.get_config()
    assert config.tax_market == 0.05
    assert config.tax_guild == 0.15
    assert config.tax_transport == 0.07
    assert config.updated_by == 42


@pytest.mark.asyncio
async def test_update_roles_persists(repo):
    await repo.update_roles(officer_role_id=12345, leader_role_id=67890, updated_by=99)
    config = await repo.get_config()
    assert config.officer_role_id == 12345
    assert config.leader_role_id == 67890
    assert config.no_dm_role_id is None
    assert config.updated_by == 99


@pytest.mark.asyncio
async def test_update_roles_can_clear(repo):
    await repo.update_roles(officer_role_id=111, leader_role_id=222, updated_by=1)
    await repo.update_roles(officer_role_id=None, leader_role_id=None, updated_by=2)
    config = await repo.get_config()
    assert config.officer_role_id is None
    assert config.leader_role_id is None
    assert config.no_dm_role_id is None
    assert config.updated_by == 2


