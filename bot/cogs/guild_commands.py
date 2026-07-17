import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot


class GuildCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name=app_commands.locale_str("ping", key="ping_name"),
        description=app_commands.locale_str("Check that the bot responds", key="ping_description"),
    )
    async def ping(self, interaction: discord.Interaction) -> None:
        template = await self.bot.translate("ping_response", interaction.locale)
        await interaction.response.send_message(
            template.replace("{latency}", str(round(self.bot.latency * 1000))),
            ephemeral=True,
        )


async def setup(bot: EradicateurBot) -> None:
    await bot.add_cog(GuildCommands(bot))
