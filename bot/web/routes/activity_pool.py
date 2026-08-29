from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.activity_pool_repository import ActivityPoolRepository
from bot.web.auth import require_auth
from bot.web.routes.dashboard import get_available_guilds

router = APIRouter(dependencies=[Depends(require_auth)], tags=["Activity Pool"])


@router.get("/guild/{guild_id}/activity-pool", response_class=HTMLResponse)
async def view_activity_pool(request: Request, guild_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = next((g for g in guilds if g["id"] == guild_id), {"id": guild_id, "name": f"Guild #{guild_id}"})

    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)

    labels = await pool_repo.get_labels(guild_id)
    pool_items = [{"position": idx + 1, "label": label} for idx, label in enumerate(labels)]

    return templates.TemplateResponse(
        request=request,
        name="activity_pool.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "pool_items": pool_items,
        },
    )


@router.post("/guild/{guild_id}/activity-pool/add")
async def add_role_to_pool(request: Request, guild_id: int, label: str = Form(...)):
    bot = request.app.state.bot
    if label.strip():
        conn = await bot.db_manager.get_connection(guild_id)
        pool_repo = ActivityPoolRepository(conn)
        await pool_repo.add_label(guild_id, label.strip())

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/activity-pool/remove/{position}")
async def remove_role_from_pool(request: Request, guild_id: int, position: int):
    bot = request.app.state.bot
    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)
    await pool_repo.remove_position(guild_id, position)

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/activity-pool/move")
async def move_role_position(
    request: Request,
    guild_id: int,
    position: int = Form(...),
    direction: str = Form(...),  # "up" or "down"
):
    bot = request.app.state.bot
    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)

    labels = await pool_repo.get_labels(guild_id)
    idx = position - 1
    if 0 <= idx < len(labels):
        if direction == "up" and idx > 0:
            labels[idx], labels[idx - 1] = labels[idx - 1], labels[idx]
            await pool_repo.set_order(guild_id, labels)
        elif direction == "down" and idx < len(labels) - 1:
            labels[idx], labels[idx + 1] = labels[idx + 1], labels[idx]
            await pool_repo.set_order(guild_id, labels)

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/activity-pool/clear")
async def clear_activity_pool(request: Request, guild_id: int):
    bot = request.app.state.bot
    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)
    await pool_repo.clear(guild_id)

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )

