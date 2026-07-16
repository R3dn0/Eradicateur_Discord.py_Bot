from dataclasses import dataclass

import discord

from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)


@dataclass(frozen=True)
class PayoutRates:
    market: float
    guild: float
    transport: float


class PayoutConfigService:
    def __init__(self, repo: PayoutConfigRepository) -> None:
        self._repo = repo

    async def get_rates(self) -> PayoutRates:
        config = await self._repo.get_config()
        return PayoutRates(
            market=config.tax_market,
            guild=config.tax_guild,
            transport=config.tax_transport,
        )

    async def is_officer(self, member: discord.Member) -> bool:
        config = await self._repo.get_config()
        if config.leader_role_id and member.get_role(config.leader_role_id):
            return True
        if config.officer_role_id and member.get_role(config.officer_role_id):
            return True
        return False

    async def check_pay_add_permission(self, member: discord.Member) -> bool:
        config = await self._repo.get_config()
        if config.pay_add_permission_level == "leader":
            return await self.is_leader(member)
        return await self.is_officer(member)

    async def is_leader(self, member: discord.Member) -> bool:
        config = await self._repo.get_config()
        if config.leader_role_id and member.get_role(config.leader_role_id):
            return True
        return False
