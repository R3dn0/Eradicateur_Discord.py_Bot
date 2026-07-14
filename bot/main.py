import asyncio
import logging

import discord
from discord.ext import commands

from bot.config import Config
from bot.i18n import JSONTranslator
from bot.repositories.member_repository import MemberRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eradicateur_bot")


class EradicateurBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.repository = MemberRepository(config.database_path)

    async def setup_hook(self) -> None:
        translator = JSONTranslator()
        await translator.load()
        await self.tree.set_translator(translator)

        await self.load_extension("bot.cogs.guild_commands")

        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(
                "Slash commands synced to guild %s", self.config.guild_id
            )
        else:
            await self.tree.sync()
            logger.info(
                "Slash commands synced globally (may take up to 1h)"
            )

    async def on_ready(self) -> None:
        assert self.user is not None
        logger.info("Logged in as %s (id: %s)", self.user, self.user.id)


async def main() -> None:
    config = Config.from_env()
    bot = EradicateurBot(config)
    async with bot:
        await bot.start(config.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
