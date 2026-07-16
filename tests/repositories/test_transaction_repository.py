import aiosqlite
import pytest

from bot.repositories.transaction_repository import (
    TransactionRepository,
)


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "test.db"
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn


@pytest.fixture
async def repo(db):
    return TransactionRepository(db)


@pytest.mark.asyncio
async def test_get_balance_returns_zero_for_unknown(repo):
    balance = await repo.get_balance(discord_id=99999)
    assert balance == 0


@pytest.mark.asyncio
async def test_add_and_balance_single(repo):
    await repo.add_transaction(discord_id=100, amount=50.0, reason="test", created_by=1)
    balance = await repo.get_balance(discord_id=100)
    assert balance == 50.0


@pytest.mark.asyncio
async def test_balance_sums_multiple(repo):
    await repo.add_transaction(discord_id=200, amount=100.0, reason="first", created_by=1)
    await repo.add_transaction(discord_id=200, amount=50.0, reason="second", created_by=1)
    await repo.add_transaction(discord_id=200, amount=-30.0, reason="debit", created_by=1)
    balance = await repo.get_balance(discord_id=200)
    assert balance == 120.0


@pytest.mark.asyncio
async def test_balance_is_per_user(repo):
    await repo.add_transaction(discord_id=300, amount=100.0, reason="user A", created_by=1)
    await repo.add_transaction(discord_id=400, amount=200.0, reason="user B", created_by=1)
    assert await repo.get_balance(discord_id=300) == 100.0
    assert await repo.get_balance(discord_id=400) == 200.0


@pytest.mark.asyncio
async def test_list_balances_excludes_zero(repo):
    await repo.add_transaction(discord_id=100, amount=50.0, reason="credit", created_by=1)
    await repo.add_transaction(discord_id=100, amount=-50.0, reason="debit", created_by=1)
    await repo.add_transaction(discord_id=200, amount=100.0, reason="credit", created_by=1)
    await repo.add_transaction(discord_id=300, amount=0.0, reason="zero", created_by=1)
    balances = await repo.list_balances()
    assert len(balances) == 1
    assert balances[0] == (200, 100.0)


@pytest.mark.asyncio
async def test_list_balances_orders_desc(repo):
    await repo.add_transaction(discord_id=1, amount=10.0, reason="a", created_by=0)
    await repo.add_transaction(discord_id=2, amount=50.0, reason="b", created_by=0)
    await repo.add_transaction(discord_id=3, amount=30.0, reason="c", created_by=0)
    balances = await repo.list_balances()
    assert balances == [(2, 50.0), (3, 30.0), (1, 10.0)]


@pytest.mark.asyncio
async def test_list_transactions_orders_desc(repo):
    await repo.add_transaction(discord_id=500, amount=10.0, reason="first", created_by=1)
    await repo.add_transaction(discord_id=500, amount=20.0, reason="second", created_by=1)
    txs = await repo.list_transactions(discord_id=500)
    assert len(txs) == 2
    assert txs[0].reason == "second"
    assert txs[1].reason == "first"
