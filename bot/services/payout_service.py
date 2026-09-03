import logging
from dataclasses import dataclass

from bot.services.payout_config_service import PayoutRates

logger = logging.getLogger("eradicateur_bot.payout_service")


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
    guild_gain: float = 0.0


def compute_split(
    bag_silvers: float,
    item_market_value: float,
    activity_cost: float,
    rates: PayoutRates,
    participant_count: int,
) -> PayoutSplitResult:
    guild_silver_cut = max(0.0, bag_silvers * rates.guild)
    silver_pool = max(0.0, bag_silvers - guild_silver_cut)
    silver_per_player = int(silver_pool // participant_count)

    total_taxes = rates.market + rates.guild + rates.transport
    taxable_items = max(0.0, item_market_value - activity_cost)
    item_net = max(0.0, taxable_items * (1 - total_taxes))
    item_per_player = int(item_net // participant_count)

    total_per_player = silver_per_player + item_per_player
    total_pool = silver_pool + item_net
    buyback_value = max(0.0, item_market_value * (1 - rates.market - rates.transport))
    guild_item_cut = max(0.0, taxable_items * rates.guild)
    guild_gain = max(0.0, guild_silver_cut + guild_item_cut)

    logger.debug(
        "Payout split computed: bag=%s item=%s activity=%s participants=%s -> %s silver/player (guild_gain=%s)",
        bag_silvers,
        item_market_value,
        activity_cost,
        participant_count,
        silver_per_player,
        guild_gain,
    )

    return PayoutSplitResult(
        guild_cut=guild_gain,
        silver_pool=silver_pool,
        silver_per_player=silver_per_player,
        item_net=item_net,
        item_per_player=item_per_player,
        amount_per_player=int(total_per_player),
        total_pool=total_pool,
        buyback_value=int(buyback_value),
        guild_gain=guild_gain,
    )
