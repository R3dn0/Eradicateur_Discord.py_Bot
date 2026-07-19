import aiosqlite
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from bot.cogs.guild_commands import GuildCommands
from bot.cogs.help.cog import HelpCog
from bot.cogs.payout.cog import PayoutCog
from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)
from bot.repositories.payout_repository import PayoutRepository
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
        bot.translate = AsyncMock(return_value="Pong ! ({latency}ms)")
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
            bag_silvers=1000000,
            item_market_value=5000000,
            activity_cost=500000,
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
            bag_silvers=1000000,
            item_market_value=5000000,
            activity_cost=500000,
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


class TestParticipantSelectBotFilter:
    @pytest.mark.asyncio
    async def test_skips_bot_members(self):
        view = ParticipantSelectView(
            bag_silvers=1000000,
            item_market_value=5000000,
            activity_cost=500000,
            select_placeholder="test",
            finish_label="Terminer",
            cancel_label="Annuler",
            retirer_label="Retirer",
            retour_label="Retour",
            remove_prompt="Sélectionnez les participants à retirer :",
            remove_placeholder="Choisissez les participants à retirer",
        )

        bot_member = MagicMock(spec=discord.Member)
        bot_member.id = 999
        bot_member.bot = True

        human_member = MagicMock(spec=discord.Member)
        human_member.id = 111
        human_member.bot = False

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.client = MagicMock()
        interaction.client.translate = AsyncMock(return_value="note")
        interaction.locale = "fr"

        view.on_participants_selected._values = [bot_member, human_member]
        await view.on_participants_selected.callback(interaction)

        assert view.accumulated == {111}
        interaction.response.edit_message.assert_awaited_once()
        call_kwargs = interaction.response.edit_message.call_args[1]
        assert "note" in call_kwargs["content"]
        assert "<@999>" not in call_kwargs["content"]
        assert "<@111>" in call_kwargs["content"]


class TestConfirmCancelViewDMNotifications:
    @pytest.fixture
    def view(self):
        return ConfirmCancelView(
            bag_silvers=1000000,
            item_market_value=5000000,
            activity_cost=500000,
            tax_market=0.05,
            tax_guild=0.05,
            tax_transport=0.05,
            split=PayoutSplitResult(
                guild_cut=0.0,
                silver_pool=0.0,
                silver_per_player=0,
                item_net=0.0,
                item_per_player=0,
                amount_per_player=50000,
                total_pool=800000.0,
                buyback_value=4000000,
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
                "payout_embed_per_player": "─── {amount} par joueur",
                "payout_embed_created_by": "Créé par {user} le {date}",
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
        interaction.user.mention = "<@999>"
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
        member_ok.bot = False
        member_ok.send = AsyncMock()
        member_ok.get_role = MagicMock(return_value=None)

        member_fail = MagicMock(spec=discord.Member)
        member_fail.id = 333
        member_fail.bot = False
        member_fail.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), ""))
        member_fail.get_role = MagicMock(return_value=None)

        member_no_cache = MagicMock(spec=discord.Member)
        member_no_cache.id = 222
        member_no_cache.bot = False
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

        interaction.edit_original_response.assert_awaited_once()

        call_args = interaction.edit_original_response.call_args
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
        member_111.bot = False
        member_111.send = AsyncMock()
        member_111.get_role = MagicMock(return_value=discord.Role)

        member_222 = MagicMock(spec=discord.Member)
        member_222.id = 222
        member_222.bot = False
        member_222.send = AsyncMock()
        member_222.get_role = MagicMock(return_value=None)

        member_333 = MagicMock(spec=discord.Member)
        member_333.id = 333
        member_333.bot = False
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
                "payout_embed_per_player": "─── {amount} par joueur",
                "payout_embed_created_by": "Créé par {user} le {date}",
                "payout_success": "Payout #{id} distribué à {n} joueurs.",
            }.get(key, key)
        )

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.client = bot
        interaction.guild = guild_with_optout
        interaction.channel = AsyncMock()
        interaction.user = MagicMock()
        interaction.user.id = 999
        interaction.user.mention = "<@999>"
        interaction.locale = "fr"
        interaction.response = AsyncMock()

        await view.confirm.callback(interaction)

        member_111 = guild_with_optout.get_member(111)
        member_222 = guild_with_optout.get_member(222)
        member_333 = guild_with_optout.get_member(333)

        member_111.send.assert_not_called()
        member_222.send.assert_awaited_once()
        member_333.send.assert_awaited_once()

        call_args = interaction.edit_original_response.call_args
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
                "payout_embed_per_player": "─── {amount} par joueur",
                "payout_embed_created_by": "Créé par {user} le {date}",
                "payout_success": "Payout #{id} distribué à {n} joueurs.",
            }.get(key, key)
        )

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.client = bot
        interaction.guild = guild_with_optout
        interaction.channel = AsyncMock()
        interaction.user = MagicMock()
        interaction.user.id = 999
        interaction.user.mention = "<@999>"
        interaction.locale = "fr"
        interaction.response = AsyncMock()

        await view.confirm.callback(interaction)

        member_111 = guild_with_optout.get_member(111)
        member_222 = guild_with_optout.get_member(222)
        member_333 = guild_with_optout.get_member(333)

        member_111.send.assert_awaited_once()
        member_222.send.assert_awaited_once()
        member_333.send.assert_awaited_once()

        call_args = interaction.edit_original_response.call_args
        content = call_args[1]["content"]
        assert "⚠️" not in content
        assert "ℹ️" not in content

    @pytest.mark.asyncio
    async def test_confirm_create_payout_failure_does_not_send_dm(self, view, _setup_interaction):
        interaction = _setup_interaction

        with patch(
            "bot.repositories.payout_repository.PayoutRepository.create_payout",
            side_effect=RuntimeError("DB connection lost"),
        ):
            await view.confirm.callback(interaction)

        interaction.channel.send.assert_not_called()

        member_ok = interaction.guild.get_member(111)
        member_fail = interaction.guild.get_member(333)
        member_ok.send.assert_not_called()
        member_fail.send.assert_not_called()

        interaction.edit_original_response.assert_awaited_once()
        call_args = interaction.edit_original_response.call_args
        assert "payout_create_failed" in call_args[1]["content"]


class TestPayoutConfigRates:
    @pytest.fixture
    async def cog(self, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.get_config()
        await payout_config_repo.update_roles(
            officer_role_id=None,
            leader_role_id=_LEADER_ROLE_ID,
            updated_by=0,
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


class TestPayoutConfigRoles:
    _OFFICER_ROLE_ID = 6001
    _LEADER_ROLE_ID = 6002

    @pytest.fixture
    async def cog(self, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.get_config()

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
        interaction.user.id = 5001
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        return interaction

    @pytest.mark.asyncio
    async def test_config_roles_updates(self, cog, interaction, db):
        officer = MagicMock(spec=discord.Role, id=self._OFFICER_ROLE_ID, mention="<@&6001>")
        leader = MagicMock(spec=discord.Role, id=self._LEADER_ROLE_ID, mention="<@&6002>")

        await cog.config_roles.callback(cog, interaction, officer=officer, leader=leader)

        payout_config_repo = PayoutConfigRepository(db)
        config = await payout_config_repo.get_config()
        assert config.officer_role_id == self._OFFICER_ROLE_ID
        assert config.leader_role_id == self._LEADER_ROLE_ID
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_config_permissions_officer_level(self, cog, interaction, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_roles(
            officer_role_id=self._OFFICER_ROLE_ID,
            leader_role_id=self._LEADER_ROLE_ID,
            updated_by=0,
        )
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._LEADER_ROLE_ID else None
        )

        await cog.config_permissions.callback(cog, interaction, level="officer")

        config = await payout_config_repo.get_config()
        assert config.pay_add_permission_level == "officer"
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_config_permissions_leader_only(self, cog, interaction, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_roles(
            officer_role_id=self._OFFICER_ROLE_ID,
            leader_role_id=self._LEADER_ROLE_ID,
            updated_by=0,
        )
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )

        await cog.config_permissions.callback(cog, interaction, level="leader")

        config = await payout_config_repo.get_config()
        assert config.pay_add_permission_level == "officer"  # unchanged
        interaction.response.send_message.assert_awaited_once()
        assert (
            "payout_config_permissions_leader_only"
            in interaction.response.send_message.call_args[0][0]
        )

    @pytest.mark.asyncio
    async def test_config_show_returns_embed(self, cog, interaction, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_rates(
            market=0.10, guild=0.05, transport=0.025, updated_by=0
        )
        await payout_config_repo.update_roles(
            officer_role_id=6001, leader_role_id=6002, updated_by=0
        )

        await cog.config_show.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "embed" in call_args[1]
        assert call_args[1]["ephemeral"] is True


class TestPayoutVoid:
    _OFFICER_ROLE_ID = 7001

    @pytest.fixture
    async def cog(self, db):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.get_config()
        await payout_config_repo.update_roles(
            officer_role_id=self._OFFICER_ROLE_ID,
            leader_role_id=None,
            updated_by=0,
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
        interaction.user.id = 7000
        interaction.user.mention = "<@7000>"
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        return interaction

    @pytest.mark.asyncio
    async def test_void_requires_officer(self, cog, interaction, db):
        interaction.user.get_role = MagicMock(return_value=None)

        await cog.void.callback(cog, interaction, payout_id=1)

        interaction.edit_original_response.assert_awaited_once()
        assert "payout_officer_only" in interaction.edit_original_response.call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_void_rejects_missing_payout(self, cog, interaction, db):
        await cog.void.callback(cog, interaction, payout_id=99999)

        interaction.edit_original_response.assert_awaited_once()
        assert "payout_void_not_found" in interaction.edit_original_response.call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_void_rejects_already_voided(self, cog, interaction, db):
        payout_repo = PayoutRepository(db, TransactionRepository(db))
        payout_id = await payout_repo.create_payout(
            bag_silvers=1_000_000,
            item_market_value=500_000,
            activity_cost=50_000,
            tax_market=0.02,
            tax_guild=0.10,
            tax_transport=0.03,
            amount_per_player=100_000,
            buyback_value=475_000,
            participant_ids=[111],
            created_by=7000,
        )
        await payout_repo.void_payout(payout_id, voided_by=7000)

        await cog.void.callback(cog, interaction, payout_id=payout_id)

        interaction.edit_original_response.assert_awaited_once()
        assert "payout_void_already_voided" in interaction.edit_original_response.call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_void_succeeds(self, cog, interaction, db):
        transaction_repo = TransactionRepository(db)
        payout_repo = PayoutRepository(db, transaction_repo)
        payout_id = await payout_repo.create_payout(
            bag_silvers=1_000_000,
            item_market_value=500_000,
            activity_cost=50_000,
            tax_market=0.02,
            tax_guild=0.10,
            tax_transport=0.03,
            amount_per_player=100_000,
            buyback_value=475_000,
            participant_ids=[111],
            created_by=7000,
        )

        with patch("bot.cogs.payout.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.void.callback(cog, interaction, payout_id=payout_id)

        payout = await payout_repo.get_payout(payout_id)
        assert payout is not None and payout.voided is True
        interaction.edit_original_response.assert_awaited_once()
        call_args = interaction.edit_original_response.call_args
        assert "payout_void_success" in call_args[1]["content"]
        assert "embed" in call_args[1]


class TestConfigCog:
    @pytest.fixture
    def cog(self, db):
        bot = MagicMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        from bot.cogs.config.cog import ConfigCog

        return ConfigCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 8000
        interaction.user.get_role = MagicMock(return_value=None)
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        return interaction

    @pytest.mark.asyncio
    async def test_opt_out_role_set(self, cog, interaction, db):
        role = MagicMock(spec=discord.Role, id=5555, mention="<@&5555>")

        await cog.opt_out_role.callback(cog, interaction, role=role)

        from bot.repositories.bot_config_repository import BotConfigRepository

        bot_config_repo = BotConfigRepository(db)
        config = await bot_config_repo.get_config()
        assert config.notification_opt_out_role_id == 5555
        interaction.response.send_message.assert_awaited_once()
        assert "config_nonotification_role_set" in interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    async def test_opt_out_role_clear(self, cog, interaction, db):
        await cog.opt_out_role.callback(cog, interaction, role=None)

        interaction.response.send_message.assert_awaited_once()
        assert (
            "config_nonotification_role_cleared"
            in interaction.response.send_message.call_args[0][0]
        )

    @pytest.mark.asyncio
    async def test_show_returns_embed(self, cog, interaction, db):
        await cog.show.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "embed" in call_args[1]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_log_channel_set(self, cog, interaction, db):
        channel = MagicMock(spec=discord.TextChannel, id=6666, mention="<#6666>")

        await cog.log_channel.callback(cog, interaction, salon=channel)

        from bot.repositories.bot_config_repository import BotConfigRepository

        bot_config_repo = BotConfigRepository(db)
        config = await bot_config_repo.get_config()
        assert config.log_channel_id == 6666
        interaction.response.send_message.assert_awaited_once()
        assert "config_logs_channel_set" in interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    async def test_log_channel_clear(self, cog, interaction, db):
        await cog.log_channel.callback(cog, interaction, salon=None)

        interaction.response.send_message.assert_awaited_once()
        assert "config_logs_channel_cleared" in interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    async def test_log_show_returns_embed(self, cog, interaction, db):
        await cog.log_show.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "embed" in call_args[1]
        assert call_args[1]["ephemeral"] is True


class TestBalanceHistory:
    _OFFICER_ROLE_ID = 7501
    _LEADER_ROLE_ID = 7502

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
        interaction.followup = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 7500
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        interaction.locale = "fr"
        return interaction

    @pytest.mark.asyncio
    async def test_history_own_empty(self, cog, interaction, db):
        await cog.history.callback(cog, interaction, member=None)

        interaction.response.send_message.assert_awaited_once()
        assert "balance_history_empty" in interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    async def test_history_own_with_transactions(self, cog, interaction, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=7500, amount=1000, reason="seed", created_by=0
        )

        await cog.history.callback(cog, interaction, member=None)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "embed" in call_args[1]

    @pytest.mark.asyncio
    async def test_history_other_authorized(self, cog, interaction, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111, amount=3000, reason="seed", created_by=0
        )
        target = MagicMock(spec=discord.Member)
        target.id = 111

        await cog.history.callback(cog, interaction, member=target)

        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "embed" in call_args[1]

    @pytest.mark.asyncio
    async def test_history_other_unauthorized(self, cog, interaction, db):
        interaction.user.get_role = MagicMock(return_value=None)
        target = MagicMock(spec=discord.Member)
        target.id = 111

        await cog.history.callback(cog, interaction, member=target)

        interaction.response.send_message.assert_awaited_once()
        assert "balance_history_officer_only" in interaction.response.send_message.call_args[0][0]


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
            discord_id=999,
            amount=5000,
            reason="seed",
            created_by=0,
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
            discord_id=111,
            amount=3000,
            reason="seed",
            created_by=0,
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
            discord_id=111,
            amount=5000,
            reason="seed",
            created_by=0,
        )
        await transaction_repo.add_transaction(
            discord_id=222,
            amount=3000,
            reason="seed",
            created_by=0,
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
        interaction.edit_original_response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        interaction.user.mention = "<@999>"
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        interaction.locale = "fr"
        return interaction

    @pytest.fixture
    def joueur(self):
        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.bot = False
        member.mention = "<@111>"
        return member

    @pytest.mark.asyncio
    async def test_payer_rejects_excessive_amount(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111,
            amount=1000,
            reason="seed",
            created_by=0,
        )

        await cog.pay.callback(cog, interaction, joueur=joueur, montant=2000)

        balance = await transaction_repo.get_balance(111)
        assert balance == 1000

        interaction.edit_original_response.assert_awaited_once()
        call_args = interaction.edit_original_response.call_args
        assert "balance_payer_insufficient_balance" in call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_payer_succeeds_when_sufficient(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111,
            amount=5000,
            reason="seed",
            created_by=0,
        )

        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.pay.callback(cog, interaction, joueur=joueur, montant=2000)

        new_balance = await transaction_repo.get_balance(111)
        assert new_balance == 3000

        interaction.edit_original_response.assert_awaited_once()
        call_args = interaction.edit_original_response.call_args
        assert "balance_payer_paid" in call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_payer_rejects_non_positive(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111,
            amount=1000,
            reason="seed",
            created_by=0,
        )

        await cog.pay.callback(cog, interaction, joueur=joueur, montant=0)

        balance = await transaction_repo.get_balance(111)
        assert balance == 1000

        interaction.edit_original_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_payer_allows_officer_when_level_is_officer(
        self,
        cog,
        interaction,
        joueur,
        db,
    ):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111,
            amount=5000,
            reason="seed",
            created_by=0,
        )

        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.pay.callback(cog, interaction, joueur=joueur, montant=1000)

        new_balance = await transaction_repo.get_balance(111)
        assert new_balance == 4000

    @pytest.mark.asyncio
    async def test_payer_rejects_officer_when_level_is_leader(
        self,
        cog,
        interaction,
        joueur,
        db,
    ):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_pay_add_permission_level(
            level="leader",
            updated_by=0,
        )

        await cog.pay.callback(cog, interaction, joueur=joueur, montant=1000)

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 0

        interaction.edit_original_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_payer_allows_leader_when_level_is_leader(
        self,
        cog,
        interaction,
        joueur,
        db,
    ):
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._LEADER_ROLE_ID else None
        )

        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_pay_add_permission_level(
            level="leader",
            updated_by=0,
        )

        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111,
            amount=5000,
            reason="seed",
            created_by=0,
        )

        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.pay.callback(cog, interaction, joueur=joueur, montant=1000)

        new_balance = await transaction_repo.get_balance(111)
        assert new_balance == 4000

        interaction.edit_original_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_payer_sends_dm(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111,
            amount=5000,
            reason="seed",
            created_by=0,
        )

        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.pay.callback(cog, interaction, joueur=joueur, montant=2000)

        mock_dm.assert_awaited_once()
        call_kwargs = mock_dm.call_args[1]
        assert call_kwargs["member_ids"] == [111]
        assert "dm_context" in call_kwargs["context"]

    @pytest.mark.asyncio
    async def test_payer_appends_optout_note(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111,
            amount=5000,
            reason="seed",
            created_by=0,
        )

        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[111], failed=[])
            await cog.pay.callback(cog, interaction, joueur=joueur, montant=2000)

        call_args = interaction.edit_original_response.call_args
        assert "payout_dm_optout_note" in call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_payer_appends_failure_note(self, cog, interaction, joueur, db):
        transaction_repo = TransactionRepository(db)
        await transaction_repo.add_transaction(
            discord_id=111,
            amount=5000,
            reason="seed",
            created_by=0,
        )

        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[111])
            await cog.pay.callback(cog, interaction, joueur=joueur, montant=2000)

        call_args = interaction.edit_original_response.call_args
        assert "payout_dm_failure_note" in call_args[1]["content"]


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
        interaction.edit_original_response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        interaction.user.mention = "<@999>"
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._OFFICER_ROLE_ID else None
        )
        interaction.guild = MagicMock()
        interaction.guild.id = 12345
        interaction.locale = "fr"
        return interaction

    @pytest.fixture
    def joueur(self):
        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.bot = False
        member.mention = "<@111>"
        return member

    @pytest.mark.asyncio
    async def test_ajouter_persists_and_updates_balance(
        self,
        cog,
        interaction,
        joueur,
        db,
    ):
        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.add.callback(
                cog,
                interaction,
                joueur=joueur,
                montant=3000,
                raison="Bonus",
            )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 3000

        interaction.edit_original_response.assert_awaited_once()
        call_args = interaction.edit_original_response.call_args
        assert "balance_ajouter_credited" in call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_ajouter_rejects_non_positive(self, cog, interaction, joueur, db):
        await cog.add.callback(
            cog,
            interaction,
            joueur=joueur,
            montant=-5,
            raison="Test",
        )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 0

        interaction.edit_original_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ajouter_allows_officer_when_level_is_officer(
        self,
        cog,
        interaction,
        joueur,
        db,
    ):
        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.add.callback(
                cog,
                interaction,
                joueur=joueur,
                montant=1000,
                raison="Test",
            )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 1000

    @pytest.mark.asyncio
    async def test_ajouter_rejects_officer_when_level_is_leader(
        self,
        cog,
        interaction,
        joueur,
        db,
    ):
        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_pay_add_permission_level(
            level="leader",
            updated_by=0,
        )

        await cog.add.callback(
            cog,
            interaction,
            joueur=joueur,
            montant=1000,
            raison="Test",
        )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 0

        interaction.edit_original_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ajouter_allows_leader_when_level_is_leader(
        self,
        cog,
        interaction,
        joueur,
        db,
    ):
        interaction.user.get_role = MagicMock(
            side_effect=lambda rid: MagicMock() if rid == self._LEADER_ROLE_ID else None
        )

        payout_config_repo = PayoutConfigRepository(db)
        await payout_config_repo.update_pay_add_permission_level(
            level="leader",
            updated_by=0,
        )

        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.add.callback(
                cog,
                interaction,
                joueur=joueur,
                montant=1000,
                raison="Test",
            )

        transaction_repo = TransactionRepository(db)
        balance = await transaction_repo.get_balance(111)
        assert balance == 1000

        interaction.edit_original_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ajouter_sends_dm(self, cog, interaction, joueur, db):
        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[])
            await cog.add.callback(
                cog,
                interaction,
                joueur=joueur,
                montant=3000,
                raison="Bonus",
            )

        mock_dm.assert_awaited_once()
        call_kwargs = mock_dm.call_args[1]
        assert call_kwargs["member_ids"] == [111]
        assert "dm_context" in call_kwargs["context"]

    @pytest.mark.asyncio
    async def test_ajouter_appends_optout_note(self, cog, interaction, joueur, db):
        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[111], failed=[])
            await cog.add.callback(
                cog,
                interaction,
                joueur=joueur,
                montant=3000,
                raison="Bonus",
            )

        call_args = interaction.edit_original_response.call_args
        assert "payout_dm_optout_note" in call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_ajouter_appends_failure_note(self, cog, interaction, joueur, db):
        with patch("bot.cogs.balance.cog.send_bulk_dm", new_callable=AsyncMock) as mock_dm:
            mock_dm.return_value = MagicMock(skipped=[], failed=[111])
            await cog.add.callback(
                cog,
                interaction,
                joueur=joueur,
                montant=3000,
                raison="Bonus",
            )

        call_args = interaction.edit_original_response.call_args
        assert "payout_dm_failure_note" in call_args[1]["content"]


class TestHelpCommand:
    @pytest.fixture
    def cog(self):
        bot = MagicMock()
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        return HelpCog(bot)

    @pytest.mark.asyncio
    async def test_help_responds_with_embed(self, cog):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        await cog.help.callback(cog, interaction)
        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        embed = call_args[1]["embed"]
        assert isinstance(embed, discord.Embed)
        assert embed.title is not None
        assert call_args[1]["ephemeral"] is True


class TestAuditLog:
    @pytest.fixture
    async def audit_bot(self, db):
        from bot.repositories.bot_config_repository import BotConfigRepository

        repo = BotConfigRepository(db)
        await repo.get_config()
        await repo.update_log_channel(channel_id=9999, updated_by=0)

        bot = AsyncMock()
        bot.db_manager = AsyncMock()
        bot.db_manager.get_connection = AsyncMock(return_value=db)
        bot.translate = AsyncMock(
            side_effect=lambda key, locale: {
                "audit_log_command": "{user} used a command in {channel}:\n`{command}`\n{params}",
            }.get(key, key)
        )
        return bot

    @pytest.fixture
    def log_channel(self):
        ch = AsyncMock(spec=discord.TextChannel)
        ch.mention = "<#9999>"
        ch.send = AsyncMock()
        return ch

    @pytest.fixture
    def guild(self, log_channel):
        g = MagicMock(spec=discord.Guild)
        g.get_channel = MagicMock(return_value=log_channel)
        g.id = 12345
        g.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), ""))
        return g

    @pytest.mark.asyncio
    async def test_logs_command_with_params(self, audit_bot, guild, log_channel):
        bot = audit_bot

        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.mention = "<@111>"

        class FakeNamespace:
            def __init__(self, **kwargs):
                self.__dict__ = kwargs

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.channel = MagicMock()
        interaction.channel.mention = "<#6666>"
        interaction.user.id = 999
        interaction.locale = "fr"
        interaction.response = AsyncMock()
        interaction.namespace = FakeNamespace(
            joueur=member, montant=150000, raison="Compensation erreur payout"
        )

        command = MagicMock()
        command.qualified_name = "balance ajouter"

        from bot.main import EradicateurBot

        await EradicateurBot.on_app_command_completion(bot, interaction, command)

        log_channel.send.assert_awaited_once()
        embed = log_channel.send.call_args[1]["embed"]
        desc = embed.description
        assert "/balance ajouter" in desc
        assert "joueur: <@111>" in desc
        assert "montant: 150000" in desc
        assert "raison: Compensation erreur payout" in desc

    @pytest.mark.asyncio
    async def test_logs_command_without_params(self, audit_bot, guild, log_channel):
        bot = audit_bot

        class FakeNamespace:
            def __init__(self, **kwargs):
                self.__dict__ = kwargs

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.channel = MagicMock()
        interaction.channel.mention = "<#6666>"
        interaction.user.id = 999
        interaction.locale = "en"
        interaction.response = AsyncMock()
        interaction.namespace = FakeNamespace()

        command = MagicMock()
        command.qualified_name = "ping"

        from bot.main import EradicateurBot

        await EradicateurBot.on_app_command_completion(bot, interaction, command)

        log_channel.send.assert_awaited_once()
        embed = log_channel.send.call_args[1]["embed"]
        desc = embed.description
        assert "/ping" in desc
        assert "joueur:" not in desc
