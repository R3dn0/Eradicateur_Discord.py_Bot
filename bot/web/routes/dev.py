from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.web.auth import require_dev_auth
from bot.web.routes.dashboard import ensure_valid_guild, get_available_guilds

router = APIRouter(dependencies=[Depends(require_dev_auth)], tags=["Dev"])


@router.get("/dev")
async def dev_root_redirect(request: Request):
    bot = request.app.state.bot
    guilds = get_available_guilds(bot)
    if guilds:
        return RedirectResponse(url=f"/guild/{guilds[0]['id']}/logs?log_type=global")
    return RedirectResponse(url="/")


@router.get("/guild/{guild_id}/dev", response_class=RedirectResponse)
@router.get("/guild/{guild_id}/dev/logs", response_class=RedirectResponse)
async def dev_console(request: Request, guild_id: int, log_type: str = "global", level_filter: str = "ALL"):
    return RedirectResponse(url=f"/guild/{guild_id}/logs?log_type={log_type}&level_filter={level_filter}")
