from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.web.auth import require_auth
from bot.web.routes.dashboard import ensure_valid_guild, get_available_guilds

router = APIRouter(dependencies=[Depends(require_auth)], tags=["Logs"])


@router.get("/logs")
@router.get("/log")
async def logs_root_redirect(request: Request):
    bot = request.app.state.bot
    guilds = get_available_guilds(bot)
    if guilds:
        return RedirectResponse(url=f"/guild/{guilds[0]['id']}/logs")
    return RedirectResponse(url="/")


def read_log_lines(
    logs_dir: Path,
    base_filename: str,
    level_filter: str = "ALL",
    limit: int = 500,
) -> list[str]:
    """Read log lines from base_filename and its rotated backups in order until limit is reached."""
    candidates = [logs_dir / base_filename]
    for i in range(1, 11):
        candidates.append(logs_dir / f"{base_filename}.{i}")

    collected_lines: list[str] = []
    found_any_file = False

    for target_path in candidates:
        if not target_path.exists():
            continue
        found_any_file = True
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    clean_line = line.rstrip("\r\n")
                    if not clean_line:
                        continue
                    if level_filter != "ALL":
                        if f"[{level_filter}]" not in clean_line and f" {level_filter} " not in clean_line:
                            continue
                    collected_lines.append(clean_line)
                    if len(collected_lines) >= limit:
                        return collected_lines
        except Exception as e:
            collected_lines.append(f"Error reading {target_path.name}: {e}")
            break

    if not found_any_file:
        return [f"No log file found ({base_filename})"]
    return collected_lines


@router.get("/guild/{guild_id}/logs", response_class=HTMLResponse)
async def view_logs(request: Request, guild_id: int, log_type: str = "guild", level_filter: str = "ALL"):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = ensure_valid_guild(bot, guild_id)

    logs_dir = Path(bot.config.data_dir) / "logs"

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    from bot.web.auth import get_user_guild_permissions, is_dev_user

    user_is_dev = is_dev_user(bot, user_id)
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    if not user_is_dev and log_type != "guild":
        log_type = "guild"

    if log_type == "errors" and user_is_dev:
        base_name = "errors.log"
    elif log_type == "global" and user_is_dev:
        base_name = "bot.log"
    else:
        log_type = "guild"
        base_name = f"guild_{guild_id}.log"

    log_lines = read_log_lines(logs_dir, base_name, level_filter=level_filter, limit=500)

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
            "is_dev": user_is_dev,
            "user_perms": user_perms,
        },
    )


@router.get("/guild/{guild_id}/logs/stream", response_class=HTMLResponse)
async def stream_logs(request: Request, guild_id: int, log_type: str = "guild", level_filter: str = "ALL"):
    bot = request.app.state.bot
    templates = request.app.state.templates
    ensure_valid_guild(bot, guild_id)

    logs_dir = Path(bot.config.data_dir) / "logs"

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    from bot.web.auth import is_dev_user

    user_is_dev = is_dev_user(bot, user_id)

    if not user_is_dev and log_type != "guild":
        log_type = "guild"

    if log_type == "errors" and user_is_dev:
        base_name = "errors.log"
    elif log_type == "global" and user_is_dev:
        base_name = "bot.log"
    else:
        base_name = f"guild_{guild_id}.log"

    log_lines = read_log_lines(logs_dir, base_name, level_filter=level_filter, limit=500)

    return templates.TemplateResponse(
        request=request,
        name="partials/log_lines.html",
        context={"log_lines": log_lines},
    )


