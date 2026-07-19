import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot
from bot.repositories.bot_config_repository import (
    BotConfigRepository,
)
from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)
from bot.repositories.transaction_repository import (
    TransactionRepository,
)
from bot.services.payout_config_service import PayoutConfigService
from bot.utils.discord_dm import send_bulk_dm
from bot.utils.discord_guards import require_guild_member
from bot.utils.discord_time import to_discord_timestamp
from bot.utils.paginator import paginate_lines


class BalanceCog(
    commands.GroupCog, group_name=app_commands.locale_str("balance", key="balance_name")
):  # type: ignore[call-arg]
    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    @app_commands.command(
        name=app_commands.locale_str("show", key="balance_show_name"),
        description=app_commands.locale_str(
            "View a member's balance",
            key="balance_show_description",
        ),
    )
    @app_commands.describe(
        member=app_commands.locale_str(
            "Member whose balance to view. Omit to see your own.",
            key="balance_show_member_description",
        ),
    )
    @require_guild_member
    async def show(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        transaction_repo = TransactionRepository(db)

        if member is None:
            balance = await transaction_repo.get_balance(interaction.user.id)
            template = await self.bot.translate("balance_show_self", interaction.locale)
            embed = discord.Embed(
                description=template.replace("{balance}", f"{balance:,.0f}"),
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)

        if not await payout_config_service.check_pay_add_permission(interaction.user):
            level = await payout_config_service._repo.get_config()
            level = level.pay_add_permission_level
            if level == "leader":
                msg = await self.bot.translate("balance_leader_only", interaction.locale)
            else:
                msg = await self.bot.translate("balance_officer_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        balance = await transaction_repo.get_balance(member.id)
        template = await self.bot.translate("balance_show_other", interaction.locale)
        embed = discord.Embed(
            description=template.replace("{joueur}", member.mention).replace(
                "{balance}", f"{balance:,.0f}"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name=app_commands.locale_str("history", key="balance_history_name"),
        description=app_commands.locale_str(
            "View a member's transaction history",
            key="balance_history_description",
        ),
    )
    @app_commands.describe(
        member=app_commands.locale_str(
            "Member whose history to view. Omit to see your own.",
            key="balance_history_member_description",
        ),
    )
    @require_guild_member
    async def history(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        transaction_repo = TransactionRepository(db)

        if member is None:
            discord_id = interaction.user.id
        else:
            payout_config_repo = PayoutConfigRepository(db)
            payout_config_service = PayoutConfigService(payout_config_repo)

            if not await payout_config_service.check_pay_add_permission(interaction.user):
                level_config = await payout_config_repo.get_config()
                level = level_config.pay_add_permission_level
                if level == "leader":
                    msg = await self.bot.translate(
                        "balance_history_leader_only", interaction.locale
                    )
                else:
                    msg = await self.bot.translate(
                        "balance_history_officer_only", interaction.locale
                    )
                await interaction.response.send_message(msg, ephemeral=True)
                return
            discord_id = member.id

        txs = await transaction_repo.list_transactions(discord_id)
        if not txs:
            msg = await self.bot.translate("balance_history_empty", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        line_template = await self.bot.translate("balance_history_entry", interaction.locale)
        lines: list[str] = []
        for tx in txs:
            ts = to_discord_timestamp(tx.created_at)
            sign = "+" if tx.amount >= 0 else ""
            lines.append(
                line_template.replace("{date}", ts)
                .replace("{montant}", f"{sign}{tx.amount:,.0f}")
                .replace("{raison}", tx.reason)
            )

        title_template = await self.bot.translate("balance_history_title", interaction.locale)
        title = title_template.replace("{joueur}", f"<@{discord_id}>")
        view = paginate_lines(lines, title=title)
        await interaction.response.send_message(
            embed=view._build_embed(), view=view, ephemeral=True
        )

    @app_commands.command(
        name=app_commands.locale_str("list", key="balance_list_name"),
        description=app_commands.locale_str(
            "List all members with a non-zero balance",
            key="balance_list_description",
        ),
    )
    @require_guild_member
    async def list_(self, interaction: discord.Interaction) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)
        transaction_repo = TransactionRepository(db)

        if not await payout_config_service.check_pay_add_permission(interaction.user):
            level = await payout_config_service._repo.get_config()
            level = level.pay_add_permission_level
            if level == "leader":
                msg = await self.bot.translate("balance_leader_only", interaction.locale)
            else:
                msg = await self.bot.translate("balance_officer_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        balances = await transaction_repo.list_balances()
        if not balances:
            msg = await self.bot.translate("balance_list_empty", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        title = await self.bot.translate("balance_list_title", interaction.locale)
        line_template = await self.bot.translate("balance_list_entry", interaction.locale)

        lines: list[str] = []
        for discord_id, bal in balances:
            lines.append(
                line_template.replace("{joueur}", f"<@{discord_id}>").replace(
                    "{balance}", f"{bal:,.0f}"
                )
            )

        view = paginate_lines(lines, title=title)
        await interaction.response.send_message(
            embed=view._build_embed(), view=view, ephemeral=True
        )

    @app_commands.command(
        name=app_commands.locale_str("payer", key="balance_payer_name"),
        description=app_commands.locale_str(
            "Manually withdraw from a player's balance",
            key="balance_payer_description",
        ),
    )
    @app_commands.describe(
        joueur=app_commands.locale_str(
            "Member whose balance will be debited",
            key="balance_payer_joueur_description",
        ),
        montant=app_commands.locale_str(
            "Amount to withdraw (must be > 0)",
            key="balance_payer_montant_description",
        ),
    )
    @require_guild_member
    async def pay(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        montant: int,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)

        if not await payout_config_service.check_pay_add_permission(interaction.user):
            level_config = await payout_config_repo.get_config()
            if level_config.pay_add_permission_level == "leader":
                msg = await self.bot.translate("balance_payer_leader_only", interaction.locale)
            else:
                msg = await self.bot.translate("balance_payer_officer_only", interaction.locale)
            await interaction.edit_original_response(content=msg)
            return

        if montant <= 0:
            msg = await self.bot.translate("payout_amount_positive", interaction.locale)
            await interaction.edit_original_response(content=msg)
            return

        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE discord_id = ?",
                (joueur.id,),
            )
            row = await cursor.fetchone()
            balance = int(row[0])
            if montant > balance:
                await db.rollback()
                template = await self.bot.translate(
                    "balance_payer_insufficient_balance", interaction.locale
                )
                await interaction.edit_original_response(
                    content=template.replace("{joueur}", joueur.mention)
                    .replace("{balance}", f"{balance:,.0f}")
                    .replace("{montant}", f"{montant:,.0f}"),
                )
                return

            await db.execute(
                "INSERT INTO transactions (discord_id, amount, reason, created_by) "
                "VALUES (?, ?, ?, ?)",
                (joueur.id, -montant, "Manual withdrawal", interaction.user.id),
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

        cursor = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE discord_id = ?",
            (joueur.id,),
        )
        row = await cursor.fetchone()
        new_balance = int(row[0])

        bot_config_repo = BotConfigRepository(db)
        bot_config = await bot_config_repo.get_config()
        no_dm_role_id = bot_config.notification_opt_out_role_id

        dm_title = await self.bot.translate("balance_dm_pay_title", interaction.locale)
        dm_amount = await self.bot.translate("balance_dm_amount_debited", interaction.locale)
        dm_new_balance = await self.bot.translate("balance_dm_new_balance", interaction.locale)

        async def _build_pay_content(member: discord.Member) -> discord.Embed:
            embed = discord.Embed(title=dm_title, color=discord.Color.red())
            embed.add_field(name=dm_amount, value=f"{montant:,.0f}", inline=True)
            embed.add_field(name=dm_new_balance, value=f"{new_balance:,.0f}", inline=True)
            return embed

        dm_context_template = await self.bot.translate("dm_context", interaction.locale)
        action = await self.bot.translate("balance_pay_dm_action", interaction.locale)
        context = dm_context_template.replace("{user}", interaction.user.mention).replace(
            "{action}", action
        )

        result = await send_bulk_dm(
            guild=interaction.guild,
            member_ids=[joueur.id],
            build_content=_build_pay_content,
            opt_out_role_id=no_dm_role_id,
            context=context,
        )

        template = await self.bot.translate("balance_payer_paid", interaction.locale)
        msg = (
            template.replace("{montant}", f"{montant:,.0f}")
            .replace("{joueur}", joueur.mention)
            .replace("{balance}", f"{new_balance:,.0f}")
        )

        if result.skipped:
            optout_note = await self.bot.translate("payout_dm_optout_note", interaction.locale)
            msg += "\n" + optout_note.replace("{n}", str(len(result.skipped)))

        if result.failed:
            failure_note = await self.bot.translate("payout_dm_failure_note", interaction.locale)
            failed_mentions = ", ".join(f"<@{uid}>" for uid in result.failed)
            msg += "\n" + failure_note.replace("{users}", failed_mentions)

        await interaction.edit_original_response(content=msg)

    @app_commands.command(
        name=app_commands.locale_str("ajouter", key="balance_ajouter_name"),
        description=app_commands.locale_str(
            "Manually credit a player's balance",
            key="balance_ajouter_description",
        ),
    )
    @app_commands.describe(
        joueur=app_commands.locale_str(
            "Member whose balance will be credited",
            key="balance_ajouter_joueur_description",
        ),
        montant=app_commands.locale_str(
            "Amount to add (must be > 0)",
            key="balance_ajouter_montant_description",
        ),
        raison=app_commands.locale_str(
            "Reason for the credit",
            key="balance_ajouter_raison_description",
        ),
    )
    @require_guild_member
    async def add(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        montant: int,
        raison: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)
        transaction_repo = TransactionRepository(db)

        if not await payout_config_service.check_pay_add_permission(interaction.user):
            level_config = await payout_config_repo.get_config()
            if level_config.pay_add_permission_level == "leader":
                msg = await self.bot.translate("balance_ajouter_leader_only", interaction.locale)
            else:
                msg = await self.bot.translate("balance_ajouter_officer_only", interaction.locale)
            await interaction.edit_original_response(content=msg)
            return

        if montant <= 0:
            msg = await self.bot.translate("payout_amount_positive", interaction.locale)
            await interaction.edit_original_response(content=msg)
            return

        await transaction_repo.add_transaction(
            discord_id=joueur.id,
            amount=montant,
            reason=raison,
            created_by=interaction.user.id,
        )

        new_balance = await transaction_repo.get_balance(joueur.id)

        bot_config_repo = BotConfigRepository(db)
        bot_config = await bot_config_repo.get_config()
        no_dm_role_id = bot_config.notification_opt_out_role_id

        dm_title = await self.bot.translate("balance_dm_add_title", interaction.locale)
        dm_amount = await self.bot.translate("balance_dm_amount_credited", interaction.locale)
        dm_new_balance = await self.bot.translate("balance_dm_new_balance", interaction.locale)
        dm_reason = await self.bot.translate("balance_dm_reason", interaction.locale)

        async def _build_add_content(member: discord.Member) -> discord.Embed:
            embed = discord.Embed(title=dm_title, color=discord.Color.green())
            embed.add_field(name=dm_amount, value=f"{montant:,.0f}", inline=True)
            embed.add_field(name=dm_reason, value=raison, inline=False)
            embed.add_field(name=dm_new_balance, value=f"{new_balance:,.0f}", inline=True)
            return embed

        dm_context_template = await self.bot.translate("dm_context", interaction.locale)
        action = await self.bot.translate("balance_add_dm_action", interaction.locale)
        context = dm_context_template.replace("{user}", interaction.user.mention).replace(
            "{action}", action
        )

        result = await send_bulk_dm(
            guild=interaction.guild,
            member_ids=[joueur.id],
            build_content=_build_add_content,
            opt_out_role_id=no_dm_role_id,
            context=context,
        )

        template = await self.bot.translate("balance_ajouter_credited", interaction.locale)
        msg = (
            template.replace("{montant}", f"{montant:,.0f}")
            .replace("{joueur}", joueur.mention)
            .replace("{raison}", raison)
            .replace("{balance}", f"{new_balance:,.0f}")
        )

        if result.skipped:
            optout_note = await self.bot.translate("payout_dm_optout_note", interaction.locale)
            msg += "\n" + optout_note.replace("{n}", str(len(result.skipped)))

        if result.failed:
            failure_note = await self.bot.translate("payout_dm_failure_note", interaction.locale)
            failed_mentions = ", ".join(f"<@{uid}>" for uid in result.failed)
            msg += "\n" + failure_note.replace("{users}", failed_mentions)

        await interaction.edit_original_response(content=msg)
