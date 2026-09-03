import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.activity_pool_repository import ActivityPoolRepository
from bot.web.audit import log_db_action
from bot.web.auth import get_user_guild_permissions, require_auth
from bot.web.routes.dashboard import ensure_valid_guild, get_available_guilds

logger = logging.getLogger("eradicateur_bot.web.activity_pool")
router = APIRouter(dependencies=[Depends(require_auth)], tags=["Activity Pool"])


@router.get("/activity-pool")
@router.get("/pool")
async def activity_pool_root_redirect(request: Request):
    bot = request.app.state.bot
    guilds = get_available_guilds(bot)
    if guilds:
        return RedirectResponse(url=f"/guild/{guilds[0]['id']}/activity-pool")
    return RedirectResponse(url="/")


@router.get("/guild/{guild_id}/activity-pool", response_class=HTMLResponse)
async def view_activity_pool(request: Request, guild_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

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
            "user_perms": user_perms,
        },
    )


@router.post("/guild/{guild_id}/activity-pool/add")
async def add_role_to_pool(request: Request, guild_id: int, label: str = Form(...)):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)
    if not user_perms["can_manage_activity_pool"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Leader role required to modify activity pool.",
        )

    cleaned_label = label.strip()[:100]
    if not cleaned_label:
        raise HTTPException(status_code=400, detail="Role label cannot be empty")

    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)
    await pool_repo.add_label(guild_id, cleaned_label)

    log_db_action(
        request,
        guild_id,
        "ACTIVITY_POOL_ADD",
        f"Added role label: '{cleaned_label}'",
    )

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/activity-pool/remove/{position}")
async def remove_role_from_pool(request: Request, guild_id: int, position: int):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)
    if not user_perms["can_manage_activity_pool"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Leader role required to modify activity pool.",
        )

    if position <= 0:
        raise HTTPException(status_code=400, detail="Invalid position")

    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)
    await pool_repo.remove_position(guild_id, position)

    log_db_action(
        request,
        guild_id,
        "ACTIVITY_POOL_REMOVE",
        f"Removed role at position #{position}",
    )

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/activity-pool/reorder")
async def reorder_activity_pool(
    request: Request,
    guild_id: int,
):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)
    if not user_perms["can_manage_activity_pool"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Leader role required to modify activity pool.",
        )

    # Parse labels list from JSON body or Form data
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            data = await request.json()
            labels = data.get("labels", [])
        else:
            form = await request.form()
            labels = form.getlist("labels")
    except Exception:
        labels = []

    cleaned_labels = [str(l).strip()[:100] for l in labels if str(l).strip()]
    if not cleaned_labels:
        raise HTTPException(status_code=400, detail="No labels provided for reordering")

    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)
    await pool_repo.set_order(guild_id, cleaned_labels)

    log_db_action(
        request,
        guild_id,
        "ACTIVITY_POOL_REORDER",
        f"Reordered activity pool ({len(cleaned_labels)} roles via drag-and-drop)",
    )

    if "application/json" in request.headers.get("content-type", "") or request.headers.get("HX-Request"):
        return {"success": True, "labels": cleaned_labels}

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
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)
    if not user_perms["can_manage_activity_pool"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Leader role required to modify activity pool.",
        )

    if direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Invalid direction: must be 'up' or 'down'")

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

    log_db_action(
        request,
        guild_id,
        "ACTIVITY_POOL_REORDER",
        f"Moved role at position #{position} ({direction})",
    )

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/activity-pool/edit/{position}")
async def edit_role_in_pool(
    request: Request,
    guild_id: int,
    position: int,
    label: str = Form(...),
):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)
    if not user_perms["can_manage_activity_pool"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Leader role required to modify activity pool.",
        )

    cleaned_label = label.strip()[:100]
    if not cleaned_label:
        raise HTTPException(status_code=400, detail="Role label cannot be empty")

    if position <= 0:
        raise HTTPException(status_code=400, detail="Invalid position")

    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)
    success = await pool_repo.update_label(guild_id, position, cleaned_label)

    if not success:
        raise HTTPException(status_code=404, detail="Role not found at specified position")

    log_db_action(
        request,
        guild_id,
        "ACTIVITY_POOL_EDIT",
        f"Renamed role at position #{position} to: '{cleaned_label}'",
    )

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/guild/{guild_id}/activity-pool/clear")
async def clear_activity_pool(request: Request, guild_id: int):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)
    if not user_perms["can_manage_activity_pool"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Leader role required to modify activity pool.",
        )

    conn = await bot.db_manager.get_connection(guild_id)
    pool_repo = ActivityPoolRepository(conn)
    await pool_repo.clear(guild_id)

    log_db_action(
        request,
        guild_id,
        "ACTIVITY_POOL_CLEAR",
        "Cleared all roles in activity pool",
    )

    return RedirectResponse(
        url=f"/guild/{guild_id}/activity-pool",
        status_code=status.HTTP_303_SEE_OTHER,
    )


