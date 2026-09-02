from unittest.mock import AsyncMock, MagicMock
import aiosqlite
import discord
import pytest

from bot.services.balance_notification_service import send_balance_transaction_dm


@pytest.fixture
async def db():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def mock_bot(db):
    bot = MagicMock()
    bot.db_manager = MagicMock()
    bot.db_manager.get_connection = AsyncMock(return_value=db)

    translations = {
        "balance_dm_add_title": "Crédit reçu",
        "balance_dm_pay_title": "Paiement effectué",
        "balance_dm_amount_credited": "Montant crédité",
        "balance_dm_amount_debited": "Montant débité",
        "balance_dm_new_balance": "Nouveau solde",
        "balance_dm_reason": "Raison",
        "balance_dm_performed_by": "Effectué par",
    }
    bot.translate = AsyncMock(side_effect=lambda key, loc=None: translations.get(key, key))
    return bot


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 12345

    member = MagicMock(spec=discord.Member)
    member.id = 999
    member.bot = False
    member.send = AsyncMock()
    member.get_role = MagicMock(return_value=None)

    guild.get_member = MagicMock(return_value=member)
    guild.fetch_member = AsyncMock(return_value=member)
    return guild, member


@pytest.mark.asyncio
async def test_send_balance_credit_dm(mock_bot, mock_guild, db):
    guild, member = mock_guild

    result = await send_balance_transaction_dm(
        bot=mock_bot,
        guild=guild,
        target_user_id=999,
        amount=50000,
        is_credit=True,
        new_balance=150000,
        reason="[Dash] Bonus Activité",
        actor_id=135489084385787905,
    )

    assert result.sent == [999]
    member.send.assert_awaited_once()
    args = member.send.call_args
    embed: discord.Embed = args[1]["embed"]

    assert embed.title == "Crédit reçu"
    assert embed.color == discord.Color.green()

    # Field 0: Montant crédité (inline)
    assert embed.fields[0].name == "Montant crédité"
    assert embed.fields[0].value == "50,000"
    assert embed.fields[0].inline is True

    # Field 1: Nouveau solde (inline)
    assert embed.fields[1].name == "Nouveau solde"
    assert embed.fields[1].value == "150,000"
    assert embed.fields[1].inline is True

    # Field 2: Raison (not inline, [Dash] prefix stripped)
    assert embed.fields[2].name == "Raison"
    assert embed.fields[2].value == "Bonus Activité"
    assert embed.fields[2].inline is False

    # Field 3: Effectué par (single line with mention)
    assert embed.fields[3].value == "**Effectué par :** <@135489084385787905>"
    assert embed.fields[3].inline is False


@pytest.mark.asyncio
async def test_send_balance_debit_dm(mock_bot, mock_guild, db):
    guild, member = mock_guild

    result = await send_balance_transaction_dm(
        bot=mock_bot,
        guild=guild,
        target_user_id=999,
        amount=25000,
        is_credit=False,
        new_balance=75000,
        reason=None,
        actor_name="R3dn0",
    )

    assert result.sent == [999]
    member.send.assert_awaited_once()
    args = member.send.call_args
    embed: discord.Embed = args[1]["embed"]

    assert embed.title == "Paiement effectué"
    assert embed.color == discord.Color.red()

    assert embed.fields[0].name == "Montant débité"
    assert embed.fields[0].value == "25,000"
    assert embed.fields[0].inline is True

    assert embed.fields[1].name == "Nouveau solde"
    assert embed.fields[1].value == "75,000"
    assert embed.fields[1].inline is True

    # Reason not present, so field 2 is Effectué par (single line)
    assert embed.fields[2].value == "**Effectué par :** R3dn0"
    assert embed.fields[2].inline is False
