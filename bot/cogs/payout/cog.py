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

    @app_commands.command(
        name=app_commands.locale_str("pay", key="payout_pay_name"),
        description=app_commands.locale_str(
            "Manually withdraw from a player's balance",
            key="payout_pay_description",
        ),
    )
    @app_commands.describe(
        joueur=app_commands.locale_str(
            "Member whose balance will be debited",
            key="payout_pay_joueur_description",
        ),
        montant=app_commands.locale_str(
            "Amount to withdraw (must be > 0)",
            key="payout_pay_montant_description",
        ),
    )
    async def pay(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        montant: float,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assert self.bot.payout_config_service is not None
        assert self.bot.payout_config_repo is not None
        assert self.bot.transaction_repo is not None
        config = await self.bot.payout_config_repo.get_config()
        if config.pay_add_permission_level == "leader":
            if not await self.bot.payout_config_service.is_leader(interaction.user):
                msg = await self.bot.translate("payout_pay_leader_only", interaction.locale)
                await interaction.response.send_message(msg, ephemeral=True)
                return
        else:
            if not await self.bot.payout_config_service.is_officer(interaction.user):
                msg = await self.bot.translate("payout_pay_officer_only", interaction.locale)
                await interaction.response.send_message(msg, ephemeral=True)
                return

        if montant <= 0:
            msg = await self.bot.translate("payout_amount_positive", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        balance = await self.bot.transaction_repo.get_balance(joueur.id)
        if montant > balance:
            template = await self.bot.translate(
                "payout_insufficient_balance", interaction.locale
            )
            await interaction.response.send_message(
                template.replace("{joueur}", joueur.mention)
                .replace("{balance}", f"{balance:,.0f}")
                .replace("{montant}", f"{montant:,.0f}"),
                ephemeral=True,
            )
            return

        await self.bot.transaction_repo.add_transaction(
            discord_id=joueur.id,
            amount=-montant,
            reason="Manual withdrawal",
            created_by=interaction.user.id,
        )

        new_balance = await self.bot.transaction_repo.get_balance(joueur.id)
        template = await self.bot.translate("payout_paid", interaction.locale)
        await interaction.response.send_message(
            template.replace("{montant}", f"{montant:,.0f}")
            .replace("{joueur}", joueur.mention)
            .replace("{balance}", f"{new_balance:,.0f}"),
            ephemeral=True,
        )

    @app_commands.command(
        name=app_commands.locale_str("add", key="payout_add_name"),
        description=app_commands.locale_str(
            "Manually credit a player's balance",
            key="payout_add_description",
        ),
    )
    @app_commands.describe(
        joueur=app_commands.locale_str(
            "Member whose balance will be credited",
            key="payout_add_joueur_description",
        ),
        montant=app_commands.locale_str(
            "Amount to add (must be > 0)",
            key="payout_add_montant_description",
        ),
        raison=app_commands.locale_str(
            "Reason for the credit",
            key="payout_add_raison_description",
        ),
    )
    async def add(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        montant: float,
        raison: str,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assert self.bot.payout_config_service is not None
        assert self.bot.payout_config_repo is not None
        assert self.bot.transaction_repo is not None
        config = await self.bot.payout_config_repo.get_config()
        if config.pay_add_permission_level == "leader":
            if not await self.bot.payout_config_service.is_leader(interaction.user):
                msg = await self.bot.translate("payout_add_leader_only", interaction.locale)
                await interaction.response.send_message(msg, ephemeral=True)
                return
        else:
            if not await self.bot.payout_config_service.is_officer(interaction.user):
                msg = await self.bot.translate("payout_add_officer_only", interaction.locale)
                await interaction.response.send_message(msg, ephemeral=True)
                return

        if montant <= 0:
            msg = await self.bot.translate("payout_amount_positive", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await self.bot.transaction_repo.add_transaction(
            discord_id=joueur.id,
            amount=montant,
            reason=raison,
            created_by=interaction.user.id,
        )

        new_balance = await self.bot.transaction_repo.get_balance(joueur.id)
        template = await self.bot.translate("payout_credited", interaction.locale)
        await interaction.response.send_message(
            template.replace("{montant}", f"{montant:,.0f}")
            .replace("{joueur}", joueur.mention)
            .replace("{raison}", raison)
            .replace("{balance}", f"{new_balance:,.0f}"),
            ephemeral=True,
        )

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

        template = await self.bot.translate("payout_config_roles_updated", interaction.locale)
        await interaction.response.send_message(
            template.replace("{officer}", officer.mention)
            .replace("{leader}", leader.mention),
            ephemeral=True,
        )

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
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assert self.bot.payout_config_service is not None
        assert self.bot.payout_config_repo is not None
        if not await self.bot.payout_config_service.is_leader(interaction.user):
            msg = await self.bot.translate("payout_config_rates_leader_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        for name, value in [("market", market), ("guild", guild), ("transport", transport)]:
            if not (0 < value <= 100):
                template = await self.bot.translate(
                    "payout_config_rates_invalid", interaction.locale
                )
                await interaction.response.send_message(
                    template.replace("{name}", name.capitalize()),
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

        template = await self.bot.translate("payout_config_rates_updated", interaction.locale)
        await interaction.response.send_message(
            template.replace("{market}", _fmt(market_dec))
            .replace("{guild}", _fmt(guild_dec))
            .replace("{transport}", _fmt(transport_dec)),
            ephemeral=True,
        )

    @config.command(
        name=app_commands.locale_str("permissions", key="payout_config_permissions_name"),
        description=app_commands.locale_str(
            "Set the permission level for /payout pay and /payout add",
            key="payout_config_permissions_description",
        ),
    )
    @app_commands.describe(
        level=app_commands.locale_str(
            "Required level (Officer or Leader)",
            key="payout_config_permissions_level_description",
        ),
    )
    @app_commands.choices(level=[
        app_commands.Choice(
            name=app_commands.locale_str("Officier", key="payout_config_permissions_choice_officer"),
            value="officer",
        ),
        app_commands.Choice(
            name=app_commands.locale_str("Leader", key="payout_config_permissions_choice_leader"),
            value="leader",
        ),
    ])
    async def config_permissions(
        self,
        interaction: discord.Interaction,
        level: str,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assert self.bot.payout_config_service is not None
        assert self.bot.payout_config_repo is not None
        if not await self.bot.payout_config_service.is_leader(interaction.user):
            msg = await self.bot.translate(
                "payout_config_permissions_leader_only", interaction.locale
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await self.bot.payout_config_repo.update_pay_add_permission_level(
            level=level,
            updated_by=interaction.user.id,
        )

        display = "Officier" if level == "officer" else "Leader"
        template = await self.bot.translate(
            "payout_config_permissions_updated", interaction.locale
        )
        await interaction.response.send_message(
            template.replace("{level}", display),
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
        officer_role = (
            guild.get_role(config.officer_role_id) if config.officer_role_id and guild else None
        )
        not_configured = await self.bot.translate("payout_not_configured", interaction.locale)
        leader = leader_role.mention if leader_role else not_configured
        officer = officer_role.mention if officer_role else not_configured
        embed = discord.Embed(
            title=await self.bot.translate("payout_config_show_embed_title", interaction.locale),
            color=discord.Color.blue(),
        )

        def _fmt(v: float) -> str:
            return f"{v:.2%}".rstrip("0").rstrip(".")

        embed.add_field(
            name=await self.bot.translate("payout_embed_tax_market", interaction.locale),
            value=f"{_fmt(config.tax_market)}", inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_tax_guild", interaction.locale),
            value=f"{_fmt(config.tax_guild)}", inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_tax_transport", interaction.locale),
            value=f"{_fmt(config.tax_transport)}", inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_config_show_leader_role", interaction.locale),
            value=leader, inline=False,
        )
        embed.add_field(
            name=await self.bot.translate("payout_config_show_officer_role", interaction.locale),
            value=officer, inline=False,
        )
        perm_display = "Officier" if config.pay_add_permission_level == "officer" else "Leader"
        embed.add_field(
            name=await self.bot.translate(
                "payout_config_show_pay_add_permission", interaction.locale
            ),
            value=perm_display, inline=False,
        )
        if config.updated_by:
            footer = await self.bot.translate(
                "payout_config_show_updated_by", interaction.locale
            )
            embed.set_footer(
                text=footer.replace("{user}", f"<@{config.updated_by}>")
                .replace("{date}", config.updated_at)
            )
        else:
            footer = await self.bot.translate("payout_config_show_updated", interaction.locale)
            embed.set_footer(text=footer.replace("{date}", config.updated_at))

        await interaction.response.send_message(embed=embed, ephemeral=True)
