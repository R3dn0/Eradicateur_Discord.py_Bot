import logging

import discord
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.bot_config_repository import BotConfigRepository
from bot.repositories.payout_config_repository import PayoutConfigRepository
from bot.repositories.payout_repository import PayoutRepository
from bot.repositories.transaction_repository import TransactionRepository
from bot.services.payout_config_service import PayoutConfigService
from bot.services.payout_service import compute_split
from bot.utils.discord_dm import send_bulk_dm
from bot.utils.discord_time import to_discord_timestamp
from bot.web.audit import log_db_action
from bot.web.auth import get_user_guild_permissions, require_auth
from bot.web.i18n import get_web_locale
from bot.web.routes.balances import _resolve_member_name
from bot.web.routes.dashboard import ensure_valid_guild, get_available_guilds

logger = logging.getLogger("eradicateur_bot.web.payouts")
router = APIRouter(dependencies=[Depends(require_auth)], tags=["Payouts"])


@router.get("/payouts")
@router.get("/payout")
async def payouts_root_redirect(request: Request):
    bot = request.app.state.bot
    guilds = get_available_guilds(bot)
    if guilds:
        return RedirectResponse(url=f"/guild/{guilds[0]['id']}/payouts")
    return RedirectResponse(url="/")


@router.get("/guild/{guild_id}/payouts", response_class=HTMLResponse)
async def list_payouts(request: Request, guild_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    payout_repo = PayoutRepository(conn, tx_repo)
    payout_cfg_repo = PayoutConfigRepository(conn)

    payout_cfg = await payout_cfg_repo.get_config()
    balances = await tx_repo.list_balances()

    cursor = await conn.execute("SELECT * FROM payouts ORDER BY id DESC")
    rows = await cursor.fetchall()

    payouts = []
    for row in rows:
        creator_name = await _resolve_member_name(bot, guild_id, row["created_by"]) if row["created_by"] else "Admin"
        payouts.append({
            "id": row["id"],
            "bag_silvers": row["bag_silvers"],
            "item_market_value": row["item_market_value"],
            "activity_cost": row["activity_cost"],
            "participant_count": row["participant_count"],
            "amount_per_player": row["amount_per_player"],
            "buyback_value": row["buyback_value"],
            "created_by": row["created_by"],
            "creator_name": creator_name,
            "created_at": row["created_at"],
            "voided": bool(row["voided"]),
            "voided_by": row["voided_by"],
            "voided_at": row["voided_at"],
        })

    from bot.web.routes.balances import get_cataloged_guild_members
    enriched_balances = await get_cataloged_guild_members(bot, guild_id, conn)

    return templates.TemplateResponse(
        request=request,
        name="payouts.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "payouts": payouts,
            "payout_cfg": payout_cfg,
            "balances": enriched_balances,
            "user_perms": user_perms,
        },
    )


@router.get("/guild/{guild_id}/payouts/{payout_id}", response_class=HTMLResponse)
async def payout_detail(request: Request, guild_id: int, payout_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    if payout_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid payout ID")

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    payout_repo = PayoutRepository(conn, tx_repo)

    payout = await payout_repo.get_payout(payout_id)
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found")

    transactions = await tx_repo.list_transactions_for_payout(payout_id)
    creator_name = await _resolve_member_name(bot, guild_id, payout.created_by) if payout.created_by else "Admin"

    participants = []
    for tx in transactions:
        member_name = await _resolve_member_name(bot, guild_id, tx.discord_id)
        participants.append({
            "discord_id": tx.discord_id,
            "name": member_name,
            "amount": tx.amount,
        })

    return templates.TemplateResponse(
        request=request,
        name="payout_detail.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "payout": payout,
            "creator_name": creator_name,
            "participants": participants,
            "user_perms": user_perms,
        },
    )


@router.post("/guild/{guild_id}/payouts/{payout_id}/void")
async def void_payout_action(request: Request, guild_id: int, payout_id: int):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    if not user_perms["can_manage_payouts"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Officer or Leader role required to void payouts.",
        )

    if payout_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid payout ID")

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    payout_repo = PayoutRepository(conn, tx_repo)

    try:
        await payout_repo.void_payout(payout_id=payout_id, voided_by=user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_db_action(
        request,
        guild_id,
        "PAYOUT_VOID",
        f"Voided Payout #{payout_id}",
    )

    return RedirectResponse(
        url=f"/guild/{guild_id}/payouts/{payout_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/payouts/create")
async def create_payout_action(
    request: Request,
    guild_id: int,
    bag_silvers: int = Form(0),
    item_market_value: int = Form(0),
    activity_cost: int = Form(0),
    participant_ids: str = Form(""),
):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    if not user_perms["can_manage_payouts"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Officer or Leader role required to create payouts.",
        )

    if bag_silvers < 0 or item_market_value < 0 or activity_cost < 0:
        raise HTTPException(status_code=400, detail="Amounts must be non-negative")

    if bag_silvers <= 0 and item_market_value <= 0:
        raise HTTPException(status_code=400, detail="At least bag silvers or item value must be strictly positive")

    # Parse and deduplicate participant IDs
    raw_ids = [p.strip() for p in participant_ids.replace(",", " ").split() if p.strip()]
    clean_ids: list[int] = []
    seen = set()
    for raw in raw_ids:
        try:
            pid = int(raw)
            if pid > 0 and pid not in seen:
                clean_ids.append(pid)
                seen.add(pid)
        except ValueError:
            continue

    if not clean_ids:
        raise HTTPException(status_code=400, detail="At least one valid participant ID is required")

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    payout_repo = PayoutRepository(conn, tx_repo)
    payout_cfg_repo = PayoutConfigRepository(conn)
    bot_cfg_repo = BotConfigRepository(conn)

    payout_cfg_service = PayoutConfigService(payout_cfg_repo)
    rates = await payout_cfg_service.get_rates()
    payout_cfg = await payout_cfg_repo.get_config()
    bot_cfg = await bot_cfg_repo.get_config()

    n = len(clean_ids)
    split = compute_split(
        bag_silvers=bag_silvers,
        item_market_value=item_market_value,
        activity_cost=activity_cost,
        rates=rates,
        participant_count=n,
    )

    current_user = getattr(request.state, "user", None) or {}
    raw_uid = current_user.get("id")
    actor_name = current_user.get("display_name") or "Dashboard Admin"
    try:
        created_by = int(raw_uid) if raw_uid else 0
    except (ValueError, TypeError):
        created_by = 0

    try:
        payout_id = await payout_repo.create_payout(
            bag_silvers=bag_silvers,
            item_market_value=item_market_value,
            activity_cost=activity_cost,
            tax_market=rates.market,
            tax_guild=rates.guild,
            tax_transport=rates.transport,
            amount_per_player=split.amount_per_player,
            buyback_value=split.buyback_value,
            participant_ids=clean_ids,
            created_by=created_by,
        )
    except Exception as e:
        logger.exception("Failed to create payout via web: %s", e)
        raise HTTPException(status_code=500, detail="Failed to record payout in database")

    log_db_action(
        request,
        guild_id,
        "PAYOUT_CREATE",
        f"Created Payout #{payout_id} | Total Loot: {bag_silvers + item_market_value} | Net/Player: {split.amount_per_player} | Participants: {n}",
    )

    # Discord Notifications & Embed posting if bot is connected
    guild = bot.get_guild(guild_id) if hasattr(bot, "get_guild") else None
    if guild and hasattr(bot, "translate"):
        locale = get_web_locale(request)
        discord_locale = "fr" if locale == "fr" else "en-US"
        creator_tag = f"<@{created_by}>" if created_by else actor_name

        # 1. Send DMs to participants
        dm_title = await bot.translate("payout_dm_title", discord_locale)
        dm_received = await bot.translate("payout_dm_received", discord_locale)
        dm_new_balance = await bot.translate("payout_dm_new_balance", discord_locale)

        async def _build_content(member: discord.Member) -> discord.Embed:
            new_balance = await tx_repo.get_balance(member.id)
            embed = discord.Embed(
                title=dm_title,
                color=discord.Color.gold(),
            )
            embed.add_field(name=dm_received, value=f"{split.amount_per_player:,.0f}", inline=True)
            embed.add_field(name=dm_new_balance, value=f"{new_balance:,.0f}", inline=True)
            return embed

        context_template = await bot.translate("dm_context", discord_locale)
        context = context_template.replace("{user}", creator_tag).replace("{action}", f"Payout #{payout_id}")

        try:
            await send_bulk_dm(
                guild=guild,
                member_ids=clean_ids,
                build_content=_build_content,
                opt_out_role_id=bot_cfg.notification_opt_out_role_id,
                context=context,
            )
        except Exception as e:
            logger.warning("Error sending bulk DMs from web payout: %s", e)

        # 2. Public announcement embed
        item_label = await bot.translate("payout_embed_item", discord_locale)
        gain_label = await bot.translate("payout_embed_gain", discord_locale)
        cost_label = await bot.translate("payout_embed_cost", discord_locale)
        part_label = await bot.translate("payout_embed_participants", discord_locale)
        split_label = await bot.translate("payout_embed_split", discord_locale)
        buyback_label = await bot.translate("payout_embed_buyback", discord_locale)
        per_player_label = await bot.translate("payout_embed_per_player", discord_locale)
        created_by_label = await bot.translate("payout_embed_created_by", discord_locale)

        mentions = "\n".join(f"<@{uid}>" for uid in clean_ids)
        public_embed = discord.Embed(
            title=f"Payout #{payout_id}",
            color=discord.Color.gold(),
        )
        public_embed.add_field(name=item_label, value=f"{item_market_value:,.0f}", inline=True)
        public_embed.add_field(name=gain_label, value=f"{bag_silvers:,.0f}", inline=True)
        public_embed.add_field(name=cost_label, value=f"{activity_cost:,.0f}", inline=True)
        public_embed.add_field(name=split_label, value=f"{split.total_pool:,.0f}", inline=True)
        public_embed.add_field(name=buyback_label, value=f"{split.buyback_value:,.0f}", inline=True)
        participants_value = f"{mentions}\n{per_player_label.replace('{amount}', f'{split.amount_per_player:,.0f}')}"
        public_embed.add_field(name=f"{part_label} ({n})", value=participants_value, inline=False)

        payout_obj = await payout_repo.get_payout(payout_id)
        created_value = created_by_label.replace("{user}", creator_tag).replace(
            "{date}",
            to_discord_timestamp(payout_obj.created_at) if payout_obj else "now",
        )
        public_embed.add_field(name="\u200b", value=created_value, inline=False)

        # Target channel: configured payout_channel_id or log_channel_id
        target_channel_id = payout_cfg.payout_channel_id or bot_cfg.log_channel_id
        target_channel = None
        if target_channel_id:
            target_channel = guild.get_channel(target_channel_id)
            if not target_channel and hasattr(bot, "fetch_channel"):
                try:
                    target_channel = await bot.fetch_channel(target_channel_id)
                except Exception as e:
                    logger.warning("Could not fetch channel %s: %s", target_channel_id, e)

        if target_channel:
            try:
                await target_channel.send(embed=public_embed)
                logger.info(
                    "[Web] Payout #%s public embed sent to channel %s (%s)",
                    payout_id,
                    getattr(target_channel, "name", "channel"),
                    target_channel_id,
                )
            except Exception as e:
                logger.warning("Failed to post public payout embed to channel #%s: %s", target_channel_id, e)
        else:
            logger.warning("No target channel found for payout #%s public embed (channel_id=%s)", payout_id, target_channel_id)

    return RedirectResponse(
        url=f"/guild/{guild_id}/payouts/{payout_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


