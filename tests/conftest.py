import pytest

from bot.repositories.member_repository import MemberRepository


@pytest.fixture
def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    return MemberRepository(db_path)
