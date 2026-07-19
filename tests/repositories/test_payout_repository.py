import aiosqlite
import pytest

from bot.repositories.payout_repository import PayoutRepository
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
    transaction_repo = TransactionRepository(db)
    return PayoutRepository(db, transaction_repo)


@pytest.mark.asyncio
async def test_create_payout_returns_id(repo):
    payout_id = await repo.create_payout(
        bag_silvers=1_000_000,
        item_market_value=500_000,
        activity_cost=50_000,
        tax_market=0.02,
        tax_guild=0.10,
        tax_transport=0.03,
        amount_per_player=100_000,
        buyback_value=475_000,
        participant_ids=[111, 222, 333],
        created_by=1,
    )
    assert isinstance(payout_id, int)
    assert payout_id > 0


@pytest.mark.asyncio
async def test_create_payout_persists_row(repo):
    payout_id = await repo.create_payout(
        bag_silvers=2_000_000,
        item_market_value=1_000_000,
        activity_cost=100_000,
        tax_market=0.02,
        tax_guild=0.10,
        tax_transport=0.03,
        amount_per_player=250_000,
        buyback_value=950_000,
        participant_ids=[111, 222],
        created_by=42,
    )

    cursor = await repo._db.execute("SELECT * FROM payouts WHERE id = ?", (payout_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["bag_silvers"] == 2_000_000
    assert row["item_market_value"] == 1_000_000
    assert row["activity_cost"] == 100_000
    assert row["tax_market"] == 0.02
    assert row["tax_guild"] == 0.10
    assert row["tax_transport"] == 0.03
    assert row["participant_count"] == 2
    assert row["amount_per_player"] == 250_000
    assert row["buyback_value"] == 950_000
    assert row["created_by"] == 42
    assert row["created_at"] is not None


@pytest.mark.asyncio
async def test_create_payout_creates_transactions(repo):
    payout_id = await repo.create_payout(
        bag_silvers=1_000_000,
        item_market_value=500_000,
        activity_cost=50_000,
        tax_market=0.02,
        tax_guild=0.10,
        tax_transport=0.03,
        amount_per_player=100_000,
        buyback_value=475_000,
        participant_ids=[111, 222, 333],
        created_by=1,
    )

    cursor = await repo._db.execute(
        "SELECT COUNT(*) AS cnt FROM transactions WHERE payout_id = ?",
        (payout_id,),
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 3


@pytest.mark.asyncio
async def test_rollback_on_transaction_failure(repo):
    transaction_insert_count = 0
    original_execute = repo._db.execute

    async def failing_execute(sql, parameters=None):
        nonlocal transaction_insert_count
        if isinstance(sql, str) and "INSERT INTO transactions" in sql:
            transaction_insert_count += 1
            if transaction_insert_count >= 2:
                raise RuntimeError("simulated DB failure")
        return await original_execute(sql, parameters)

    repo._db.execute = failing_execute

    with pytest.raises(RuntimeError):
        await repo.create_payout(
            bag_silvers=1_000_000,
            item_market_value=500_000,
            activity_cost=50_000,
            tax_market=0.02,
            tax_guild=0.10,
            tax_transport=0.03,
            amount_per_player=100_000,
            buyback_value=475_000,
            participant_ids=[111, 222, 333],
            created_by=1,
        )

    repo._db.execute = original_execute

    cursor = await repo._db.execute("SELECT COUNT(*) AS cnt FROM payouts")
    row = await cursor.fetchone()
    assert row["cnt"] == 0

    cursor = await repo._db.execute("SELECT COUNT(*) AS cnt FROM transactions")
    row = await cursor.fetchone()
    assert row["cnt"] == 0


@pytest.mark.asyncio
async def test_buyback_value_formula(repo):
    item_market_value = 30_600_000
    tax_market = 0.02
    tax_transport = 0.03
    expected = int(item_market_value * (1 - tax_market - tax_transport))

    payout_id = await repo.create_payout(
        bag_silvers=1_000_000,
        item_market_value=item_market_value,
        activity_cost=50_000,
        tax_market=tax_market,
        tax_guild=0.10,
        tax_transport=tax_transport,
        amount_per_player=100_000,
        buyback_value=expected,
        participant_ids=[111],
        created_by=1,
    )

    cursor = await repo._db.execute("SELECT buyback_value FROM payouts WHERE id = ?", (payout_id,))
    row = await cursor.fetchone()
    assert row["buyback_value"] == 29_070_000


@pytest.mark.asyncio
async def test_get_payout_returns_none_for_missing(repo):
    payout = await repo.get_payout(99999)
    assert payout is None


@pytest.mark.asyncio
async def test_get_payout_returns_payout(repo):
    payout_id = await repo.create_payout(
        bag_silvers=1_000_000,
        item_market_value=500_000,
        activity_cost=50_000,
        tax_market=0.02,
        tax_guild=0.10,
        tax_transport=0.03,
        amount_per_player=100_000,
        buyback_value=475_000,
        participant_ids=[111, 222],
        created_by=1,
    )

    payout = await repo.get_payout(payout_id)
    assert payout is not None
    assert payout.id == payout_id
    assert payout.bag_silvers == 1_000_000
    assert payout.voided is False


@pytest.mark.asyncio
async def test_void_payout_marks_voided_and_reverses(repo):
    payout_id = await repo.create_payout(
        bag_silvers=1_000_000,
        item_market_value=500_000,
        activity_cost=50_000,
        tax_market=0.02,
        tax_guild=0.10,
        tax_transport=0.03,
        amount_per_player=100_000,
        buyback_value=475_000,
        participant_ids=[111, 222],
        created_by=1,
    )

    await repo.void_payout(payout_id, voided_by=42)

    payout = await repo.get_payout(payout_id)
    assert payout is not None
    assert payout.voided is True
    assert payout.voided_by == 42

    cursor = await repo._db.execute(
        "SELECT SUM(amount) AS total FROM transactions WHERE discord_id = ?",
        (111,),
    )
    row = await cursor.fetchone()
    assert row["total"] == 0


@pytest.mark.asyncio
async def test_void_payout_rejects_double_void(repo):
    payout_id = await repo.create_payout(
        bag_silvers=1_000_000,
        item_market_value=500_000,
        activity_cost=50_000,
        tax_market=0.02,
        tax_guild=0.10,
        tax_transport=0.03,
        amount_per_player=100_000,
        buyback_value=475_000,
        participant_ids=[111],
        created_by=1,
    )

    await repo.void_payout(payout_id, voided_by=1)
    with pytest.raises(ValueError, match="already voided"):
        await repo.void_payout(payout_id, voided_by=2)


@pytest.mark.asyncio
async def test_void_payout_rejects_missing(repo):
    with pytest.raises(ValueError, match="not found"):
        await repo.void_payout(99999, voided_by=1)
