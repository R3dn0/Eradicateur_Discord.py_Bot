import functools
from collections.abc import Callable, Coroutine
from typing import Any

import discord

from bot.main import EradicateurBot


def require_guild_member(
    func: Callable[..., Coroutine[Any, Any, None]],
) -> Callable[..., Coroutine[Any, Any, None]]:
    @functools.wraps(func)
    async def wrapper(
        self: Any, interaction: discord.Interaction, *args: Any, **kwargs: Any
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            bot: EradicateurBot = self.bot  # type: ignore
            msg = await bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        return await func(self, interaction, *args, **kwargs)

    return wrapper
