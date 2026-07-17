import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.payout.views import PayoutCreateModal
from bot.main import EradicateurBot
from bot.repositories.bot_config_repository import BotConfigRepository
from bot.repositories.payout_repository import PayoutRepository
from bot.repositories.transaction_repository import TransactionRepository
from bot.utils.discord_guards import require_guild_member
from bot.utils.discord_time import to_discord_timestamp
from bot.utils.discord_dm import send_bulk_dm
from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)
from bot.services.payout_config_service import PayoutConfigService


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
    @require_guild_member
    async def create(self, interaction: discord.Interaction) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)

        if not await payout_config_service.is_officer(interaction.user):
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
        name=app_commands.locale_str("void", key="payout_void_name"),
        description=app_commands.locale_str(
            "Void a payout and refund all participants",
            key="payout_void_description",
        ),
    )
    @app_commands.describe(
        payout_id=app_commands.locale_str(
            "ID of the payout to void",
            key="payout_void_id_description",
        ),
    )
    @require_guild_member
    async def void(
        self,
        interaction: discord.Interaction,
        payout_id: int,
    ) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)

        if not await payout_config_service.is_officer(interaction.user):
            msg = await self.bot.translate("payout_officer_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        payout_repo = PayoutRepository(db, TransactionRepository(db))
        payout = await payout_repo.get_payout(payout_id)
        if payout is None:
            template = await self.bot.translate("payout_void_not_found", interaction.locale)
            await interaction.response.send_message(
                template.replace("{id}", str(payout_id)),
                ephemeral=True,
            )
            return

        if payout.voided:
            template = await self.bot.translate("payout_void_already_voided", interaction.locale)
            await interaction.response.send_message(
                template.replace("{id}", str(payout_id)),
                ephemeral=True,
            )
            return

        await payout_repo.void_payout(payout_id, voided_by=interaction.user.id)

        bot_config_repo = BotConfigRepository(db)
        bot_config = await bot_config_repo.get_config()
        no_dm_role_id = bot_config.notification_opt_out_role_id

        void_dm_title = await self.bot.translate("payout_void_dm_title", interaction.locale)
        void_dm_balance = await self.bot.translate("payout_void_dm_new_balance", interaction.locale)
        void_dm_adjusted = await self.bot.translate("payout_void_dm_adjusted", interaction.locale)

        transaction_repo = TransactionRepository(db)

        async def _build_void_content(member: discord.Member) -> discord.Embed:
            new_balance = await transaction_repo.get_balance(member.id)
            embed = discord.Embed(
                title=void_dm_title,
                color=discord.Color.orange(),
            )
            embed.add_field(
                name=void_dm_adjusted,
                value=f"{payout.amount_per_player:,.0f}",
                inline=True,
            )
            embed.add_field(
                name=void_dm_balance,
                value=f"{new_balance:,.0f}",
                inline=True,
            )
            return embed

        txns = await transaction_repo.list_transactions_for_payout(payout_id)
        participant_ids = list({t.discord_id for t in txns})

        result = await send_bulk_dm(
            guild=interaction.guild,
            member_ids=participant_ids,
            build_content=_build_void_content,
            opt_out_role_id=no_dm_role_id,
        )

        n = payout.participant_count
        success = await self.bot.translate("payout_void_success", interaction.locale)
        success = success.replace("{id}", str(payout_id)).replace("{n}", str(n))

        if result.skipped:
            optout_note = await self.bot.translate("payout_dm_optout_note", interaction.locale)
            success += "\n" + optout_note.replace("{n}", str(len(result.skipped)))

        if result.failed:
            failure_note = await self.bot.translate("payout_dm_failure_note", interaction.locale)
            failed_mentions = ", ".join(f"<@{uid}>" for uid in result.failed)
            success += "\n" + failure_note.replace("{users}", failed_mentions)

        embed = discord.Embed(
            title=(await self.bot.translate("payout_void_embed_title", interaction.locale)).replace(
                "{id}", str(payout_id)
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_gain", interaction.locale),
            value=f"{payout.bag_silvers:,.0f}",
            inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_item", interaction.locale),
            value=f"{payout.item_market_value:,.0f}",
            inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_cost", interaction.locale),
            value=f"{payout.activity_cost:,.0f}",
            inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_participants", interaction.locale),
            value=str(n),
            inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_amount", interaction.locale),
            value=f"{payout.amount_per_player:,.0f}",
            inline=True,
        )
        template = await self.bot.translate("payout_void_reversed_by", interaction.locale)
        embed.add_field(
            name=await self.bot.translate("payout_embed_buyback", interaction.locale),
            value=template.replace("{user}", interaction.user.mention).replace(
                "{date}", to_discord_timestamp(payout.created_at)
            ),
            inline=False,
        )

        await interaction.response.send_message(content=success, embed=embed, ephemeral=True)

    @config.command(
        name=app_commands.locale_str("roles", key="payout_config_roles_name"),
        description=app_commands.locale_str(
            "Set the officer and leader roles for payout management",
            key="payout_config_roles_description",
        ),
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        officer=app_commands.locale_str(
            "Officer role", key="payout_config_roles_officer_description"
        ),
        leader=app_commands.locale_str("Leader role", key="payout_config_roles_leader_description"),
    )
    @require_guild_member
    async def config_roles(
        self,
        interaction: discord.Interaction,
        leader: discord.Role,
        officer: discord.Role,
    ) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)

        await payout_config_repo.update_roles(
            leader_role_id=leader.id,
            officer_role_id=officer.id,
            updated_by=interaction.user.id,
        )

        template = await self.bot.translate("payout_config_roles_updated", interaction.locale)
        await interaction.response.send_message(
            template.replace("{officer}", officer.mention).replace("{leader}", leader.mention),
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
    @require_guild_member
    async def config_rates(
        self,
        interaction: discord.Interaction,
        market: float,
        guild: float,
        transport: float,
    ) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)

        if not await payout_config_service.is_leader(interaction.user):
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

        await payout_config_repo.update_rates(
            market=market_dec,
            guild=guild_dec,
            transport=transport_dec,
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
    @app_commands.choices(
        level=[
            app_commands.Choice(
                name=app_commands.locale_str(
                    "Officier", key="payout_config_permissions_choice_officer"
                ),
                value="officer",
            ),
            app_commands.Choice(
                name=app_commands.locale_str(
                    "Leader", key="payout_config_permissions_choice_leader"
                ),
                value="leader",
            ),
        ]
    )
    @require_guild_member
    async def config_permissions(
        self,
        interaction: discord.Interaction,
        level: str,
    ) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)

        if not await payout_config_service.is_leader(interaction.user):
            msg = await self.bot.translate(
                "payout_config_permissions_leader_only", interaction.locale
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await payout_config_repo.update_pay_add_permission_level(
            level=level,
            updated_by=interaction.user.id,
        )

        display = await self.bot.translate(
            "payout_level_officer" if level == "officer" else "payout_level_leader",
            interaction.locale,
        )
        template = await self.bot.translate("payout_config_permissions_updated", interaction.locale)
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
    @require_guild_member
    async def config_show(self, interaction: discord.Interaction) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        config = await payout_config_repo.get_config()

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
            value=f"{_fmt(config.tax_market)}",
            inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_tax_guild", interaction.locale),
            value=f"{_fmt(config.tax_guild)}",
            inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_embed_tax_transport", interaction.locale),
            value=f"{_fmt(config.tax_transport)}",
            inline=True,
        )
        embed.add_field(
            name=await self.bot.translate("payout_config_show_leader_role", interaction.locale),
            value=leader,
            inline=False,
        )
        embed.add_field(
            name=await self.bot.translate("payout_config_show_officer_role", interaction.locale),
            value=officer,
            inline=False,
        )
        perm_display = await self.bot.translate(
            "payout_level_officer"
            if config.pay_add_permission_level == "officer"
            else "payout_level_leader",
            interaction.locale,
        )
        embed.add_field(
            name=await self.bot.translate(
                "payout_config_show_pay_add_permission", interaction.locale
            ),
            value=perm_display,
            inline=False,
        )
        if config.updated_by:
            value = (
                (await self.bot.translate("payout_config_show_updated_by", interaction.locale))
                .replace("{user}", f"<@{config.updated_by}>")
                .replace("{date}", to_discord_timestamp(config.updated_at))
            )
        else:
            value = (
                await self.bot.translate("payout_config_show_updated", interaction.locale)
            ).replace("{date}", to_discord_timestamp(config.updated_at))
        embed.add_field(
            name=await self.bot.translate("payout_config_show_updated_label", interaction.locale),
            value=value,
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
