import pytest
from bot.services.payout_config_service import PayoutRates
from bot.services.payout_service import compute_split


class TestComputeSplit:
    def test_known_example(self):
        rates = PayoutRates(market=0.02, guild=0.10, transport=0.03)
        result = compute_split(
            bag_silvers=1_340_000,
            item_market_value=30_600_000,
            activity_cost=3_364_000,
            rates=rates,
            participant_count=9,
        )

        assert result.silver_per_player == 134_000
        assert result.buyback_value == 29_070_000

        total_per_player = result.silver_per_player + result.item_per_player
        assert total_per_player == result.amount_per_player

    def test_zero_participants_raises(self):
        rates = PayoutRates(market=0.02, guild=0.10, transport=0.03)
        with pytest.raises(ZeroDivisionError):
            compute_split(
                bag_silvers=1_000_000,
                item_market_value=500_000,
                activity_cost=50_000,
                rates=rates,
                participant_count=0,
            )

    def test_very_large_amounts(self):
        rates = PayoutRates(market=0.02, guild=0.10, transport=0.03)
        result = compute_split(
            bag_silvers=100_000_000_000,
            item_market_value=50_000_000_000,
            activity_cost=5_000_000_000,
            rates=rates,
            participant_count=100,
        )
        assert result.amount_per_player >= 0
        assert result.buyback_value >= 0

    def test_pathological_inputs_never_negative(self):
        rates = PayoutRates(market=0.02, guild=0.10, transport=0.03)

        result = compute_split(
            bag_silvers=0,
            item_market_value=0,
            activity_cost=0,
            rates=rates,
            participant_count=1,
        )
        assert result.amount_per_player >= 0
        assert result.buyback_value >= 0

        result = compute_split(
            bag_silvers=-1_000_000,
            item_market_value=-500_000,
            activity_cost=100_000,
            rates=rates,
            participant_count=5,
        )
        assert result.amount_per_player >= 0
        assert result.buyback_value >= 0

        result = compute_split(
            bag_silvers=1_000_000,
            item_market_value=500_000,
            activity_cost=-100_000,
            rates=rates,
            participant_count=2,
        )
        assert result.amount_per_player >= 0
        assert result.buyback_value >= 0

        result = compute_split(
            bag_silvers=100,
            item_market_value=100,
            activity_cost=0,
            rates=PayoutRates(market=2.0, guild=2.0, transport=2.0),
            participant_count=1,
        )
        assert result.amount_per_player >= 0
        assert result.buyback_value >= 0
