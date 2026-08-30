import logging
import math

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.bot_config_repository import BotConfigRepository
from bot.repositories.payout_config_repository import PayoutConfigRepository
from bot.web.auth import require_auth
from bot.web.routes.dashboard import ensure_valid_guild, get_available_guilds

logger = logging.getLogger("eradicateur_bot.web.config")
router = APIRouter(dependencies=[Depends(require_auth)], tags=["Config"])


def _parse_optional_id(raw: str, field_name: str) -> int | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        val = int(cleaned)
        if val <= 0:
            raise ValueError()
        return val
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}. Must be a valid positive numeric ID.")


@router.get("/config")
async def config_root_redirect(request: Request):
    bot = request.app.state.bot
    guilds = get_available_guilds(bot)
    if guilds:
        return RedirectResponse(url=f"/guild/{guilds[0]['id']}/config")
    return RedirectResponse(url="/")


@router.get("/guild/{guild_id}/config", response_class=HTMLResponse)
async def view_config(request: Request, guild_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = ensure_valid_guild(bot, guild_id)

    conn = await bot.db_manager.get_connection(guild_id)
    bot_cfg_repo = BotConfigRepository(conn)
    payout_cfg_repo = PayoutConfigRepository(conn)

    bot_cfg = await bot_cfg_repo.get_config()
    payout_cfg = await payout_cfg_repo.get_config()

    # Get roles and channels list from discord guild if connected
    roles = []
    channels = []
    if hasattr(bot, "get_guild"):
        guild = bot.get_guild(guild_id)
        if guild:
            roles = [{"id": r.id, "name": r.name} for r in guild.roles if not r.is_default()]
            channels = [{"id": c.id, "name": c.name} for c in guild.text_channels]

    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "bot_cfg": bot_cfg,
            "payout_cfg": payout_cfg,
            "roles": roles,
            "channels": channels,
            "success_msg": request.query_params.get("saved"),
        },
    )


@router.post("/guild/{guild_id}/config/rates")
async def update_rates(
    request: Request,
    guild_id: int,
    tax_market: float = Form(...),
    tax_guild: float = Form(...),
    tax_transport: float = Form(...),
):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    # Validate range and reject NaN / Inf
    for name, val in [("tax_market", tax_market), ("tax_guild", tax_guild), ("tax_transport", tax_transport)]:
        if math.isnan(val) or math.isinf(val) or val < 0.0 or val > 100.0:
            raise HTTPException(status_code=400, detail=f"Invalid value for {name}: must be between 0% and 100%")

    # Convert percentages (if entered as 0-100 or 0-1)
    m = tax_market / 100.0 if tax_market > 1.0 else tax_market
    g = tax_guild / 100.0 if tax_guild > 1.0 else tax_guild
    t = tax_transport / 100.0 if tax_transport > 1.0 else tax_transport

    conn = await bot.db_manager.get_connection(guild_id)
    payout_cfg_repo = PayoutConfigRepository(conn)

    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        "Admin (IP %s) updated tax rates for Guild %s: Market=%.4f, Guild=%.4f, Transport=%.4f",
        client_ip,
        guild_id,
        m,
        g,
        t,
    )

    await payout_cfg_repo.update_rates(market=m, guild=g, transport=t, updated_by=0)

    return RedirectResponse(
        url=f"/guild/{guild_id}/config?saved=rates",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/config/roles")
async def update_roles(
    request: Request,
    guild_id: int,
    officer_role_id: str = Form(""),
    leader_role_id: str = Form(""),
    pay_add_permission_level: str = Form("officer"),
):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    if pay_add_permission_level not in ("officer", "leader"):
        raise HTTPException(status_code=400, detail="Invalid permission level: must be 'officer' or 'leader'")

    off_id = _parse_optional_id(officer_role_id, "officer_role_id")
    ldr_id = _parse_optional_id(leader_role_id, "leader_role_id")

    conn = await bot.db_manager.get_connection(guild_id)
    payout_cfg_repo = PayoutConfigRepository(conn)

    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        "Admin (IP %s) updated roles for Guild %s: Officer=%s, Leader=%s, Level=%s",
        client_ip,
        guild_id,
        off_id,
        ldr_id,
        pay_add_permission_level,
    )

    await payout_cfg_repo.update_roles(officer_role_id=off_id, leader_role_id=ldr_id, updated_by=0)
    await payout_cfg_repo.update_pay_add_permission_level(level=pay_add_permission_level, updated_by=0)

    return RedirectResponse(
        url=f"/guild/{guild_id}/config?saved=roles",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/config/bot")
async def update_bot_config(
    request: Request,
    guild_id: int,
    notification_opt_out_role_id: str = Form(""),
    log_channel_id: str = Form(""),
):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    opt_role_id = _parse_optional_id(notification_opt_out_role_id, "notification_opt_out_role_id")
    log_ch_id = _parse_optional_id(log_channel_id, "log_channel_id")

    conn = await bot.db_manager.get_connection(guild_id)
    bot_cfg_repo = BotConfigRepository(conn)

    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        "Admin (IP %s) updated bot config for Guild %s: OptOutRole=%s, LogChannel=%s",
        client_ip,
        guild_id,
        opt_role_id,
        log_ch_id,
    )

    await bot_cfg_repo.update_opt_out_role(role_id=opt_role_id, updated_by=0)
    await bot_cfg_repo.update_log_channel(channel_id=log_ch_id, updated_by=0)

    return RedirectResponse(
        url=f"/guild/{guild_id}/config?saved=bot",
        status_code=status.HTTP_303_SEE_OTHER,
    )


