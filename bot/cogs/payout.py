import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot


# Root cog for the /payout command tree.
# Future siblings to add here: create, pay, balance, history.
class PayoutCog(commands.GroupCog, group_name=app_commands.locale_str("payout", key="payout_name")):  # type: ignore[call-arg]
    config = app_commands.Group(
        name=app_commands.locale_str("config", key="payout_config_name"),
        description=app_commands.locale_str(
            "Configure payout settings", key="payout_config_description"
        ),
    )

    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    @config.command(
        name=app_commands.locale_str("roles", key="payout_config_roles_name"),
        description=app_commands.locale_str(
            "Set the officer and leader roles for payout management",
            key="payout_config_roles_description",
        ),
    )
    @app_commands.default_permissions(administrator=True)
    async def config_roles(
        self,
        interaction: discord.Interaction,
        officer: discord.Role,
        leader: discord.Role,
    ) -> None:
        assert self.bot.payout_config_repo is not None
        await self.bot.payout_config_repo.update_roles(
            officer_role_id=officer.id,
            leader_role_id=leader.id,
        )
        await interaction.response.send_message(
            f"Roles configured: officer = {officer.mention}, leader = {leader.mention}",
            ephemeral=True,
        )

    @config.command(
        name=app_commands.locale_str("rates", key="payout_config_rates_name"),
        description=app_commands.locale_str(
            "Update the tax rates used in payout calculations",
            key="payout_config_rates_description",
        ),
    )
    async def config_rates(
        self,
        interaction: discord.Interaction,
        market: float,
        guild: float,
        transport: float,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        assert self.bot.payout_config_service is not None
        assert self.bot.payout_config_repo is not None
        if not await self.bot.payout_config_service.is_leader(interaction.user):
            await interaction.response.send_message(
                "You need the leader role to change tax rates.", ephemeral=True
            )
            return

        await self.bot.payout_config_repo.update_rates(
            market=market, guild=guild, transport=transport
        )
        await interaction.response.send_message(
            f"Rates updated: market = {market:.0%}, guild = {guild:.0%}, transport = {transport:.0%}",
            ephemeral=True,
        )

    @config.command(
        name=app_commands.locale_str("show", key="payout_config_show_name"),
        description=app_commands.locale_str(
            "Display current payout configuration",
            key="payout_config_show_description",
        ),
    )
    async def config_show(self, interaction: discord.Interaction) -> None:
        assert self.bot.payout_config_repo is not None
        config = await self.bot.payout_config_repo.get_config()

        guild = interaction.guild
        officer_role = (
            guild.get_role(config.officer_role_id) if config.officer_role_id and guild else None
        )
        officer = officer_role.mention if officer_role else "*Not configured*"
        leader_role = (
            guild.get_role(config.leader_role_id) if config.leader_role_id and guild else None
        )
        leader = leader_role.mention if leader_role else "*Not configured*"

        embed = discord.Embed(
            title="Payout Configuration",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Market tax", value=f"{config.tax_market:.0%}", inline=True)
        embed.add_field(name="Guild tax", value=f"{config.tax_guild:.0%}", inline=True)
        embed.add_field(name="Transport tax", value=f"{config.tax_transport:.0%}", inline=True)
        embed.add_field(name="Officer role", value=officer, inline=False)
        embed.add_field(name="Leader role", value=leader, inline=False)
        embed.set_footer(text=f"Last updated: {config.updated_at}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: EradicateurBot) -> None:
    await bot.add_cog(PayoutCog(bot))
