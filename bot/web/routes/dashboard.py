from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.bot_config_repository import BotConfigRepository
from bot.repositories.payout_config_repository import PayoutConfigRepository
from bot.repositories.transaction_repository import TransactionRepository
from bot.web.auth import require_auth

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
                "member_count": g.member_count if g else None,
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


@router.get("/guild/{guild_id}", response_class=HTMLResponse)
async def guild_overview(request: Request, guild_id: int):
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

    return templates.TemplateResponse(
        request=request,
        name="guild_overview.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": guild_info,
            "total_owed": total_owed,
            "active_players_count": len(balances),
            "active_payouts_count": active_payouts_count,
            "bot_cfg": bot_cfg,
            "payout_cfg": payout_cfg,
        },
    )


