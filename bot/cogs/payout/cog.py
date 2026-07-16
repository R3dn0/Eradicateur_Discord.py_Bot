import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.payout.views import PayoutCreateModal
from bot.main import EradicateurBot


class PayoutCog(commands.GroupCog, group_name=app_commands.locale_str("payout", key="payout_name")):  # type: ignore[call-arg]
    config = app_commands.Group(
        name=app_commands.locale_str("config", key="payout_config_name"),
        description=app_commands.locale_str(
            "Configure payout settings", key="payout_config_description"
        ),
    )

    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    @app_commands.command(
        name=app_commands.locale_str("create", key="payout_create_name"),
        description=app_commands.locale_str(
            "Create a new payout from a guild activity",
            key="payout_create_description",
        ),
    )
    async def create(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assert self.bot.payout_config_service is not None
        if not await self.bot.payout_config_service.is_officer(interaction.user):
            msg = await self.bot.translate("payout_officer_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        title = await self.bot.translate("payout_modal_title", interaction.locale)
        bag_label = await self.bot.translate("payout_modal_bag_label", interaction.locale)
        bag_placeholder = await self.bot.translate(
            "payout_modal_bag_placeholder", interaction.locale
        )
        item_label = await self.bot.translate("payout_modal_item_label", interaction.locale)
        item_placeholder = await self.bot.translate(
            "payout_modal_item_placeholder", interaction.locale
        )
        cost_label = await self.bot.translate("payout_modal_cost_label", interaction.locale)
        cost_placeholder = await self.bot.translate(
            "payout_modal_cost_placeholder", interaction.locale
        )
        invalid_msg = await self.bot.translate("payout_modal_invalid_number", interaction.locale)

        modal = PayoutCreateModal(
            title=title,
            bag_label=bag_label,
            bag_placeholder=bag_placeholder,
            item_label=item_label,
            item_placeholder=item_placeholder,
            cost_label=cost_label,
            cost_placeholder=cost_placeholder,
            invalid_msg=invalid_msg,
        )
        await interaction.response.send_modal(modal)

    @config.command(
        name=app_commands.locale_str("roles", key="payout_config_roles_name"),
        description=app_commands.locale_str(
            "Set the officer and leader roles for payout management",
            key="payout_config_roles_description",
        ),
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        officer="Officer role",
        leader="Leader role",
    )
    async def config_roles(
        self,
        interaction: discord.Interaction,
        leader: discord.Role,
        officer: discord.Role,
    ) -> None:
        assert self.bot.payout_config_repo is not None

        await self.bot.payout_config_repo.update_roles(
            leader_role_id=leader.id,
            officer_role_id=officer.id,
            updated_by=interaction.user.id,
        )

        msg = f"Roles configured: officer = {officer.mention}, leader = {leader.mention}"
        await interaction.response.send_message(msg, ephemeral=True)

    @config.command(
        name=app_commands.locale_str("rates", key="payout_config_rates_name"),
        description=app_commands.locale_str(
            "Update the tax rates used in payout calculations",
            key="payout_config_rates_description",
        ),
    )
    @app_commands.describe(
        market=app_commands.locale_str(
            "Market tax as a percentage, e.g. 2 for 2%",
            key="payout_config_rates_market_description",
        ),
        guild=app_commands.locale_str(
            "Guild tax as a percentage, e.g. 10 for 10%",
            key="payout_config_rates_guild_description",
        ),
        transport=app_commands.locale_str(
            "Transport tax as a percentage, e.g. 3 for 3%",
            key="payout_config_rates_transport_description",
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

        for name, value in [("market", market), ("guild", guild), ("transport", transport)]:
            if not (0 < value <= 100):
                await interaction.response.send_message(
                    f"{name.capitalize()} rate must be between 0 and 100.",
                    ephemeral=True,
                )
                return

        market_dec = market / 100
        guild_dec = guild / 100
        transport_dec = transport / 100

        await self.bot.payout_config_repo.update_rates(
            market=market_dec, guild=guild_dec, transport=transport_dec,
            updated_by=interaction.user.id,
        )

        def _fmt(v: float) -> str:
            return f"{v:.2%}".rstrip("0").rstrip(".")

        await interaction.response.send_message(
            f"Rates updated: market = {_fmt(market_dec)}, guild = {_fmt(guild_dec)}, transport = {_fmt(transport_dec)}",
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
        leader_role = (
            guild.get_role(config.leader_role_id) if config.leader_role_id and guild else None
        )
        leader = leader_role.mention if leader_role else "*Not configured*"
        officer_role = (
            guild.get_role(config.officer_role_id) if config.officer_role_id and guild else None
        )
        officer = officer_role.mention if officer_role else "*Not configured*"
        embed = discord.Embed(
            title="Payout Configuration",
            color=discord.Color.blue(),
        )

        def _fmt(v: float) -> str:
            return f"{v:.2%}".rstrip("0").rstrip(".")

        embed.add_field(name="Market tax", value=f"{_fmt(config.tax_market)}", inline=True)
        embed.add_field(name="Guild tax", value=f"{_fmt(config.tax_guild)}", inline=True)
        embed.add_field(name="Transport tax", value=f"{_fmt(config.tax_transport)}", inline=True)
        embed.add_field(name="Leader role", value=leader, inline=False)
        embed.add_field(name="Officer role", value=officer, inline=False)
        if config.updated_by:
            embed.set_footer(text=f"Last updated by <@{config.updated_by}> on {config.updated_at}")
        else:
            embed.set_footer(text=f"Last updated: {config.updated_at}")

        await interaction.response.send_message(embed=embed, ephemeral=True)
