from pathlib import Path
import math
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.repositories.transaction_repository import TransactionRepository
from bot.web.auth import get_user_guild_permissions, require_auth
from bot.web.routes.balances import _resolve_members_bulk
from bot.web.routes.dashboard import ensure_valid_guild, get_available_guilds
from bot.utils.fuzzy_search import fuzzy_match_member

router = APIRouter(dependencies=[Depends(require_auth)], tags=["Transactions"])


@router.get("/transactions")
@router.get("/transaction")
async def transactions_root_redirect(request: Request):
    bot = request.app.state.bot
    guilds = get_available_guilds(bot)
    if guilds:
        return RedirectResponse(url=f"/guild/{guilds[0]['id']}/transactions")
    return RedirectResponse(url="/")


@router.get("/guild/{guild_id}/transactions", response_class=HTMLResponse)
async def list_transactions(
    request: Request,
    guild_id: int,
    q: str = Query("", alias="q"),
    filter_type: str = Query("all", alias="filter"),
    page: int = Query(1, ge=1),
):
    bot = request.app.state.bot
    templates = request.app.state.templates
    guilds = get_available_guilds(bot)
    current_guild = ensure_valid_guild(bot, guild_id)

    conn = await bot.db_manager.get_connection(guild_id)
    tx_repo = TransactionRepository(conn)

    # Fetch stats and guild debt
    stats = await tx_repo.get_transaction_stats()
    total_owed = await tx_repo.get_total_owed()

    page_size = 40
    search_query = q.strip()

    if not search_query:
        # Fast path: database-level pagination
        total_items = await tx_repo.count_transactions(filter_type=filter_type)
        total_pages = max(1, math.ceil(total_items / page_size))
        current_page = min(page, total_pages)
        start_idx = (current_page - 1) * page_size

        raw_txs = await tx_repo.list_all_transactions(
            limit=page_size,
            offset=start_idx,
            filter_type=filter_type,
        )

        player_ids = {tx.discord_id for tx in raw_txs}
        creator_ids = {tx.created_by for tx in raw_txs}

        resolved_players = await _resolve_members_bulk(bot, guild_id, player_ids, is_creator=False)
        resolved_creators = await _resolve_members_bulk(bot, guild_id, creator_ids, is_creator=True)

        paginated_txs = []
        for tx in raw_txs:
            player_name = resolved_players.get(tx.discord_id, f"User {tx.discord_id}")
            creator_name = resolved_creators.get(tx.created_by, f"User {tx.created_by}")
            tx_kind = "payout" if tx.payout_id else ("credit" if tx.amount > 0 else "debit")
            paginated_txs.append({
                "id": tx.id,
                "discord_id": tx.discord_id,
                "player_name": player_name,
                "amount": tx.amount,
                "reason": tx.reason,
                "payout_id": tx.payout_id,
                "created_by": tx.created_by,
                "creator_name": creator_name,
                "created_at": tx.created_at,
                "kind": tx_kind,
            })
    else:
        # Search path: fetch filtered transactions, bulk resolve unique users, then fuzzy filter
        raw_txs = await tx_repo.list_all_transactions(limit=None, filter_type=filter_type)

        player_ids = {tx.discord_id for tx in raw_txs}
        creator_ids = {tx.created_by for tx in raw_txs}

        resolved_players = await _resolve_members_bulk(bot, guild_id, player_ids, is_creator=False)
        resolved_creators = await _resolve_members_bulk(bot, guild_id, creator_ids, is_creator=True)

        enriched_txs = []
        for tx in raw_txs:
            player_name = resolved_players.get(tx.discord_id, f"User {tx.discord_id}")
            if not fuzzy_match_member(search_query, player_name, tx.discord_id):
                continue
            creator_name = resolved_creators.get(tx.created_by, f"User {tx.created_by}")
            tx_kind = "payout" if tx.payout_id else ("credit" if tx.amount > 0 else "debit")
            enriched_txs.append({
                "id": tx.id,
                "discord_id": tx.discord_id,
                "player_name": player_name,
                "amount": tx.amount,
                "reason": tx.reason,
                "payout_id": tx.payout_id,
                "created_by": tx.created_by,
                "creator_name": creator_name,
                "created_at": tx.created_at,
                "kind": tx_kind,
            })

        total_items = len(enriched_txs)
        total_pages = max(1, math.ceil(total_items / page_size))
        current_page = min(page, total_pages)
        start_idx = (current_page - 1) * page_size
        paginated_txs = enriched_txs[start_idx : start_idx + page_size]

    user = getattr(request.state, "user", None) or {}
    user_id = int(user.get("id", 0))
    sim_role = request.cookies.get("dev_simulated_role", "dev")
    user_perms = await get_user_guild_permissions(bot, guild_id, user_id, simulated_role=sim_role)

    ctx = {
        "bot": bot,
        "guilds": guilds,
        "current_guild": current_guild,
        "transactions": paginated_txs,
        "total_items": total_items,
        "total_pages": total_pages,
        "current_page": current_page,
        "page_size": page_size,
        "stats": stats,
        "total_owed": total_owed,
        "query": q,
        "filter_type": filter_type,
        "user_perms": user_perms,
    }

    # Return partial for HTMX search / filter
    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        return templates.TemplateResponse(
            request=request,
            name="partials/transactions_table.html",
            context=ctx,
        )

    return templates.TemplateResponse(
        request=request,
        name="transactions.html",
        context=ctx,
    )
