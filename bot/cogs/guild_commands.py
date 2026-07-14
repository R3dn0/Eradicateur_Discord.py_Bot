import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot
from bot.repositories.member_repository import GuildMember, MemberRepository


class GuildCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, repository: MemberRepository) -> None:
        self.bot = bot
        self.repository = repository

    @app_commands.command(
        name=app_commands.locale_str("ping", key="ping_name"),
        description=app_commands.locale_str("Check that the bot responds", key="ping_description"),
    )
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Pong ! ({round(self.bot.latency * 1000)}ms)"
        )

    @app_commands.command(
        name=app_commands.locale_str("register", key="register_name"),
        description=app_commands.locale_str("Link your Albion in-game name", key="register_description"),
    )
    @app_commands.describe(
        ign=app_commands.locale_str("Your Albion Online in-game name", key="register_ign_description"),
    )
    @app_commands.rename(ign=app_commands.locale_str("pseudo", key="register_ign_name"))
    async def register(self, interaction: discord.Interaction, ign: str) -> None:
        self.repository.add(
            GuildMember(discord_id=interaction.user.id, albion_name=ign)
        )
        await interaction.response.send_message(
            f"Registered: **{ign}** linked to your Discord account."
        )

    @app_commands.command(
        name=app_commands.locale_str("members", key="members_name"),
        description=app_commands.locale_str("List all registered members", key="members_description"),
    )
    async def members(self, interaction: discord.Interaction) -> None:
        members = self.repository.list_all()
        if not members:
            await interaction.response.send_message(
                "No members registered yet."
            )
            return
        lines = [f"- {m.albion_name} ({m.role})" for m in members]
        await interaction.response.send_message("\n".join(lines))


async def setup(bot: EradicateurBot) -> None:
    await bot.add_cog(GuildCommands(bot, bot.repository))
