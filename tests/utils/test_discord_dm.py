import discord
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.utils.discord_dm import send_bulk_dm


class TestSendBulkDm:
    @pytest.fixture
    def guild(self):
        guild = MagicMock(spec=discord.Guild)

        member_normal = MagicMock(spec=discord.Member)
        member_normal.id = 111
        member_normal.bot = False
        member_normal.send = AsyncMock()
        member_normal.get_role = MagicMock(return_value=None)

        member_optout = MagicMock(spec=discord.Member)
        member_optout.id = 222
        member_optout.bot = False
        member_optout.send = AsyncMock()
        member_optout.get_role = MagicMock(return_value=discord.Role)

        member_forbidden = MagicMock(spec=discord.Member)
        member_forbidden.id = 333
        member_forbidden.bot = False
        member_forbidden.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), ""))
        member_forbidden.get_role = MagicMock(return_value=None)

        members_by_id = {111: member_normal, 222: member_optout, 333: member_forbidden}
        guild.get_member = lambda uid: members_by_id.get(uid)
        guild.fetch_member = AsyncMock(side_effect=lambda uid: members_by_id[uid])

        return guild, member_normal, member_optout, member_forbidden

    @pytest.mark.asyncio
    async def test_sent_skipped_failed(self, guild):
        guild_obj, member_normal, member_optout, member_forbidden = guild

        async def build_content(member):
            return discord.Embed(title="Test", description=f"Hello {member.id}")

        result = await send_bulk_dm(
            guild=guild_obj,
            member_ids=[111, 222, 333],
            build_content=build_content,
            opt_out_role_id=777,
        )

        assert result.sent == [111]
        assert result.skipped == [222]
        assert result.failed == [333]

        member_normal.send.assert_awaited_once()
        member_optout.send.assert_not_called()
        member_forbidden.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_bot_member(self, guild):
        guild_obj, member_normal, member_optout, member_forbidden = guild

        member_bot = MagicMock(spec=discord.Member)
        member_bot.id = 444
        member_bot.bot = True
        member_bot.send = AsyncMock()

        orig_get = guild_obj.get_member
        guild_obj.get_member = lambda uid: member_bot if uid == 444 else orig_get(uid)

        async def build_content(member):
            return discord.Embed(title="Test", description=f"Hello {member.id}")

        result = await send_bulk_dm(
            guild=guild_obj,
            member_ids=[111, 444],
            build_content=build_content,
            opt_out_role_id=777,
        )

        assert result.sent == [111]
        assert member_bot.id not in result.sent
        assert member_bot.id not in result.failed
        assert member_bot.id not in result.skipped
        member_normal.send.assert_awaited_once()
        member_bot.send.assert_not_called()

        guild_obj.get_member = orig_get

    @pytest.mark.asyncio
    async def test_build_content_exception_isolated(self, guild):
        guild_obj, member_normal, member_optout, member_forbidden = guild

        call_count = 0

        async def build_content(member):
            nonlocal call_count
            call_count += 1
            if member.id == 111:
                raise RuntimeError("DB error for member 111")
            return discord.Embed(title="Test", description=f"Hello {member.id}")

        result = await send_bulk_dm(
            guild=guild_obj,
            member_ids=[111, 222, 333],
            build_content=build_content,
            opt_out_role_id=777,
        )

        assert result.sent == []
        assert result.skipped == [222]
        assert result.failed == [111, 333]

        member_normal.send.assert_not_called()
        member_optout.send.assert_not_called()
        member_forbidden.send.assert_awaited_once()
        assert call_count == 2
