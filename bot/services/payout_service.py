from dataclasses import dataclass

from bot.services.payout_config_service import PayoutRates


@dataclass(frozen=True)
class PayoutSplitResult:
    guild_cut: float
    silver_pool: float
    silver_per_player: int
    item_net: float
    item_per_player: int
    amount_per_player: int
    total_pool: float
    buyback_value: int


def compute_split(
    bag_silvers: float,
    item_market_value: float,
    activity_cost: float,
    rates: PayoutRates,
    participant_count: int,
) -> PayoutSplitResult:
    guild_cut = bag_silvers * rates.guild
    silver_pool = max(0, bag_silvers - guild_cut)
    silver_per_player = int(silver_pool // participant_count)

    total_taxes = rates.market + rates.guild + rates.transport
    item_net = max(0, (item_market_value - activity_cost) * (1 - total_taxes))
    item_per_player = int(item_net // participant_count)

    total_per_player = silver_per_player + item_per_player
    total_pool = silver_pool + item_net
    buyback_value = max(0, item_market_value * (1 - rates.market - rates.transport))

    return PayoutSplitResult(
        guild_cut=guild_cut,
        silver_pool=silver_pool,
        silver_per_player=silver_per_player,
        item_net=item_net,
        item_per_player=item_per_player,
        amount_per_player=int(total_per_player),
        total_pool=total_pool,
        buyback_value=int(buyback_value),
    )
