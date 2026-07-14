from bot.repositories.member_repository import GuildMember


class TestMemberRepository:
    def test_add_and_get(self, repo):
        m = GuildMember(discord_id=12345, albion_name="TestName", role="officer")
        repo.add(m)
        got = repo.get_by_discord_id(12345)
        assert got is not None
        assert got.discord_id == 12345
        assert got.albion_name == "TestName"
        assert got.role == "officer"

    def test_get_unknown_returns_none(self, repo):
        got = repo.get_by_discord_id(99999)
        assert got is None

    def test_list_all_empty_and_count(self, repo):
        assert repo.list_all() == []
        repo.add(GuildMember(discord_id=1, albion_name="A"))
        repo.add(GuildMember(discord_id=2, albion_name="B"))
        repo.add(GuildMember(discord_id=3, albion_name="C"))
        assert len(repo.list_all()) == 3

    def test_add_overwrites_existing(self, repo):
        repo.add(GuildMember(discord_id=1, albion_name="Original", role="member"))
        repo.add(GuildMember(discord_id=1, albion_name="Updated", role="officer"))
        got = repo.get_by_discord_id(1)
        assert got is not None
        assert got.albion_name == "Updated"
        assert got.role == "officer"
