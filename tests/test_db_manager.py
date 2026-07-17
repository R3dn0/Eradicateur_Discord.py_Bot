import asyncio
import os

import aiosqlite
import pytest

from bot.db_manager import GuildDatabaseManager


@pytest.fixture
async def manager(tmp_path):
    data_dir = str(tmp_path)
    m = GuildDatabaseManager(data_dir, idle_minutes=0.001)
    try:
        yield m
    finally:
        await m.close_all()


@pytest.mark.asyncio
async def test_two_guilds_get_separate_databases(manager):
    conn1 = await manager.get_connection(1001)
    conn2 = await manager.get_connection(1002)

    assert conn1 is not conn2

    await conn1.execute("CREATE TABLE IF NOT EXISTS test (guild_id INTEGER)")
    await conn1.execute("INSERT INTO test (guild_id) VALUES (1001)")
    await conn1.commit()

    cursor = await conn2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='test'"
    )
    row = await cursor.fetchone()
    assert row is None


@pytest.mark.asyncio
async def test_get_connection_returns_cached(manager):
    conn1 = await manager.get_connection(500)
    conn2 = await manager.get_connection(500)
    assert conn1 is conn2


@pytest.mark.asyncio
async def test_close_all_closes_all(manager):
    conn1 = await manager.get_connection(10)
    conn2 = await manager.get_connection(20)
    await manager.close_all()

    with pytest.raises((ValueError, aiosqlite.Error)):
        await conn1.execute("SELECT 1")

    with pytest.raises((ValueError, aiosqlite.Error)):
        await conn2.execute("SELECT 1")


@pytest.mark.asyncio
async def test_evict_idle_closes_old_connections(manager):
    conn = await manager.get_connection(42)

    await asyncio.sleep(0.1)

    await manager.evict_idle()

    with pytest.raises((ValueError, aiosqlite.Error)):
        await conn.execute("SELECT 1")


@pytest.mark.asyncio
async def test_reopen_after_eviction(manager):
    conn1 = await manager.get_connection(77)
    await asyncio.sleep(0.1)
    await manager.evict_idle()

    conn2 = await manager.get_connection(77)
    assert conn1 is not conn2

    cursor = await conn2.execute("SELECT 1")
    row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_schema_is_initialized(tmp_path):
    data_dir = str(tmp_path)
    manager = GuildDatabaseManager(data_dir, idle_minutes=30)
    try:
        conn = await manager.get_connection(200)

        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in await cursor.fetchall()}
        assert "bot_config" in tables
        assert "payout_config" in tables
        assert "payouts" in tables
        assert "transactions" in tables
    finally:
        await manager.close_all()


@pytest.mark.asyncio
async def test_file_created_at_expected_path(tmp_path):
    data_dir = str(tmp_path)
    manager = GuildDatabaseManager(data_dir, idle_minutes=30)
    try:
        await manager.get_connection(999)
        db_path = os.path.join(data_dir, "guilds", "999.db")
        assert os.path.exists(db_path)
    finally:
        await manager.close_all()


@pytest.mark.asyncio
async def test_concurrent_get_connection_same_guild(tmp_path):
    data_dir = str(tmp_path)
    manager = GuildDatabaseManager(data_dir, idle_minutes=30)
    try:

        async def get():
            return await manager.get_connection(300)

        results = await asyncio.gather(get(), get(), get())
        conn_a, conn_b, conn_c = results
        assert conn_a is conn_b
        assert conn_b is conn_c
    finally:
        await manager.close_all()
