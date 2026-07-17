import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Iterable

import discord

logger = logging.getLogger("eradicateur_bot.discord_dm")


@dataclass
class BulkDMResult:
    sent: list[int]
    skipped: list[int]
    failed: list[int]


async def send_bulk_dm(
    guild: discord.Guild,
    member_ids: Iterable[int],
    build_content: Callable[[discord.Member], Awaitable[discord.Embed]],
    opt_out_role_id: int | None = None,
) -> BulkDMResult:
    sent: list[int] = []
    skipped: list[int] = []
    failed: list[int] = []

    for member_id in member_ids:
        member = guild.get_member(member_id)
        if member is None:
            try:
                member = await guild.fetch_member(member_id)
            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                failed.append(member_id)
                continue

        if opt_out_role_id is not None and member.get_role(opt_out_role_id):
            skipped.append(member_id)
            continue

        try:
            embed = await build_content(member)
        except Exception:
            logger.exception("build_content failed for member %s in guild %s", member_id, guild.id)
            failed.append(member_id)
            continue

        try:
            await member.send(embed=embed)
            sent.append(member_id)
        except (discord.Forbidden, discord.HTTPException):
            failed.append(member_id)

    return BulkDMResult(sent=sent, skipped=skipped, failed=failed)
