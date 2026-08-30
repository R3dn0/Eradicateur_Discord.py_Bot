import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.transaction_repository import TransactionRepository
from bot.web.auth import require_auth
from bot.web.routes.dashboard import ensure_valid_guild, get_available_guilds

logger = logging.getLogger("eradicateur_bot.web.balances")
router = APIRouter(dependencies=[Depends(require_auth)], tags=["Balances"])


async def _resolve_member_name(bot, guild_id: int, discord_id: int) -> str:
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

    # Fetch all balances from database including zero balances
    raw_balances = await tx_repo.list_balances(include_zero=True)
    total_owed = await tx_repo.get_total_owed()

    # Track seen discord IDs
    seen_ids = set()
    all_enriched = []
    q_lower = q.lower().strip()

    # 1. Process all database balances
    for discord_id, balance in raw_balances:
        seen_ids.add(discord_id)
        name = await _resolve_member_name(bot, guild_id, discord_id)
        all_enriched.append({
            "discord_id": discord_id,
            "name": name or f"User {discord_id}",
            "balance": balance,
        })

    # 2. If searching, also search Discord guild members not in transactions (balance 0)
    if q_lower and hasattr(bot, "get_guild"):
        try:
            guild = bot.get_guild(guild_id)
            if guild and hasattr(guild, "members") and guild.members:
                for m in guild.members:
                    if m.id not in seen_ids:
                        display_name = f"{getattr(m, 'display_name', str(m.id))} (@{getattr(m, 'name', str(m.id))})"
                        if q_lower in display_name.lower() or q_lower in str(m.id):
                            seen_ids.add(m.id)
                            all_enriched.append({
                                "discord_id": m.id,
                                "name": display_name,
                                "balance": 0,
                            })
        except Exception:
            logger.exception("Error searching Discord guild members for guild %s", guild_id)

    # Stats for filter tabs (Tous, Actifs, Soldes à 0)
    stats = {
        "all": len(all_enriched),
        "nonzero": sum(1 for b in all_enriched if b["balance"] != 0),
        "zero": sum(1 for b in all_enriched if b["balance"] == 0),
    }

    # Filter by query string
    filtered_balances = []
    for b in all_enriched:
        if q_lower:
            if q_lower not in b["name"].lower() and q_lower not in str(b["discord_id"]):
                continue

        # Apply balance type filter
        if filter_type == "nonzero" and b["balance"] == 0:
            continue
        elif filter_type == "zero" and b["balance"] != 0:
            continue

        filtered_balances.append(b)

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
            "total_owed": total_owed,
            "query": q,
            "filter_type": filter_type,
            "stats": stats,
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

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)

    transactions = await tx_repo.list_transactions(discord_id)
    current_balance = await tx_repo.get_balance(discord_id)
    member_name = await _resolve_member_name(bot, guild_id, discord_id)

    enriched_transactions = []
    for tx in transactions:
        creator_name = await _resolve_member_name(bot, guild_id, tx.created_by)
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
        },
    )


@router.post("/guild/{guild_id}/balances/transaction")
async def add_manual_transaction(
    request: Request,
    guild_id: int,
    discord_id: int = Form(...),
    operation: str = Form(...),  # "credit" or "debit"
    amount: int = Form(...),
    reason: str = Form(...),
):
    bot = request.app.state.bot
    ensure_valid_guild(bot, guild_id)

    if operation not in ("credit", "debit"):
        raise HTTPException(status_code=400, detail="Invalid operation type. Must be 'credit' or 'debit'.")

    if amount <= 0 or amount > 100_000_000_000:
        raise HTTPException(status_code=400, detail="Amount must be between 1 and 100 000 000 000 silvers")

    if discord_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid Discord User ID")

    sanitized_reason = reason.strip()[:255]
    if not sanitized_reason:
        sanitized_reason = "Manual adjustment"
    cleaned_reason = f"[Web Dashboard] {sanitized_reason}"

    final_amount = amount if operation == "credit" else -amount

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)

    current_user = getattr(request.state, "user", None) or {}
    actor_id = int(current_user.get("id", 0))
    actor_name = current_user.get("display_name", "Dashboard Admin")

    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        "User %s (ID: %s, IP: %s) performed manual %s of %s silvers for user %s (Guild %s, Reason: %s)",
        actor_name,
        actor_id,
        client_ip,
        operation,
        amount,
        discord_id,
        guild_id,
        sanitized_reason,
    )

    # Record transaction with created_by = logged-in Discord user ID
    await tx_repo.add_transaction(
        discord_id=discord_id,
        amount=final_amount,
        reason=cleaned_reason,
        created_by=actor_id,
    )

    return RedirectResponse(
        url=f"/guild/{guild_id}/balances/{discord_id}/history",
        status_code=status.HTTP_303_SEE_OTHER,
    )


