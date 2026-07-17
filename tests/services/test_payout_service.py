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
