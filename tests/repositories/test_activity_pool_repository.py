import aiosqlite
import pytest

from bot.repositories.activity_pool_repository import ActivityPoolRepository


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "test.db"
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn


@pytest.fixture
async def repo(db):
    return ActivityPoolRepository(db)


@pytest.mark.asyncio
async def test_add_and_get_labels(repo):
    await repo.add_label(1, "🛡️ Tank")
    await repo.add_label(1, "💚 Sancti")
    await repo.add_label(2, "Autre")
    assert await repo.get_labels(1) == ["🛡️ Tank", "💚 Sancti"]
    assert await repo.get_labels(2) == ["Autre"]


@pytest.mark.asyncio
async def test_remove_position_renumbers(repo):
    for label in ["A", "B", "C"]:
        await repo.add_label(1, label)
    assert await repo.remove_position(1, 2) is True
    assert await repo.get_labels(1) == ["A", "C"]
    assert await repo.remove_position(1, 99) is False
    assert await repo.get_labels(1) == ["A", "C"]


@pytest.mark.asyncio
async def test_remove_first_position_renumbers(repo):
    for label in ["A", "B", "C"]:
        await repo.add_label(1, label)
    await repo.remove_position(1, 1)
    assert await repo.get_labels(1) == ["B", "C"]


@pytest.mark.asyncio
async def test_clear(repo):
    await repo.add_label(1, "A")
    await repo.add_label(1, "B")
    await repo.clear(1)
    assert await repo.get_labels(1) == []


@pytest.mark.asyncio
async def test_guilds_are_isolated(repo):
    await repo.add_label(1, "A")
    await repo.add_label(2, "B")
    await repo.remove_position(1, 1)
    assert await repo.get_labels(2) == ["B"]


@pytest.mark.asyncio
async def test_set_order_rewrites_positions(repo):
    for label in ["A", "B", "C"]:
        await repo.add_label(1, label)
    await repo.set_order(1, ["C", "A", "B"])
    assert await repo.get_labels(1) == ["C", "A", "B"]
    await repo.set_order(2, ["X"])
    assert await repo.get_labels(1) == ["C", "A", "B"]
    assert await repo.get_labels(2) == ["X"]
