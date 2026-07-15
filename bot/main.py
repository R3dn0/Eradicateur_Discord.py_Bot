import asyncio
import logging

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Config
from bot.i18n import JSONTranslator
from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)
from bot.repositories.payout_repository import PayoutRepository
from bot.repositories.transaction_repository import (
    TransactionRepository,
)
from bot.services.payout_config_service import PayoutConfigService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eradicateur_bot")


class EradicateurBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="/", intents=intents)
        self.config = config
        self.db: aiosqlite.Connection | None = None
        self.payout_config_repo: PayoutConfigRepository | None = None
        self.payout_repo: PayoutRepository | None = None
        self.transaction_repo: TransactionRepository | None = None
        self.payout_config_service: PayoutConfigService | None = None

    async def setup_hook(self) -> None:
        translator = JSONTranslator()
        await translator.load()
        await self.tree.set_translator(translator)

        self.db = await aiosqlite.connect(self.config.database_path)
        assert self.db is not None
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")

        self.payout_config_repo = PayoutConfigRepository(self.db)
        self.transaction_repo = TransactionRepository(self.db)
        self.payout_repo = PayoutRepository(self.db, self.transaction_repo)
        self.payout_config_service = PayoutConfigService(self.payout_config_repo)

        await self.load_extension("bot.cogs.guild_commands")
        await self.load_extension("bot.cogs.payout")

        if self.config.guild_id:
            for gid in self.config.guild_id:
                try:
                    guild = discord.Object(id=gid)
                    self.tree.copy_global_to(guild=guild)
                    await self.tree.sync(guild=guild)
                    logger.info("Slash commands synced to guild %s", gid)
                except discord.Forbidden:
                    logger.warning("No access to guild %s, skipping", gid)
        else:
            await self.tree.sync()
            logger.info("Slash commands synced globally (may take up to 1h)")

    async def translate(self, key: str, locale: discord.Locale) -> str:
        translator = self.tree.translator
        if translator is None:
            return key
        ls = app_commands.locale_str(key, key=key)
        result = await translator.translate(ls, locale, None)
        return result or key

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
        await super().close()

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
