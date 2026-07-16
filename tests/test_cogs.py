import aiosqlite
import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.cogs.guild_commands import GuildCommands
from bot.cogs.payout.cog import PayoutCog
from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)
from bot.repositories.transaction_repository import (
    TransactionRepository,
)
from bot.cogs.payout.views import (
    ConfirmCancelView,
    ParticipantSelectView,
    RemoveParticipantsView,
)
from bot.services.payout_service import PayoutSplitResult

_OFFICER_ROLE_ID = 9999
_LEADER_ROLE_ID = 8888


@pytest.fixture
async def db():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        await conn.close()


class TestPingCommand:
    @pytest.fixture
    def cog(self):
        bot = MagicMock()
        bot.latency = 0.05
        return GuildCommands(bot)

    @pytest.mark.asyncio
    async def test_ping_responds(self, cog):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        await cog.ping.callback(cog, interaction)
        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "Pong" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True


class TestPayoutDeduplication:
    def test_deduplicates_across_batches(self):
        view = ParticipantSelectView(
            bag_silvers=1000000.0,
            item_market_value=5000000.0,
            activity_cost=500000.0,
            select_placeholder="test",
            finish_label="Terminer",
            cancel_label="Annuler",
            retirer_label="Retirer",
            retour_label="Retour",
            remove_prompt="Sélectionnez les participants à retirer :",
            remove_placeholder="Choisissez les participants à retirer",
        )
        view.accumulated.update({1, 2, 3})
        view.accumulated.update({3, 4, 5})
        assert len(view.accumulated) == 5
        assert view.accumulated == {1, 2, 3, 4, 5}

    def test_remove_flow_deduplicates_correctly(self):
        view = ParticipantSelectView(
            bag_silvers=1000000.0,
            item_market_value=5000000.0,
            activity_cost=500000.0,
            select_placeholder="test",
            finish_label="Terminer",
            cancel_label="Annuler",
            retirer_label="Retirer",
            retour_label="Retour",
            remove_prompt="Sélectionnez les participants à retirer :",
            remove_placeholder="Choisissez les participants à retirer",
        )
        view.accumulated.update({1, 2, 3})
        remove_view = RemoveParticipantsView(
            accumulated=view.accumulated,
            main_view=view,
            remove_placeholder="test",
            retour_label="Retour",
        )
        remove_view.accumulated.difference_update({2})
        assert len(view.accumulated) == 2
        assert view.accumulated == {1, 3}


class TestConfirmCancelViewDMNotifications:
    @pytest.fixture
    def view(self):
        return ConfirmCancelView(
            bag_silvers=1000000.0,
            item_market_value=5000000.0,
            activity_cost=500000.0,
            tax_market=0.05,
            tax_guild=0.05,
            tax_transport=0.05,
            split=PayoutSplitResult(
                guild_cut=0.0,
                silver_pool=0.0,
                silver_per_player=0,
                item_net=0.0,
                item_per_player=0,
                amount_per_player=50000.0,
                total_pool=800000.0,
                buyback_value=4000000.0,
            ),
            participant_ids=[111, 222, 333],
            participant_mentions="<@111> <@222> <@333>",
            confirm_label="Confirmer",
            cancel_label="Annuler",
        )

    @pytest.fixture
    async def _setup_bot(self, view, no_dm_role_id, db):
        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(
            side_effect=lambda key, locale: {
                "payout_dm_title": "Payout reçu",
                "payout_dm_received": "Montant reçu",
                "payout_dm_new_balance": "Nouveau solde",
                "payout_dm_failure_note": "⚠️ Impossible de contacter en MP : {users}",
                "payout_dm_optout_note": "ℹ️ {n} participant(s) ont désactivé les notifications payout",
                "payout_embed_item": "Valeur marchande",
                "payout_embed_gain": "Gain",
                "payout_embed_cost": "Coût",
                "payout_embed_participants": "Participants",
                "payout_embed_split": "Split",
                "payout_embed_buyback": "Rachat",
                "payout_embed_amount": "Montant",
                "payout_embed_list": "Liste",
                "payout_success": "Payout #{id} distribué à {n} joueurs.",
            }.get(key, key)
        )
        return bot

    @pytest.fixture
    async def _setup_interaction(self, _setup_bot, guild):
        bot = _setup_bot
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.client = bot
        interaction.guild = guild
        interaction.channel = AsyncMock()
        interaction.user = MagicMock()
        interaction.user.id = 999
        interaction.locale = "fr"
        interaction.response = AsyncMock()
        return interaction

    @pytest.fixture(params=[None])
    def no_dm_role_id(self, request):
        return request.param

    @pytest.fixture
    def guild(self):
        guild = MagicMock(spec=discord.Guild)

        member_ok = MagicMock(spec=discord.Member)
        member_ok.id = 111
        member_ok.send = AsyncMock()
        member_ok.get_role = MagicMock(return_value=None)

        member_fail = MagicMock(spec=discord.Member)
        member_fail.id = 333
        member_fail.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), ""))
        member_fail.get_role = MagicMock(return_value=None)

        member_no_cache = MagicMock(spec=discord.Member)
        member_no_cache.id = 222
        member_no_cache.send = AsyncMock()
        member_no_cache.get_role = MagicMock(return_value=None)

        members_by_id = {111: member_ok, 333: member_fail}
        guild.get_member = lambda uid: members_by_id.get(uid)

        async def fetch_member(uid: int) -> discord.Member:
            if uid == 222:
                return member_no_cache
            raise discord.NotFound(MagicMock(), "Not found")

        guild.fetch_member = fetch_member

        return guild

    @pytest.mark.asyncio
    async def test_dm_failure_does_not_block_others(self, view, _setup_interaction, db):
        interaction = _setup_interaction

        await view.confirm.callback(interaction)

        cursor = await db.execute("SELECT COUNT(*) FROM payouts")
        row = await cursor.fetchone()
        assert row[0] == 1

        cursor = await db.execute("SELECT COUNT(*) FROM transactions")
        row = await cursor.fetchone()
        assert row[0] == 3

        member_ok = interaction.guild.get_member(111)
        member_no_cache = await interaction.guild.fetch_member(222)
        member_fail = interaction.guild.get_member(333)

        member_ok.send.assert_awaited_once()
        member_no_cache.send.assert_awaited_once()
        member_fail.send.assert_awaited_once()

        interaction.channel.send.assert_awaited_once()

        interaction.response.edit_message.assert_awaited_once()

        call_args = interaction.response.edit_message.call_args
        content = call_args[1]["content"]
        assert "⚠️" in content
        assert "<@333>" in content
        assert "<@111>" not in content.split("⚠️")[-1]
        assert "<@222>" not in content.split("⚠️")[-1]

    @pytest.fixture
    def no_dm_role_id_111(self):
        return 777

    @pytest.fixture
    def guild_with_optout(self, no_dm_role_id_111):
        guild = MagicMock(spec=discord.Guild)

        member_111 = MagicMock(spec=discord.Member)
        member_111.id = 111
        member_111.send = AsyncMock()
        member_111.get_role = MagicMock(return_value=discord.Role)

        member_222 = MagicMock(spec=discord.Member)
        member_222.id = 222
        member_222.send = AsyncMock()
        member_222.get_role = MagicMock(return_value=None)

        member_333 = MagicMock(spec=discord.Member)
        member_333.id = 333
        member_333.send = AsyncMock()
        member_333.get_role = MagicMock(return_value=None)

        members_by_id = {111: member_111, 222: member_222, 333: member_333}
        guild.get_member = lambda uid: members_by_id.get(uid)
        guild.fetch_member = AsyncMock(side_effect=lambda uid: members_by_id[uid])

        return guild

    @pytest.mark.asyncio
    async def test_confirm_skips_dm_for_opt_out_role(self, view, guild_with_optout, db):
        from bot.repositories.bot_config_repository import BotConfigRepository

        bot_config_repo = BotConfigRepository(db)
        await bot_config_repo.update_opt_out_role(role_id=777, updated_by=0)

        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(
            side_effect=lambda key, locale: {
                "payout_dm_title": "Payout reçu",
                "payout_dm_received": "Montant reçu",
                "payout_dm_new_balance": "Nouveau solde",
                "payout_dm_failure_note": "⚠️ Impossible de contacter en MP : {users}",
                "payout_dm_optout_note": "ℹ️ {n} participant(s) ont désactivé les notifications payout",
                "payout_embed_item": "Valeur marchande",
                "payout_embed_gain": "Gain",
                "payout_embed_cost": "Coût",
                "payout_embed_participants": "Participants",
                "payout_embed_split": "Split",
                "payout_embed_buyback": "Rachat",
                "payout_embed_amount": "Montant",
                "payout_embed_list": "Liste",
                "payout_success": "Payout #{id} distribué à {n} joueurs.",
            }.get(key, key)
        )

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.client = bot
        interaction.guild = guild_with_optout
        interaction.channel = AsyncMock()
        interaction.user = MagicMock()
        interaction.user.id = 999
        interaction.locale = "fr"
        interaction.response = AsyncMock()

        await view.confirm.callback(interaction)

        member_111 = guild_with_optout.get_member(111)
        member_222 = guild_with_optout.get_member(222)
        member_333 = guild_with_optout.get_member(333)

        member_111.send.assert_not_called()
        member_222.send.assert_awaited_once()
        member_333.send.assert_awaited_once()

        call_args = interaction.response.edit_message.call_args
        content = call_args[1]["content"]
        assert "⚠️" not in content
        assert "ℹ️" in content or "désactivé" in content

    @pytest.mark.asyncio
    async def test_confirm_sends_dm_without_opt_out_role(self, view, guild_with_optout, db):
        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(
            side_effect=lambda key, locale: {
                "payout_dm_title": "Payout reçu",
                "payout_dm_received": "Montant reçu",
                "payout_dm_new_balance": "Nouveau solde",
                "payout_dm_failure_note": "⚠️ Impossible de contacter en MP : {users}",
                "payout_dm_optout_note": "ℹ️ {n} participant(s) ont désactivé les notifications payout",
                "payout_embed_item": "Valeur marchande",
                "payout_embed_gain": "Gain",
                "payout_embed_cost": "Coût",
                "payout_embed_participants": "Participants",
                "payout_embed_split": "Split",
                "payout_embed_buyback": "Rachat",
                "payout_embed_amount": "Montant",
                "payout_embed_list": "Liste",
                "payout_success": "Payout #{id} distribué à {n} joueurs.",
            }.get(key, key)
        )

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.client = bot
        interaction.guild = guild_with_optout
        interaction.channel = AsyncMock()
        interaction.user = MagicMock()
        interaction.user.id = 999
        interaction.locale = "fr"
        interaction.response = AsyncMock()

        await view.confirm.callback(interaction)

        member_111 = guild_with_optout.get_member(111)
        member_222 = guild_with_optout.get_member(222)
        member_333 = guild_with_optout.get_member(333)

        member_111.send.assert_awaited_once()
        member_222.send.assert_awaited_once()
        member_333.send.assert_awaited_once()

        call_args = interaction.response.edit_message.call_args
        content = call_args[1]["content"]
        assert "⚠️" not in content
        assert "ℹ️" not in content


class TestPayoutConfigRates:
    @pytest.fixture
    async def cog(self, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.get_config()
        await payout_config_repo.update_roles(
            officer_role_id=None, leader_role_id=_LEADER_ROLE_ID, updated_by=0,
        )

        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        return PayoutCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 12345
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == _LEADER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        return interaction

    @pytest.mark.asyncio
    async def test_config_rates_converts_percentages_to_decimals(self, cog, interaction, db):
        await cog.config_rates.callback(cog, interaction, market=10.0, guild=5.0, transport=2.5)

        payout_config_repo = PayoutConfigRepository(db)
        config = await payout_config_repo.get_config()
        assert config.tax_market == 0.10
        assert config.tax_guild == 0.05
        assert config.tax_transport == 0.025
        assert config.updated_by == 12345

    @pytest.mark.asyncio
    async def test_config_rates_rejects_value_above_100(self, cog, interaction, db):
        await cog.config_rates.callback(cog, interaction, market=150.0, guild=10.0, transport=5.0)

        payout_config_repo = PayoutConfigRepository(db)
        config = await payout_config_repo.get_config()
        assert config.tax_market == 0.02  # unchanged

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "payout_config_rates_invalid" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_config_rates_rejects_negative_value(self, cog, interaction, db):
        await cog.config_rates.callback(cog, interaction, market=10.0, guild=-5.0, transport=5.0)

        payout_config_repo = PayoutConfigRepository(db)
        config = await payout_config_repo.get_config()
        assert config.tax_guild == 0.10  # unchanged

        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_config_rates_rejects_zero(self, cog, interaction, db):
        await cog.config_rates.callback(cog, interaction, market=0.0, guild=10.0, transport=5.0)

        payout_config_repo = PayoutConfigRepository(db)
        config = await payout_config_repo.get_config()
        assert config.tax_market == 0.02  # unchanged

        interaction.response.send_message.assert_awaited_once()


class TestBalanceShow:
    _OFFICER_ROLE_ID = 9999
    _LEADER_ROLE_ID = 8888

    @pytest.fixture
    async def cog(self, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.get_config()
        await payout_config_repo.update_roles(
            officer_role_id=self._OFFICER_ROLE_ID,
            leader_role_id=self._LEADER_ROLE_ID,
            updated_by=0,
        )

        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        from bot.cogs.balance.cog import BalanceCog
        return BalanceCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        interaction.locale = "fr"
        return interaction

    @pytest.mark.asyncio
    async def test_show_own_balance_no_permission_check(self, cog, interaction, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=999, amount=5000, reason="seed", created_by=0,
        )

        await cog.show.callback(cog, interaction, member=None)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        embed = call_args[1].get("embed")
        assert embed is not None
        assert "balance_show_self" in embed.description
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_show_other_authorized(self, cog, interaction, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111, amount=3000, reason="seed", created_by=0,
        )

        target = MagicMock(spec=discord.Member)
        target.id = 111
        target.mention = "<@111>"

        await cog.show.callback(cog, interaction, member=target)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        embed = call_args[1].get("embed")
        assert embed is not None
        assert "balance_show_other" in embed.description
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_show_other_unauthorized(self, cog, interaction, db):
        interaction.user.get_role = MagicMock(return_value=None)

        target = MagicMock(spec=discord.Member)
        target.id = 111
        target.mention = "<@111>"

        await cog.show.callback(cog, interaction, member=target)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "balance_officer_only" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True


class TestBalanceList:
    _OFFICER_ROLE_ID = 9999
    _LEADER_ROLE_ID = 8888

    @pytest.fixture
    async def cog(self, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.get_config()
        await payout_config_repo.update_roles(
            officer_role_id=self._OFFICER_ROLE_ID,
            leader_role_id=self._LEADER_ROLE_ID,
            updated_by=0,
        )

        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        from bot.cogs.balance.cog import BalanceCog
        return BalanceCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        interaction.locale = "fr"
        return interaction

    @pytest.mark.asyncio
    async def test_list_permission_gated(self, cog, interaction, db):
        interaction.user.get_role = MagicMock(return_value=None)

        await cog.list_.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "balance_officer_only" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_list_empty(self, cog, interaction, db):
        await cog.list_.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "balance_list_empty" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_list_with_entries(self, cog, interaction, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111, amount=5000, reason="seed", created_by=0,
        )
        await transaction_repo.add_transaction(
            discord_id=222, amount=3000, reason="seed", created_by=0,
        )

        await cog.list_.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        embed = call_args[1].get("embed")
        assert embed is not None
        assert "balance_list_title" in embed.title
        assert call_args[1]["ephemeral"] is True


class TestBalancePayer:
    _OFFICER_ROLE_ID = 9999
    _LEADER_ROLE_ID = 8888

    @pytest.fixture
    async def cog(self, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.get_config()
        await payout_config_repo.update_roles(
            officer_role_id=self._OFFICER_ROLE_ID,
            leader_role_id=self._LEADER_ROLE_ID,
            updated_by=0,
        )

        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        from bot.cogs.balance.cog import BalanceCog
        return BalanceCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        return interaction

    @pytest.fixture
    def joueur(self):
        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.mention = "<@111>"
        return member

    @pytest.mark.asyncio
    async def test_payer_rejects_excessive_amount(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111, amount=1000, reason="seed", created_by=0,
        )

        await cog.payer.callback(cog, interaction, joueur=joueur, montant=2000.0)

        balance = await transaction_repo.get_balance(111)
        assert balance == 1000

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "balance_payer_insufficient_balance" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_payer_succeeds_when_sufficient(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111, amount=5000, reason="seed", created_by=0,
        )

        await cog.payer.callback(cog, interaction, joueur=joueur, montant=2000.0)

        new_balance = await transaction_repo.get_balance(111)
        assert new_balance == 3000

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "balance_payer_paid" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_payer_rejects_non_positive(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111, amount=1000, reason="seed", created_by=0,
        )

        await cog.payer.callback(cog, interaction, joueur=joueur, montant=0.0)

        balance = await transaction_repo.get_balance(111)
        assert balance == 1000

        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_payer_allows_officer_when_level_is_officer(
        self, cog, interaction, joueur, db,
    ):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111, amount=5000, reason="seed", created_by=0,
        )

        await cog.payer.callback(cog, interaction, joueur=joueur, montant=1000.0)

        new_balance = await transaction_repo.get_balance(111)
        assert new_balance == 4000

    @pytest.mark.asyncio
    async def test_payer_rejects_officer_when_level_is_leader(
        self, cog, interaction, joueur, db,
    ):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_pay_add_permission_level(
            level="leader", updated_by=0,
        )

        await cog.payer.callback(cog, interaction, joueur=joueur, montant=1000.0)

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 0

        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_payer_allows_leader_when_level_is_leader(
        self, cog, interaction, joueur, db,
    ):
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._LEADER_ROLE_ID else None
        )

        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_pay_add_permission_level(
            level="leader", updated_by=0,
        )

        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111, amount=5000, reason="seed", created_by=0,
        )

        await cog.payer.callback(cog, interaction, joueur=joueur, montant=1000.0)

        new_balance = await transaction_repo.get_balance(111)
        assert new_balance == 4000

        interaction.response.send_message.assert_awaited_once()


class TestBalanceAjouter:
    _OFFICER_ROLE_ID = 9999
    _LEADER_ROLE_ID = 8888

    @pytest.fixture
    async def cog(self, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.get_config()
        await payout_config_repo.update_roles(
            officer_role_id=self._OFFICER_ROLE_ID,
            leader_role_id=self._LEADER_ROLE_ID,
            updated_by=0,
        )

        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        from bot.cogs.balance.cog import BalanceCog
        return BalanceCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        return interaction

    @pytest.fixture
    def joueur(self):
        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.mention = "<@111>"
        return member

    @pytest.mark.asyncio
    async def test_ajouter_persists_and_updates_balance(
        self, cog, interaction, joueur, db,
    ):
        await cog.ajouter.callback(
            cog, interaction, joueur=joueur, montant=3000.0, raison="Bonus",
        )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 3000

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "balance_ajouter_credited" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_ajouter_rejects_non_positive(self, cog, interaction, joueur, db):
        await cog.ajouter.callback(
            cog, interaction, joueur=joueur, montant=-5.0, raison="Test",
        )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 0

        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ajouter_allows_officer_when_level_is_officer(
        self, cog, interaction, joueur, db,
    ):
        await cog.ajouter.callback(
            cog, interaction, joueur=joueur, montant=1000.0, raison="Test",
        )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 1000

    @pytest.mark.asyncio
    async def test_ajouter_rejects_officer_when_level_is_leader(
        self, cog, interaction, joueur, db,
    ):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_pay_add_permission_level(
            level="leader", updated_by=0,
        )

        await cog.ajouter.callback(
            cog, interaction, joueur=joueur, montant=1000.0, raison="Test",
        )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 0

        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ajouter_allows_leader_when_level_is_leader(
        self, cog, interaction, joueur, db,
    ):
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._LEADER_ROLE_ID else None
        )

        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_pay_add_permission_level(
            level="leader", updated_by=0,
        )

        await cog.ajouter.callback(
            cog, interaction, joueur=joueur, montant=1000.0, raison="Test",
        )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 1000

        interaction.response.send_message.assert_awaited_once()
