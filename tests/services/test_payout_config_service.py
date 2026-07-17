from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.repositories.payout_config_repository import PayoutConfig
from bot.services.payout_config_service import PayoutConfigService


class TestPayoutConfigService:
    @pytest.mark.asyncio
    async def test_is_officer_returns_true_for_leader_only_member(self):
        repo = AsyncMock()
        repo.get_config = AsyncMock(
            return_value=PayoutConfig(
                tax_market=0.02,
                tax_guild=0.10,
                tax_transport=0.03,
                officer_role_id=None,
                leader_role_id=12345,
                updated_at="2024-01-01",
                updated_by=None,
                pay_add_permission_level="officer",
            )
        )
        service = PayoutConfigService(repo)
        member = MagicMock(spec=discord.Member)
        member.get_role = MagicMock(side_effect=lambda rid: rid == 12345)

        result = await service.is_officer(member)
        assert result is True