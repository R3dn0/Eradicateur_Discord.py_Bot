from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.bot_config_repository import BotConfigRepository
from bot.repositories.payout_config_repository import PayoutConfigRepository
from bot.repositories.transaction_repository import TransactionRepository
from bot.web.auth import get_user_guild_permissions, require_auth

router = APIRouter(dependencies=[Depends(require_auth)], tags=["Dashboard"])


def get_available_guilds(bot) -> list[dict]:
    guilds_dict: dict[int, dict] = {}

    # 1. From active Discord guilds
    if hasattr(bot, "guilds"):
        for g in bot.guilds:
            guilds_dict[g.id] = {
                "id": g.id,
                "name": g.name,
                "icon": g.icon.url if g.icon else None,
                "member_count": g.member_count,
                "online": True,
            }

    # 2. From config.guild_id
    for gid in getattr(bot.config, "guild_id", []):
        if gid not in guilds_dict:
            g = bot.get_guild(gid) if hasattr(bot, "get_guild") else None
            guilds_dict[gid] = {
                "id": gid,
                "name": g.name if g else f"Guild #{gid}",
                "icon": g.icon.url if g and g.icon else None,
                "member_count": getattr(g, "member_count", len(getattr(g, "members", []))) if g else None,
                "online": g is not None,
            }

    # 3. From files on disk
    guilds_dir = Path(bot.config.data_dir) / "guilds"
    if guilds_dir.exists():
        for db_file in guilds_dir.glob("*.db"):
            try:
                gid = int(db_file.stem)
                if gid not in guilds_dict:
                    guilds_dict[gid] = {
                        "id": gid,
                        "name": f"Guild #{gid}",
                        "icon": None,
                        "member_count": None,
                        "online": False,
                    }
            except ValueError:
                continue

    return list(guilds_dict.values())


def ensure_valid_guild(bot, guild_id: int) -> dict:
    guilds = get_available_guilds(bot)
    guild_info = next((g for g in guilds if g["id"] == guild_id), None)
    if not guild_info:
        raise HTTPException(status_code=404, detail=f"Guild {guild_id} not found")
    return guild_info


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)

    # If exactly 1 guild exists, auto-redirect to it for speed
    if len(guilds) == 1:
        return RedirectResponse(url=f"/guild/{guilds[0]['id']}")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": None,
        },
    )


@router.get("/set-dev-role/{role}")
async def set_dev_role(request: Request, role: str, redirect: str = "/"):
    from bot.web.auth import is_dev_user

    bot = request.app.state.bot
    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))

    if not is_dev_user(bot, user_id):
        raise HTTPException(status_code=403, detail="Developer accounts only.")

    if role not in ("dev", "leader", "officer"):
        role = "dev"

    target_url = redirect if (redirect.startswith("/") and not redirect.startswith("//")) else "/"

    response = RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="dev_simulated_role",
        value=role,
        max_age=86400 * 30,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/guild/{guild_id}", response_class=HTMLResponse)
async def guild_overview(request: Request, guild_id: int):
    from bot.web.routes.balances import _resolve_creator_name, _resolve_member_name

    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    guild_info = ensure_valid_guild(bot, guild_id)

    # Fetch stats
    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    bot_cfg_repo = BotConfigRepository(conn)
    payout_cfg_repo = PayoutConfigRepository(conn)

    total_owed = await tx_repo.get_total_owed()
    balances = await tx_repo.list_balances()
    bot_cfg = await bot_cfg_repo.get_config()
    payout_cfg = await payout_cfg_repo.get_config()

    cursor = await conn.execute("SELECT COUNT(*) FROM payouts WHERE voided = 0")
    row = await cursor.fetchone()
    active_payouts_count = row[0] if row else 0

    # Recent Transactions (10)
    recent_txs_raw = await tx_repo.list_recent_transactions(limit=10)
    recent_transactions = []
    for tx in recent_txs_raw:
        player_name = await _resolve_member_name(bot, guild_id, tx.discord_id)
        creator_name = await _resolve_creator_name(bot, guild_id, tx.created_by)
        recent_transactions.append({
            "id": tx.id,
            "discord_id": tx.discord_id,
            "player_name": player_name,
            "amount": tx.amount,
            "reason": tx.reason,
            "payout_id": tx.payout_id,
            "created_by": tx.created_by,
            "creator_name": creator_name,
            "created_at": tx.created_at,
        })

    # Recent Payouts (10)
    cursor = await conn.execute("SELECT * FROM payouts ORDER BY created_at DESC, id DESC LIMIT 10")
    payout_rows = await cursor.fetchall()
    recent_payouts = []
    for p in payout_rows:
        creator_name = await _resolve_creator_name(bot, guild_id, p["created_by"])
        txs = await tx_repo.list_transactions_for_payout(p["id"])
        participants = []
        for tx in txs:
            member_name = await _resolve_member_name(bot, guild_id, tx.discord_id)
            participants.append({
                "discord_id": tx.discord_id,
                "name": member_name,
                "amount": tx.amount,
            })
        recent_payouts.append({
            "id": p["id"],
            "bag_silvers": p["bag_silvers"],
            "item_market_value": p["item_market_value"],
            "total_loot": p["bag_silvers"] + p["item_market_value"],
            "activity_cost": p["activity_cost"],
            "participant_count": p["participant_count"],
            "amount_per_player": p["amount_per_player"],
            "created_by": p["created_by"],
            "creator_name": creator_name,
            "created_at": p["created_at"],
            "voided": bool(p["voided"]),
            "participants": participants,
        })

    # Enriched balances for transaction and payout modal (catalog of all server members)
    from bot.web.routes.balances import get_cataloged_guild_members
    enriched_balances = await get_cataloged_guild_members(bot, guild_id, conn)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    return templates.TemplateResponse(
        request=request,
        name="guild_overview.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": guild_info,
            "total_owed": total_owed,
            "active_players_count": len([b for b in enriched_balances if b["balance"] != 0]),
            "active_payouts_count": active_payouts_count,
            "bot_cfg": bot_cfg,
            "payout_cfg": payout_cfg,
            "recent_transactions": recent_transactions,
            "recent_payouts": recent_payouts,
            "balances": enriched_balances,
            "user_perms": user_perms,
        },
    )



