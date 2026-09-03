import csv
import io
import logging
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from bot.repositories.transaction_repository import TransactionRepository
from bot.services.balance_notification_service import send_balance_transaction_dm
from bot.utils.fuzzy_search import fuzzy_match_member
from bot.web.audit import log_db_action
from bot.web.auth import get_user_guild_permissions, require_auth
from bot.web.routes.dashboard import ensure_valid_guild, get_available_guilds

logger = logging.getLogger("eradicateur_bot.web.balances")
router = APIRouter(dependencies=[Depends(require_auth)], tags=["Balances"])


async def _resolve_member_name(bot, guild_id: int, discord_id: int) -> str:
    if discord_id == 0:
        return "Web Dashboard Admin"
    if hasattr(bot, "get_guild"):
        guild = bot.get_guild(guild_id)
        if guild:
            member = guild.get_member(discord_id)
            if member:
                return f"{member.display_name} (@{member.name})"
            try:
                user = await bot.fetch_user(discord_id)
                if user:
                    return f"{user.display_name} (@{user.name})"
            except Exception:
                pass
    return f"User {discord_id}"


async def _resolve_creator_name(bot, guild_id: int, created_by: int) -> str:
    if created_by == 0:
        return "😎 DEV 😎"
    return await _resolve_member_name(bot, guild_id, created_by)


async def get_cataloged_guild_members(bot, guild_id: int, conn) -> list[dict]:
    """
    Catalogues all members of the Discord guild (excluding bots),
    merging their profile with current database balances.
    - Active server members are tagged with in_guild=True.
    - Departed members (not in discord guild) with a non-zero balance are tagged with in_guild=False.
    - Departed members with 0 balance are excluded completely.
    """
    tx_repo = TransactionRepository(conn)
    raw_balances = await tx_repo.list_balances(include_zero=True)
    db_balances = {row[0]: row[1] for row in raw_balances}

    catalog: dict[int, dict] = {}

    guild = bot.get_guild(guild_id) if hasattr(bot, "get_guild") else None
    if guild:
        members = list(guild.members)
        if len(members) <= 1 and hasattr(guild, "fetch_members"):
            try:
                members = [m async for m in guild.fetch_members(limit=None)]
            except Exception:
                members = list(guild.members)

        for m in members:
            if getattr(m, "bot", False):
                continue
            bal = db_balances.get(m.id, 0)
            display_name = m.display_name
            username = getattr(m, "name", str(m.id))
            full_name = f"{display_name} (@{username})" if username and username != display_name else display_name
            catalog[m.id] = {
                "discord_id": str(m.id),
                "name": full_name,
                "display_name": display_name,
                "balance": bal,
                "in_guild": True,
            }

        # Add departed members who still have a non-zero balance in DB
        for discord_id, bal in db_balances.items():
            if discord_id not in catalog and bal != 0:
                name = await _resolve_member_name(bot, guild_id, discord_id)
                catalog[discord_id] = {
                    "discord_id": str(discord_id),
                    "name": name,
                    "display_name": name,
                    "balance": bal,
                    "in_guild": False,
                }
    else:
        # Fallback when guild object is unavailable (e.g. tests / bot offline)
        for discord_id, bal in db_balances.items():
            name = await _resolve_member_name(bot, guild_id, discord_id)
            catalog[discord_id] = {
                "discord_id": str(discord_id),
                "name": name,
                "display_name": name,
                "balance": bal,
                "in_guild": True,
            }

    return sorted(catalog.values(), key=lambda x: x["name"].lower())


@router.get("/balances")
@router.get("/balance")
async def balances_root_redirect(request: Request):
    bot = request.app.state.bot
    guilds = get_available_guilds(bot)
    if guilds:
        return RedirectResponse(url=f"/guild/{guilds[0]['id']}/balances")
    return RedirectResponse(url="/")


@router.get("/guild/{guild_id}/balances", response_class=HTMLResponse)
async def list_balances(
    request: Request,
    guild_id: int,
    q: str = "",
    filter_type: str = "all",
):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = ensure_valid_guild(bot, guild_id)

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    total_owed = await tx_repo.get_total_owed()

    all_enriched = await get_cataloged_guild_members(bot, guild_id, conn)
    q_lower = q.lower().strip()

    # Stats for filter tabs (Tous, Actifs, Soldes à 0, Partis avec solde)
    stats = {
        "all": len(all_enriched),
        "nonzero": sum(1 for b in all_enriched if b["balance"] != 0),
        "zero": sum(1 for b in all_enriched if b["balance"] == 0 and b.get("in_guild", True)),
        "left": sum(1 for b in all_enriched if not b.get("in_guild", True) and b["balance"] != 0),
    }

    # Filter by query string and filter_type
    filtered_balances = []
    for b in all_enriched:
        if q:
            if not fuzzy_match_member(q, b["name"], b["discord_id"]):
                continue

        # Apply balance type filter
        if filter_type == "nonzero" and b["balance"] == 0:
            continue
        elif filter_type == "zero" and (b["balance"] != 0 or not b.get("in_guild", True)):
            continue
        elif filter_type == "left" and (b.get("in_guild", True) or b["balance"] == 0):
            continue

        filtered_balances.append(b)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    # Return partial for HTMX search / filter
    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        return templates.TemplateResponse(
            request=request,
            name="partials/balances_table.html",
            context={
                "balances": filtered_balances,
                "current_guild": current_guild,
                "total_owed": total_owed,
                "query": q,
                "filter_type": filter_type,
                "stats": stats,
                "user_perms": user_perms,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="balances.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "balances": filtered_balances,
            "all_members": all_enriched,
            "total_owed": total_owed,
            "query": q,
            "filter_type": filter_type,
            "stats": stats,
            "user_perms": user_perms,
            "message": None,
            "error": None,
        },
    )


@router.get("/guild/{guild_id}/balances/{discord_id}/history", response_class=HTMLResponse)
async def member_history(request: Request, guild_id: int, discord_id: int):
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

    transactions = await tx_repo.list_transactions(discord_id)
    current_balance = await tx_repo.get_balance(discord_id)
    member_name = await _resolve_member_name(bot, guild_id, discord_id)

    enriched_transactions = []
    for tx in transactions:
        creator_name = await _resolve_creator_name(bot, guild_id, tx.created_by)
        enriched_transactions.append({
            "id": tx.id,
            "discord_id": tx.discord_id,
            "amount": tx.amount,
            "reason": tx.reason,
            "payout_id": tx.payout_id,
            "created_by": tx.created_by,
            "creator_name": creator_name,
            "created_at": tx.created_at,
        })

    stats = {
        "total_count": len(enriched_transactions),
        "total_credits": sum(tx["amount"] for tx in enriched_transactions if tx["amount"] > 0),
        "total_debits": sum(tx["amount"] for tx in enriched_transactions if tx["amount"] < 0),
    }

    return templates.TemplateResponse(
        request=request,
        name="member_history.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "discord_id": discord_id,
            "member_name": member_name,
            "current_balance": current_balance,
            "transactions": enriched_transactions,
            "stats": stats,
            "user_perms": user_perms,
        },
    )


@router.post("/guild/{guild_id}/balances/transaction")
async def add_manual_transaction(
    request: Request,
    guild_id: int,
    discord_id: int = Form(...),
    operation: str = Form(...),  # "credit" or "debit"
    amount: int = Form(...),
    reason: str = Form(""),
    return_to: str | None = Form(None),
):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    if not user_perms["can_manage_balances"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to execute manual transactions on balances.",
        )

    if operation not in ("credit", "debit"):
        raise HTTPException(status_code=400, detail="Invalid operation type. Must be 'credit' or 'debit'.")

    if amount <= 0 or amount > 100_000_000_000:
        raise HTTPException(status_code=400, detail="Amount must be between 1 and 100 000 000 000 silvers")

    if discord_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid Discord User ID")

    stripped_reason = reason.strip()[:255]
    if operation == "debit":
        sanitized_reason = stripped_reason if stripped_reason else "Manual withdrawal"
    else:
        if not stripped_reason:
            raise HTTPException(status_code=400, detail="Reason is required for credit transactions")
        sanitized_reason = stripped_reason

    cleaned_reason = f"[Dash] {sanitized_reason}"

    final_amount = amount if operation == "credit" else -amount

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)

    current_user = getattr(request.state, "user", None) or {}
    actor_id = int(current_user.get("id", 0))
    is_dev_mode = (sim_role == "dev") or (actor_id == 0 and sim_role not in ("leader", "officer"))
    recorded_created_by = 0 if is_dev_mode else actor_id
    actor_name = "😎 DEV 😎" if is_dev_mode else current_user.get("display_name", "Dashboard Admin")

    # Record transaction with created_by = 0 for DEV mode, or user ID for Leader/Officer
    await tx_repo.add_transaction(
        discord_id=discord_id,
        amount=final_amount,
        reason=cleaned_reason,
        created_by=recorded_created_by,
    )

    new_balance = await tx_repo.get_balance(discord_id)

    # Attempt to send Discord DM notification to the user
    if hasattr(bot, "get_guild"):
        guild = bot.get_guild(guild_id)
        if guild:
            try:
                await send_balance_transaction_dm(
                    bot=bot,
                    guild=guild,
                    target_user_id=discord_id,
                    amount=amount,
                    is_credit=(operation == "credit"),
                    new_balance=new_balance,
                    reason=sanitized_reason if operation == "credit" else None,
                    actor_id=None if is_dev_mode else (actor_id if actor_id > 0 else None),
                    actor_name=actor_name,
                )
            except Exception:
                logger.exception(
                    "Failed to send balance transaction DM for user %s in guild %s",
                    discord_id,
                    guild_id,
                )

    log_db_action(
        request,
        guild_id,
        f"BALANCE_{operation.upper()}",
        f"Target User ID: {discord_id} | Amount: {final_amount:+d} silvers | Reason: {sanitized_reason}",
    )

    redirect_url = return_to if (return_to and return_to.startswith(f"/guild/{guild_id}")) else f"/guild/{guild_id}/balances/{discord_id}/history"

    return RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/guild/{guild_id}/balances/export.csv")
async def export_balances_csv(request: Request, guild_id: int):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    rows = await tx_repo.list_balances(include_zero=False)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["Discord ID", "Pseudo", "Solde (Silvers)"])

    for discord_id, balance in rows:
        name = await _resolve_member_name(bot, guild_id, discord_id)
        writer.writerow([discord_id, name, balance])

    csv_content = output.getvalue()
    filename = f"balances_{guild_id}_{int(time.time())}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.get("/guild/{guild_id}/balances/{discord_id}/history/export.csv")
async def export_member_history_csv(request: Request, guild_id: int, discord_id: int):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    txs = await tx_repo.list_transactions(discord_id)

    player_name = await _resolve_member_name(bot, guild_id, discord_id)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["ID Transaction", "Date & Heure", "Joueur ID", "Joueur Nom", "Type / Ref", "Montant (Silvers)", "Motif / Raison", "Auteur"])

    for tx in txs:
        tx_type = f"Payout #{tx.payout_id}" if tx.payout_id else ("Credit" if tx.amount > 0 else "Debit")
        author = "😎 DEV 😎" if tx.created_by == 0 else await _resolve_creator_name(bot, guild_id, tx.created_by)
        writer.writerow([
            tx.id,
            tx.created_at,
            discord_id,
            player_name,
            tx_type,
            tx.amount,
            tx.reason or "",
            author,
        ])

    csv_content = output.getvalue()
    filename = f"history_{discord_id}_{int(time.time())}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


