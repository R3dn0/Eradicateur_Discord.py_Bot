import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.cogs.guild_commands import GuildCommands


class TestPingCommand:
    @pytest.fixture
    def cog(self):
        bot = MagicMock()
        bot.latency = 0.05
        return GuildCommands(bot)

    @pytest.mark.asyncio
    async def test_ping_responds(self, cog):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        await cog.ping.callback(cog, interaction)
        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "Pong" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True
