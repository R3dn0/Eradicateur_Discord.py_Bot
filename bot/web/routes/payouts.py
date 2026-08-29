from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.payout_repository import PayoutRepository
from bot.repositories.transaction_repository import TransactionRepository
from bot.web.auth import require_auth
from bot.web.routes.balances import _resolve_member_name
from bot.web.routes.dashboard import get_available_guilds

router = APIRouter(dependencies=[Depends(require_auth)], tags=["Payouts"])


@router.get("/guild/{guild_id}/payouts", response_class=HTMLResponse)
async def list_payouts(request: Request, guild_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = next((g for g in guilds if g["id"] == guild_id), {"id": guild_id, "name": f"Guild #{guild_id}"})

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    payout_repo = PayoutRepository(conn, tx_repo)

    cursor = await conn.execute("SELECT * FROM payouts ORDER BY id DESC")
    rows = await cursor.fetchall()

    payouts = []
    for row in rows:
        creator_name = await _resolve_member_name(bot, guild_id, row["created_by"]) if row["created_by"] else "Admin"
        payouts.append({
            "id": row["id"],
            "bag_silvers": row["bag_silvers"],
            "item_market_value": row["item_market_value"],
            "activity_cost": row["activity_cost"],
            "participant_count": row["participant_count"],
            "amount_per_player": row["amount_per_player"],
            "buyback_value": row["buyback_value"],
            "created_by": row["created_by"],
            "creator_name": creator_name,
            "created_at": row["created_at"],
            "voided": bool(row["voided"]),
            "voided_by": row["voided_by"],
            "voided_at": row["voided_at"],
        })

    return templates.TemplateResponse(
        request=request,
        name="payouts.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "payouts": payouts,
        },
    )


@router.get("/guild/{guild_id}/payouts/{payout_id}", response_class=HTMLResponse)
async def payout_detail(request: Request, guild_id: int, payout_id: int):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = next((g for g in guilds if g["id"] == guild_id), {"id": guild_id, "name": f"Guild #{guild_id}"})

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    payout_repo = PayoutRepository(conn, tx_repo)

    payout = await payout_repo.get_payout(payout_id)
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found")

    transactions = await tx_repo.list_transactions_for_payout(payout_id)
    creator_name = await _resolve_member_name(bot, guild_id, payout.created_by) if payout.created_by else "Admin"

    participants = []
    for tx in transactions:
        member_name = await _resolve_member_name(bot, guild_id, tx.discord_id)
        participants.append({
            "discord_id": tx.discord_id,
            "name": member_name,
            "amount": tx.amount,
        })

    return templates.TemplateResponse(
        request=request,
        name="payout_detail.html",
        context={
            "bot": bot,
            "guilds": guilds,
            "current_guild": current_guild,
            "payout": payout,
            "creator_name": creator_name,
            "participants": participants,
        },
    )


@router.post("/guild/{guild_id}/payouts/{payout_id}/void")
async def void_payout_action(request: Request, guild_id: int, payout_id: int):
    bot = request.app.state.bot
    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)
    payout_repo = PayoutRepository(conn, tx_repo)

    try:
        # Voided by 0 (Dashboard Admin)
        await payout_repo.void_payout(payout_id=payout_id, voided_by=0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(
        url=f"/guild/{guild_id}/payouts/{payout_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )

