from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from bot.repositories.bot_config_repository import BotConfigRepository
from bot.utils.discord_dm import BulkDMResult, send_bulk_dm

if TYPE_CHECKING:
    from bot.main import EradicateurBot

logger = logging.getLogger("eradicateur_bot.balance_notification")


async def send_balance_transaction_dm(
    bot: EradicateurBot,
    guild: discord.Guild,
    target_user_id: int,
    amount: int,
    is_credit: bool,
    new_balance: int,
    reason: str | None,
    actor_id: int | None = None,
    actor_name: str | None = None,
    locale: str | discord.Locale | None = None,
) -> BulkDMResult:
    """Send a unified direct message to a user when their balance is credited or debited."""
    assert bot.db_manager is not None
    db = await bot.db_manager.get_connection(guild.id)
    bot_config_repo = BotConfigRepository(db)
    bot_config = await bot_config_repo.get_config()
    no_dm_role_id = bot_config.notification_opt_out_role_id

    if is_credit:
        title = await bot.translate("balance_dm_add_title", locale)
        amount_label = await bot.translate("balance_dm_amount_credited", locale)
        color = discord.Color.green()
    else:
        title = await bot.translate("balance_dm_pay_title", locale)
        amount_label = await bot.translate("balance_dm_amount_debited", locale)
        color = discord.Color.red()

    new_balance_label = await bot.translate("balance_dm_new_balance", locale)
    reason_label = await bot.translate("balance_dm_reason", locale)
    performed_by_label = await bot.translate("balance_dm_performed_by", locale)

    dev_users = getattr(getattr(bot, "config", None), "dashboard_dev_users", None) or [135489084385787905]
    if (actor_id and actor_id in dev_users) or (actor_name and ("dev" in actor_name.lower() or "😎" in actor_name)):
        actor_str = "Dev 😎"
    elif actor_id and actor_id > 0:
        actor_str = f"<@{actor_id}>"
    elif actor_name:
        actor_str = actor_name
    else:
        actor_str = "Admin"

    clean_amount = abs(amount)

    async def _build_content(member: discord.Member) -> discord.Embed:
        embed = discord.Embed(title=title, color=color)
        # Line 1: | Montant transaction | Nouveau solde | (inline)
        embed.add_field(name=amount_label, value=f"{clean_amount:,.0f}", inline=True)
        embed.add_field(name=new_balance_label, value=f"{new_balance:,.0f}", inline=True)

        # Line 2: Raison (if present)
        if reason and reason.strip():
            clean_reason = reason.strip()
            if clean_reason.startswith("[Dash] "):
                clean_reason = clean_reason[7:].strip()
            if clean_reason:
                embed.add_field(name=reason_label, value=clean_reason, inline=False)

        # Line 3: Effectué par @personne (single line)
        embed.add_field(
            name="\u200b",
            value=f"**{performed_by_label} :** {actor_str}",
            inline=False,
        )
        return embed

    return await send_bulk_dm(
        guild=guild,
        member_ids=[target_user_id],
        build_content=_build_content,
        opt_out_role_id=no_dm_role_id,
        context="",
    )
