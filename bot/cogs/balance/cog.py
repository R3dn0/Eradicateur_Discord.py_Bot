import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot
from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)
from bot.repositories.transaction_repository import (
    TransactionRepository,
)
from bot.services.payout_config_service import PayoutConfigService

_MAX_EMBED_DESC = 4096
_MAX_LINES = 40


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
    async def show(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

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

        if not isinstance(interaction.user, discord.Member):
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

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
        name=app_commands.locale_str("list", key="balance_list_name"),
        description=app_commands.locale_str(
            "List all members with a non-zero balance",
            key="balance_list_description",
        ),
    )
    async def list_(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)
        transaction_repo = TransactionRepository(db)

        if not isinstance(interaction.user, discord.Member):
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

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

        pages: list[str] = []
        current_lines: list[str] = []

        for discord_id, bal in balances:
            line = line_template.replace("{joueur}", f"<@{discord_id}>").replace(
                "{balance}", f"{bal:,.0f}"
            )
            tentative = "\n".join(current_lines + [line])
            if len(tentative) > _MAX_EMBED_DESC or len(current_lines) >= _MAX_LINES:
                pages.append("\n".join(current_lines))
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            pages.append("\n".join(current_lines))

        if len(pages) == 1:
            embed = discord.Embed(
                title=title,
                description=pages[0],
                color=discord.Color.blue(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title=title,
                description=pages[0],
                color=discord.Color.blue(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            for page in pages[1:]:
                embed = discord.Embed(
                    description=page,
                    color=discord.Color.blue(),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)

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
    async def payer(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        montant: float,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if interaction.guild is None:
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)
        transaction_repo = TransactionRepository(db)

        if not await payout_config_service.check_pay_add_permission(interaction.user):
            level_config = await payout_config_repo.get_config()
            if level_config.pay_add_permission_level == "leader":
                msg = await self.bot.translate("balance_payer_leader_only", interaction.locale)
            else:
                msg = await self.bot.translate("balance_payer_officer_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if montant <= 0:
            msg = await self.bot.translate("payout_amount_positive", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        balance = await transaction_repo.get_balance(joueur.id)
        if montant > balance:
            template = await self.bot.translate(
                "balance_payer_insufficient_balance", interaction.locale
            )
            await interaction.response.send_message(
                template.replace("{joueur}", joueur.mention)
                .replace("{balance}", f"{balance:,.0f}")
                .replace("{montant}", f"{montant:,.0f}"),
                ephemeral=True,
            )
            return

        await transaction_repo.add_transaction(
            discord_id=joueur.id,
            amount=-montant,
            reason="Manual withdrawal",
            created_by=interaction.user.id,
        )

        new_balance = await transaction_repo.get_balance(joueur.id)
        template = await self.bot.translate("balance_payer_paid", interaction.locale)
        await interaction.response.send_message(
            template.replace("{montant}", f"{montant:,.0f}")
            .replace("{joueur}", joueur.mention)
            .replace("{balance}", f"{new_balance:,.0f}"),
            ephemeral=True,
        )

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
    async def ajouter(
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

        if interaction.guild is None:
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

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
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if montant <= 0:
            msg = await self.bot.translate("payout_amount_positive", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await transaction_repo.add_transaction(
            discord_id=joueur.id,
            amount=montant,
            reason=raison,
            created_by=interaction.user.id,
        )

        new_balance = await transaction_repo.get_balance(joueur.id)
        template = await self.bot.translate("balance_ajouter_credited", interaction.locale)
        await interaction.response.send_message(
            template.replace("{montant}", f"{montant:,.0f}")
            .replace("{joueur}", joueur.mention)
            .replace("{raison}", raison)
            .replace("{balance}", f"{new_balance:,.0f}"),
            ephemeral=True,
        )
