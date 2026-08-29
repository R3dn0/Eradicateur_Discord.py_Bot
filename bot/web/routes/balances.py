from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.transaction_repository import TransactionRepository
from bot.web.auth import require_auth
from bot.web.routes.dashboard import get_available_guilds

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


@router.get("/guild/{guild_id}/balances", response_class=HTMLResponse)
async def list_balances(request: Request, guild_id: int, q: str = ""):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = next((g for g in guilds if g["id"] == guild_id), {"id": guild_id, "name": f"Guild #{guild_id}"})

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)

    raw_balances = await tx_repo.list_balances()
    total_owed = await tx_repo.get_total_owed()

    # Enrich balances with discord names
    enriched_balances = []
    q_lower = q.lower().strip()
    for discord_id, balance in raw_balances:
        name = await _resolve_member_name(bot, guild_id, discord_id)
        if q_lower:
            if q_lower not in name.lower() and q_lower not in str(discord_id):
                continue
        enriched_balances.append({
            "discord_id": discord_id,
            "name": name,
            "balance": balance,
        })

    # Return partial for HTMX search
    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        return templates.TemplateResponse(
            request=request,
            name="partials/balances_table.html",
            context={
                "balances": enriched_balances,
                "current_guild": current_guild,
                "total_owed": total_owed,
                "query": q,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="balances.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "balances": enriched_balances,
            "total_owed": total_owed,
            "query": q,
            "message": None,
            "error": None,
        },
    )


@router.get("/guild/{guild_id}/balances/{discord_id}/history", response_class=HTMLResponse)
async def member_history(request: Request, guild_id: int, discord_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = next((g for g in guilds if g["id"] == guild_id), {"id": guild_id, "name": f"Guild #{guild_id}"})

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
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be strictly positive")

    final_amount = amount if operation == "credit" else -amount
    cleaned_reason = f"[Web Dashboard] {reason.strip()}"

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)

    # If debit, check balance
    if operation == "debit":
        current_bal = await tx_repo.get_balance(discord_id)
        if current_bal < amount:
            # We can allow overdraft if explicitly done from dashboard or warn, but let's allow with warning or standard check
            pass

    # Record transaction with created_by = 0 (Dashboard Admin)
    await tx_repo.add_transaction(
        discord_id=discord_id,
        amount=final_amount,
        reason=cleaned_reason,
        created_by=0,
    )

    return RedirectResponse(
        url=f"/guild/{guild_id}/balances/{discord_id}/history",
        status_code=status.HTTP_303_SEE_OTHER,
    )

