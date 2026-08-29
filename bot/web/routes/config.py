from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.bot_config_repository import BotConfigRepository
from bot.repositories.payout_config_repository import PayoutConfigRepository
from bot.web.auth import require_auth
from bot.web.routes.dashboard import get_available_guilds

router = APIRouter(dependencies=[Depends(require_auth)], tags=["Config"])


@router.get("/guild/{guild_id}/config", response_class=HTMLResponse)
async def view_config(request: Request, guild_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = next((g for g in guilds if g["id"] == guild_id), {"id": guild_id, "name": f"Guild #{guild_id}"})

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
    conn = await bot.db_manager.get_connection(guild_id)
    payout_cfg_repo = PayoutConfigRepository(conn)

    # Convert percentages (if entered as 0-100 or 0-1)
    m = tax_market / 100.0 if tax_market > 1.0 else tax_market
    g = tax_guild / 100.0 if tax_guild > 1.0 else tax_guild
    t = tax_transport / 100.0 if tax_transport > 1.0 else tax_transport

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
    conn = await bot.db_manager.get_connection(guild_id)
    payout_cfg_repo = PayoutConfigRepository(conn)

    off_id = int(officer_role_id.strip()) if officer_role_id.strip() else None
    ldr_id = int(leader_role_id.strip()) if leader_role_id.strip() else None

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
    conn = await bot.db_manager.get_connection(guild_id)
    bot_cfg_repo = BotConfigRepository(conn)

    opt_role_id = int(notification_opt_out_role_id.strip()) if notification_opt_out_role_id.strip() else None
    log_ch_id = int(log_channel_id.strip()) if log_channel_id.strip() else None

    await bot_cfg_repo.update_opt_out_role(role_id=opt_role_id, updated_by=0)
    await bot_cfg_repo.update_log_channel(channel_id=log_ch_id, updated_by=0)

    return RedirectResponse(
        url=f"/guild/{guild_id}/config?saved=bot",
        status_code=status.HTTP_303_SEE_OTHER,
    )

