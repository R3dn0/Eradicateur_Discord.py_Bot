from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from bot.web.auth import require_auth
from bot.web.routes.dashboard import get_available_guilds

router = APIRouter(dependencies=[Depends(require_auth)], tags=["Logs"])


@router.get("/guild/{guild_id}/logs", response_class=HTMLResponse)
async def view_logs(request: Request, guild_id: int, log_type: str = "guild", level_filter: str = "ALL"):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = next((g for g in guilds if g["id"] == guild_id), {"id": guild_id, "name": f"Guild #{guild_id}"})

    logs_dir = Path(bot.config.data_dir) / "logs"

    if log_type == "errors":
        target_file = logs_dir / "errors.log"
    elif log_type == "global":
        target_file = logs_dir / "bot.log"
    else:
        target_file = logs_dir / f"guild_{guild_id}.log"

    log_lines = []
    if target_file.exists():
        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                # If level_filter != ALL, filter lines
                if level_filter != "ALL":
                    lines = [line for line in lines if f"[{level_filter}]" in line or f" {level_filter} " in line]
                log_lines = lines[:500]  # Limit to latest 500 lines
        except Exception as e:
            log_lines = [f"Error reading logs: {e}"]
    else:
        log_lines = [f"No log file found ({target_file.name})"]

    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "log_type": log_type,
            "level_filter": level_filter,
            "log_lines": log_lines,
        },
    )

