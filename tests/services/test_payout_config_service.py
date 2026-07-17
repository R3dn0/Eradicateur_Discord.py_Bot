from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.repositories.payout_config_repository import PayoutConfig
from bot.services.payout_config_service import PayoutConfigService


def _make_config(
    officer_role_id: int | None = None,
    leader_role_id: int | None = None,
    pay_add_permission_level: str = "officer",
) -> PayoutConfig:
    return PayoutConfig(
        tax_market=0.02,
        tax_guild=0.10,
        tax_transport=0.03,
        officer_role_id=officer_role_id,
        leader_role_id=leader_role_id,
        updated_at="2024-01-01",
        updated_by=None,
        pay_add_permission_level=pay_add_permission_level,
    )


def _make_member(role_ids: set[int]) -> discord.Member:
    member = MagicMock(spec=discord.Member)
    member.get_role = MagicMock(side_effect=lambda rid: rid in role_ids)
    return member


class TestPayoutConfigService:
    @pytest.mark.asyncio
    async def test_is_officer_leader_only_member(self):
        repo = AsyncMock()
        repo.get_config = AsyncMock(return_value=_make_config(leader_role_id=12345))
        service = PayoutConfigService(repo)
        member = _make_member({12345})

        assert await service.is_officer(member) is True
        assert await service.is_leader(member) is True
        assert await service.check_pay_add_permission(member) is True

    @pytest.mark.asyncio
    async def test_is_officer_officer_only_member(self):
        repo = AsyncMock()
        repo.get_config = AsyncMock(return_value=_make_config(officer_role_id=67890))
        service = PayoutConfigService(repo)
        member = _make_member({67890})

        assert await service.is_officer(member) is True
        assert await service.is_leader(member) is False
        assert await service.check_pay_add_permission(member) is True

    @pytest.mark.asyncio
    async def test_no_role_member(self):
        repo = AsyncMock()
        repo.get_config = AsyncMock(
            return_value=_make_config(officer_role_id=67890, leader_role_id=12345)
        )
        service = PayoutConfigService(repo)
        member = _make_member(set())

        assert await service.is_officer(member) is False
        assert await service.is_leader(member) is False
        assert await service.check_pay_add_permission(member) is False

    @pytest.mark.asyncio
    async def test_check_pay_add_permission_leader_level(self):
        repo = AsyncMock()
        repo.get_config = AsyncMock(
            return_value=_make_config(leader_role_id=12345, pay_add_permission_level="leader")
        )
        service = PayoutConfigService(repo)
        officer_only = _make_member({67890})
        leader = _make_member({12345})

        assert await service.check_pay_add_permission(officer_only) is False
        assert await service.check_pay_add_permission(leader) is True
