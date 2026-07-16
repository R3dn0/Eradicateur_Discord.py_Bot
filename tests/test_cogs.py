import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.cogs.guild_commands import GuildCommands
from bot.cogs.payout.cog import PayoutCog
from bot.repositories.payout_config_repository import PayoutConfig
from bot.cogs.payout.views import (
    ConfirmCancelView,
    ParticipantSelectView,
    RemoveParticipantsView,
)
from bot.services.payout_service import PayoutSplitResult


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
    def _setup_bot(self, view, no_dm_role_id):
        bot = MagicMock()
        bot.payout_repo = MagicMock()
        bot.payout_repo.create_payout = AsyncMock(return_value=42)
        bot.bot_config_repo = MagicMock()
        bot.bot_config_repo.get_config = AsyncMock(
            return_value=MagicMock(notification_opt_out_role_id=no_dm_role_id)
        )
        bot.transaction_repo = MagicMock()
        bot.transaction_repo.get_balance = AsyncMock(return_value=150000.0)
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
    def _setup_interaction(self, _setup_bot, guild):
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
        member_ok.send = AsyncMock()
        member_ok.get_role = MagicMock(return_value=None)

        member_fail = MagicMock(spec=discord.Member)
        member_fail.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), ""))
        member_fail.get_role = MagicMock(return_value=None)

        member_no_cache = MagicMock(spec=discord.Member)
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
    async def test_dm_failure_does_not_block_others(self, view, _setup_interaction):
        interaction = _setup_interaction

        await view.confirm.callback(interaction)

        bot = interaction.client
        bot.payout_repo.create_payout.assert_awaited_once()

        assert bot.transaction_repo.get_balance.await_count == 3

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
        member_111.send = AsyncMock()
        member_111.get_role = MagicMock(return_value=discord.Role)

        member_222 = MagicMock(spec=discord.Member)
        member_222.send = AsyncMock()
        member_222.get_role = MagicMock(return_value=None)

        member_333 = MagicMock(spec=discord.Member)
        member_333.send = AsyncMock()
        member_333.get_role = MagicMock(return_value=None)

        members_by_id = {111: member_111, 222: member_222, 333: member_333}
        guild.get_member = lambda uid: members_by_id.get(uid)
        guild.fetch_member = AsyncMock(side_effect=lambda uid: members_by_id[uid])

        return guild

    @pytest.mark.asyncio
    async def test_confirm_skips_dm_for_opt_out_role(self, view, guild_with_optout):
        bot = MagicMock()
        bot.payout_repo = MagicMock()
        bot.payout_repo.create_payout = AsyncMock(return_value=42)
        bot.bot_config_repo = MagicMock()
        bot.bot_config_repo.get_config = AsyncMock(
            return_value=MagicMock(notification_opt_out_role_id=777)
        )
        bot.transaction_repo = MagicMock()
        bot.transaction_repo.get_balance = AsyncMock(return_value=150000.0)
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
    async def test_confirm_sends_dm_without_opt_out_role(self, view, guild_with_optout):
        bot = MagicMock()
        bot.payout_repo = MagicMock()
        bot.payout_repo.create_payout = AsyncMock(return_value=42)
        bot.bot_config_repo = MagicMock()
        bot.bot_config_repo.get_config = AsyncMock(
            return_value=MagicMock(notification_opt_out_role_id=None)
        )
        bot.transaction_repo = MagicMock()
        bot.transaction_repo.get_balance = AsyncMock(return_value=150000.0)
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
    def cog(self):
        bot = MagicMock()
        bot.payout_config_service = MagicMock()
        bot.payout_config_service.is_leader = AsyncMock(return_value=True)
        bot.payout_config_repo = MagicMock()
        bot.payout_config_repo.update_rates = AsyncMock()
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        return PayoutCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 12345
        interaction.locale = "fr"
        return interaction

    @pytest.mark.asyncio
    async def test_config_rates_converts_percentages_to_decimals(self, cog, interaction):
        await cog.config_rates.callback(cog, interaction, market=10.0, guild=5.0, transport=2.5)
        cog.bot.payout_config_repo.update_rates.assert_awaited_once_with(
            market=0.10, guild=0.05, transport=0.025, updated_by=12345
        )

    @pytest.mark.asyncio
    async def test_config_rates_rejects_value_above_100(self, cog, interaction):
        await cog.config_rates.callback(cog, interaction, market=150.0, guild=10.0, transport=5.0)
        cog.bot.payout_config_repo.update_rates.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "payout_config_rates_invalid" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_config_rates_rejects_negative_value(self, cog, interaction):
        await cog.config_rates.callback(cog, interaction, market=10.0, guild=-5.0, transport=5.0)
        cog.bot.payout_config_repo.update_rates.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_config_rates_rejects_zero(self, cog, interaction):
        await cog.config_rates.callback(cog, interaction, market=0.0, guild=10.0, transport=5.0)
        cog.bot.payout_config_repo.update_rates.assert_not_called()
        interaction.response.send_message.assert_awaited_once()


class TestPayoutPay:
    @pytest.fixture
    def config(self):
        return PayoutConfig(
            tax_market=0.02,
            tax_guild=0.10,
            tax_transport=0.03,
            officer_role_id=None,
            leader_role_id=None,
            updated_at="2024-01-01",
            updated_by=None,
            pay_add_permission_level="officer",
        )

    @pytest.fixture
    def cog(self, config):
        bot = MagicMock()
        bot.payout_config_repo = MagicMock()
        bot.payout_config_repo.get_config = AsyncMock(return_value=config)
        bot.payout_config_service = MagicMock()
        bot.payout_config_service.is_officer = AsyncMock(return_value=True)
        bot.payout_config_service.is_leader = AsyncMock(return_value=False)
        bot.transaction_repo = MagicMock()
        bot.transaction_repo.add_transaction = AsyncMock(return_value=1)
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        return PayoutCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        return interaction

    @pytest.fixture
    def joueur(self):
        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.mention = "<@111>"
        return member

    @pytest.mark.asyncio
    async def test_pay_rejects_excessive_amount(self, cog, interaction, joueur):
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=1000.0)
        await cog.pay.callback(cog, interaction, joueur=joueur, montant=2000.0)
        cog.bot.transaction_repo.add_transaction.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "payout_insufficient_balance" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_pay_succeeds_when_sufficient(self, cog, interaction, joueur):
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=5000.0)
        await cog.pay.callback(cog, interaction, joueur=joueur, montant=2000.0)
        cog.bot.transaction_repo.add_transaction.assert_awaited_once_with(
            discord_id=111,
            amount=-2000.0,
            reason="Manual withdrawal",
            created_by=999,
        )
        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "payout_paid" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_pay_rejects_non_positive(self, cog, interaction, joueur):
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=1000.0)
        await cog.pay.callback(cog, interaction, joueur=joueur, montant=0.0)
        cog.bot.transaction_repo.add_transaction.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pay_allows_officer_when_level_is_officer(self, cog, interaction, joueur):
        cog.bot.payout_config_service.is_officer = AsyncMock(return_value=True)
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=5000.0)
        await cog.pay.callback(cog, interaction, joueur=joueur, montant=1000.0)
        cog.bot.transaction_repo.add_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pay_rejects_officer_when_level_is_leader(self, cog, interaction, joueur):
        cog.bot.payout_config_repo.get_config = AsyncMock(
            return_value=PayoutConfig(
                tax_market=0.02, tax_guild=0.10, tax_transport=0.03,
                officer_role_id=None, leader_role_id=None,
                updated_at="2024-01-01", updated_by=None,
                pay_add_permission_level="leader",
            )
        )
        cog.bot.payout_config_service.is_officer = AsyncMock(return_value=True)
        cog.bot.payout_config_service.is_leader = AsyncMock(return_value=False)
        await cog.pay.callback(cog, interaction, joueur=joueur, montant=1000.0)
        cog.bot.transaction_repo.add_transaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_pay_allows_leader_when_level_is_leader(self, cog, interaction, joueur):
        cog.bot.payout_config_repo.get_config = AsyncMock(
            return_value=PayoutConfig(
                tax_market=0.02, tax_guild=0.10, tax_transport=0.03,
                officer_role_id=None, leader_role_id=None,
                updated_at="2024-01-01", updated_by=None,
                pay_add_permission_level="leader",
            )
        )
        cog.bot.payout_config_service.is_leader = AsyncMock(return_value=True)
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=5000.0)
        await cog.pay.callback(cog, interaction, joueur=joueur, montant=1000.0)
        cog.bot.transaction_repo.add_transaction.assert_awaited_once()


class TestPayoutAdd:
    @pytest.fixture
    def config(self):
        return PayoutConfig(
            tax_market=0.02,
            tax_guild=0.10,
            tax_transport=0.03,
            officer_role_id=None,
            leader_role_id=None,
            updated_at="2024-01-01",
            updated_by=None,
            pay_add_permission_level="officer",
        )

    @pytest.fixture
    def cog(self, config):
        bot = MagicMock()
        bot.payout_config_repo = MagicMock()
        bot.payout_config_repo.get_config = AsyncMock(return_value=config)
        bot.payout_config_service = MagicMock()
        bot.payout_config_service.is_officer = AsyncMock(return_value=True)
        bot.payout_config_service.is_leader = AsyncMock(return_value=False)
        bot.transaction_repo = MagicMock()
        bot.transaction_repo.add_transaction = AsyncMock(return_value=1)
        bot.translate = AsyncMock(side_effect=lambda key, locale: key)
        return PayoutCog(bot)

    @pytest.fixture
    def interaction(self):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        return interaction

    @pytest.fixture
    def joueur(self):
        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.mention = "<@111>"
        return member

    @pytest.mark.asyncio
    async def test_add_persists_and_updates_balance(self, cog, interaction, joueur):
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=7000.0)
        await cog.add.callback(cog, interaction, joueur=joueur, montant=3000.0, raison="Bonus")
        cog.bot.transaction_repo.add_transaction.assert_awaited_once_with(
            discord_id=111,
            amount=3000.0,
            reason="Bonus",
            created_by=999,
        )
        interaction.response.send_message.assert_awaited_once()
        call_args = interaction.response.send_message.call_args
        assert "payout_credited" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_add_rejects_non_positive(self, cog, interaction, joueur):
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=1000.0)
        await cog.add.callback(cog, interaction, joueur=joueur, montant=-5.0, raison="Test")
        cog.bot.transaction_repo.add_transaction.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_allows_officer_when_level_is_officer(self, cog, interaction, joueur):
        cog.bot.payout_config_service.is_officer = AsyncMock(return_value=True)
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=5000.0)
        await cog.add.callback(cog, interaction, joueur=joueur, montant=1000.0, raison="Test")
        cog.bot.transaction_repo.add_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_rejects_officer_when_level_is_leader(self, cog, interaction, joueur):
        cog.bot.payout_config_repo.get_config = AsyncMock(
            return_value=PayoutConfig(
                tax_market=0.02, tax_guild=0.10, tax_transport=0.03,
                officer_role_id=None, leader_role_id=None,
                updated_at="2024-01-01", updated_by=None,
                pay_add_permission_level="leader",
            )
        )
        cog.bot.payout_config_service.is_officer = AsyncMock(return_value=True)
        cog.bot.payout_config_service.is_leader = AsyncMock(return_value=False)
        await cog.add.callback(cog, interaction, joueur=joueur, montant=1000.0, raison="Test")
        cog.bot.transaction_repo.add_transaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_allows_leader_when_level_is_leader(self, cog, interaction, joueur):
        cog.bot.payout_config_repo.get_config = AsyncMock(
            return_value=PayoutConfig(
                tax_market=0.02, tax_guild=0.10, tax_transport=0.03,
                officer_role_id=None, leader_role_id=None,
                updated_at="2024-01-01", updated_by=None,
                pay_add_permission_level="leader",
            )
        )
        cog.bot.payout_config_service.is_leader = AsyncMock(return_value=True)
        cog.bot.transaction_repo.get_balance = AsyncMock(return_value=5000.0)
        await cog.add.callback(cog, interaction, joueur=joueur, montant=1000.0, raison="Test")
        cog.bot.transaction_repo.add_transaction.assert_awaited_once()
