import logging

import discord
from discord import app_commands
from discord.app_commands import AppCommandError
from discord.ext import commands, tasks

from bot.config import Config
from bot.db_manager import GuildDatabaseManager
from bot.dev_logs import guild_log_context, set_console_level, setup_dev_logging
from bot.i18n import JSONTranslator
from bot.repositories.bot_config_repository import BotConfigRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eradicateur_bot")


class GuildAwareCommandTree(app_commands.CommandTree):
    _EXPECTED_ERRORS: tuple[type[AppCommandError], ...] = (
        app_commands.CommandNotFound,
        app_commands.CommandOnCooldown,
        app_commands.CheckFailure,
    )

    def _from_interaction(self, interaction: discord.Interaction) -> None:
        async def wrapper() -> None:
            guild_id = interaction.guild.id if interaction.guild else None
            with guild_log_context(guild_id):
                try:
                    await self._call(interaction)
                except AppCommandError as e:
                    await self._dispatch_error(interaction, e)

        self.client.loop.create_task(wrapper(), name="CommandTree-invoker")

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: AppCommandError,
    ) -> None:
        command_name = (
            interaction.command.qualified_name if interaction.command is not None else "<unknown>"
        )
        user = interaction.user
        guild = interaction.guild
        user_ref = f'{user.id} "{user.display_name}"' if user is not None else "<unknown>"
        guild_ref = f'{guild.id} "{guild.name}"' if guild is not None else "<none>"
        if isinstance(error, self._EXPECTED_ERRORS):
            logger.debug(
                "Command '%s' skipped by %s in guild %s (%s): %s",
                command_name,
                user_ref,
                guild_ref,
                type(error).__name__,
                error,
            )
            return
        logger.error(
            "Command '%s' failed for %s in guild %s",
            command_name,
            user_ref,
            guild_ref,
            exc_info=error,
        )


class EradicateurBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(
            command_prefix="/",
            intents=intents,
            chunk_guilds_at_startup=True,
            tree_cls=GuildAwareCommandTree,
        )
        self.config = config
        self.db_manager: GuildDatabaseManager | None = None

    async def setup_hook(self) -> None:
        translator = JSONTranslator()
        await translator.load()
        await self.tree.set_translator(translator)

        self.db_manager = GuildDatabaseManager(self.config.data_dir)

        _evict_idle.start(self)

        await self.load_extension("bot.cogs.guild_commands")
        await self.load_extension("bot.cogs.payout")
        await self.load_extension("bot.cogs.config")
        await self.load_extension("bot.cogs.balance")
        await self.load_extension("bot.cogs.help")

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
        if self.db_manager is not None:
            await self.db_manager.close_all()
        _evict_idle.stop()
        await super().close()

    async def on_ready(self) -> None:
        assert self.user is not None
        logger.info("Logged in as %s (id: %s)", self.user, self.user.id)

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        if interaction.guild is None or self.db_manager is None:
            return

        user = interaction.user
        guild = interaction.guild
        user_ref = f'{user.id} "{user.display_name}"' if user is not None else "<unknown>"
        logger.debug(
            "Command '%s' executed by %s in guild %s \"%s\"",
            f"/{command.qualified_name}",
            user_ref,
            guild.id,
            guild.name,
        )

        try:
            db = await self.db_manager.get_connection(interaction.guild.id)
            repo = BotConfigRepository(db)
            config = await repo.get_config()
        except Exception:
            logger.warning(
                "Failed to fetch bot_config for guild %s", interaction.guild.id, exc_info=True
            )
            return

        if config.log_channel_id is None:
            return

        channel = interaction.guild.get_channel(config.log_channel_id)
        if channel is None:
            try:
                channel = await interaction.guild.fetch_channel(config.log_channel_id)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "Log channel %s not accessible in guild %s",
                    config.log_channel_id,
                    interaction.guild.id,
                )
                return

        qualified = f"/{command.qualified_name}"
        params_parts = []
        try:
            ns = interaction.namespace
        except Exception:
            ns = None
        if ns is not None:
            for name, value in vars(ns).items():
                if isinstance(value, (discord.Member, discord.User, discord.Role)):
                    formatted = value.mention
                else:
                    formatted = str(value)
                params_parts.append(f"{name}: {formatted}")
        params_str = ", ".join(params_parts)
        template = await self.translate("audit_log_command", interaction.locale)
        embed = discord.Embed(
            description=template.replace("{user}", f"<@{interaction.user.id}>")
            .replace("{channel}", interaction.channel.mention)
            .replace("{command}", qualified)
            .replace("{params}", params_str),
            color=discord.Color.blurple(),
        )

        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Failed to send log message to channel %s in guild %s",
                config.log_channel_id,
                interaction.guild.id,
            )


@tasks.loop(minutes=5)
async def _evict_idle(bot: EradicateurBot) -> None:
    try:
        assert bot.db_manager is not None
        await bot.db_manager.evict_idle()
    except Exception:
        logger.exception("Idle eviction loop error — will retry in 5 minutes")


@_evict_idle.before_loop
async def _wait_ready(bot: EradicateurBot) -> None:
    await bot.wait_until_ready()


async def main() -> None:
    config = Config.from_env()
    setup_dev_logging(config.data_dir, config.log_level)
    set_console_level(logging.INFO)
    logging.getLogger().setLevel(config.log_level)
    logger.setLevel(config.log_level)
    bot = EradicateurBot(config)
    async with bot:
        await bot.start(config.discord_token)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
