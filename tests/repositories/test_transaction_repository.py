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
    await repo.add_transaction(discord_id=100, amount=50, reason="test", created_by=1)
    balance = await repo.get_balance(discord_id=100)
    assert balance == 50


@pytest.mark.asyncio
async def test_balance_sums_multiple(repo):
    await repo.add_transaction(discord_id=200, amount=100, reason="first", created_by=1)
    await repo.add_transaction(discord_id=200, amount=50, reason="second", created_by=1)
    await repo.add_transaction(discord_id=200, amount=-30, reason="debit", created_by=1)
    balance = await repo.get_balance(discord_id=200)
    assert balance == 120


@pytest.mark.asyncio
async def test_balance_is_per_user(repo):
    await repo.add_transaction(discord_id=300, amount=100, reason="user A", created_by=1)
    await repo.add_transaction(discord_id=400, amount=200, reason="user B", created_by=1)
    assert await repo.get_balance(discord_id=300) == 100
    assert await repo.get_balance(discord_id=400) == 200


@pytest.mark.asyncio
async def test_list_balances_excludes_zero(repo):
    await repo.add_transaction(discord_id=100, amount=50, reason="credit", created_by=1)
    await repo.add_transaction(discord_id=100, amount=-50, reason="debit", created_by=1)
    await repo.add_transaction(discord_id=200, amount=100, reason="credit", created_by=1)
    await repo.add_transaction(discord_id=300, amount=0, reason="zero", created_by=1)
    balances = await repo.list_balances()
    assert len(balances) == 1
    assert balances[0] == (200, 100)


@pytest.mark.asyncio
async def test_list_balances_orders_desc(repo):
    await repo.add_transaction(discord_id=1, amount=10, reason="a", created_by=0)
    await repo.add_transaction(discord_id=2, amount=50, reason="b", created_by=0)
    await repo.add_transaction(discord_id=3, amount=30, reason="c", created_by=0)
    balances = await repo.list_balances()
    assert balances == [(2, 50), (3, 30), (1, 10)]


@pytest.mark.asyncio
async def test_get_total_owed_returns_zero_when_empty(repo):
    assert await repo.get_total_owed() == 0


@pytest.mark.asyncio
async def test_get_total_owed_sums_positive_balances_only(repo):
    await repo.add_transaction(discord_id=100, amount=100, reason="credit", created_by=1)
    await repo.add_transaction(discord_id=200, amount=50, reason="credit", created_by=1)
    await repo.add_transaction(discord_id=300, amount=-30, reason="debt", created_by=1)
    await repo.add_transaction(discord_id=100, amount=-100, reason="net zero", created_by=1)
    assert await repo.get_total_owed() == 50


@pytest.mark.asyncio
async def test_list_transactions_orders_desc(repo):
    await repo.add_transaction(discord_id=500, amount=10, reason="first", created_by=1)
    await repo.add_transaction(discord_id=500, amount=20, reason="second", created_by=1)
    txs = await repo.list_transactions(discord_id=500)
    assert len(txs) == 2
    assert txs[0].reason == "second"
    assert txs[1].reason == "first"


@pytest.mark.asyncio
async def test_list_transactions_for_payout(repo):
    txn_id_1 = await repo.add_transaction(
        discord_id=100, amount=50, reason="first", created_by=1, payout_id=99
    )
    txn_id_2 = await repo.add_transaction(
        discord_id=100, amount=50, reason="second", created_by=1, payout_id=99
    )
    await repo.add_transaction(discord_id=200, amount=30, reason="other", created_by=1)

    txs = await repo.list_transactions_for_payout(99)
    assert len(txs) == 2
    assert txs[0].id == txn_id_1
    assert txs[1].id == txn_id_2
