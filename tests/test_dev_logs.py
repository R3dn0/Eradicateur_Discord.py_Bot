import asyncio
import logging
from unittest.mock import MagicMock

import pytest

import discord
from discord.app_commands import AppCommandError

from bot.dev_logs import (
    ErrorFileHandler,
    PerGuildFileHandler,
    current_log_context,
    guild_log_context,
    parse_log_level,
    set_console_level,
    setup_dev_logging,
)

APP_LOGGER_NAME = "eradicateur_bot.test_dev_logs"


@pytest.fixture
def app_logger():
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False
    yield logger
    logger.handlers.clear()


class TestParseLogLevel:
    def test_valid_level(self):
        assert parse_log_level("DEBUG") == logging.DEBUG
        assert parse_log_level("info") == logging.INFO
        assert parse_log_level("warning") == logging.WARNING
        assert parse_log_level("ERROR") == logging.ERROR

    def test_default_when_missing(self):
        assert parse_log_level(None) == logging.DEBUG

    def test_invalid_falls_back_to_default(self):
        assert parse_log_level("TRACE") == logging.DEBUG
        assert parse_log_level("", "INFO") == logging.INFO


class TestGuildLogContext:
    def test_sets_and_resets(self):
        assert current_log_context.get().guild_id is None
        with guild_log_context(12345):
            assert current_log_context.get().guild_id == 12345
        assert current_log_context.get().guild_id is None

    def test_none_context(self):
        with guild_log_context(None):
            assert current_log_context.get().guild_id is None


class TestPerGuildFileHandler:
    def test_newest_first_ordering(self, app_logger, tmp_path):
        handler = PerGuildFileHandler(str(tmp_path), level=logging.DEBUG)
        app_logger.addHandler(handler)
        try:
            with guild_log_context(424242):
                app_logger.info("first message")
                app_logger.info("second message")
            lines = (tmp_path / "logs" / "guild_424242.log").read_text().splitlines()
            assert "second message" in lines[0]
            assert "first message" in lines[-1]
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    def test_rotation_keeps_backup_files(self, app_logger, tmp_path):
        handler = PerGuildFileHandler(
            str(tmp_path), level=logging.DEBUG, max_bytes=100, backup_count=3
        )
        app_logger.addHandler(handler)
        try:
            for i in range(200):
                app_logger.info(f"line {i}")
            assert (tmp_path / "logs" / "bot.log.3").exists()
            assert not (tmp_path / "logs" / "bot.log.4").exists()
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    def test_rotation_preserves_ordering_within_chunk(self, app_logger, tmp_path):
        handler = PerGuildFileHandler(
            str(tmp_path), level=logging.DEBUG, max_bytes=200, backup_count=2
        )
        app_logger.addHandler(handler)
        try:
            for i in range(50):
                app_logger.info(f"line {i}")
            content = (tmp_path / "logs" / "bot.log").read_text()
            numbers = [
                int(ln.rsplit("line ", 1)[1]) for ln in content.splitlines() if "line " in ln
            ]
            assert len(numbers) >= 2
            assert numbers == sorted(numbers, reverse=True)
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    def test_routes_to_guild_file(self, app_logger, tmp_path):
        handler = PerGuildFileHandler(str(tmp_path), level=logging.DEBUG)
        app_logger.addHandler(handler)
        try:
            with guild_log_context(424242):
                app_logger.info("hello guild")
            assert (tmp_path / "logs" / "guild_424242.log").exists()
            content = (tmp_path / "logs" / "guild_424242.log").read_text()
            assert "hello guild" in content
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    def test_routes_to_global_file_without_guild(self, app_logger, tmp_path):
        handler = PerGuildFileHandler(str(tmp_path), level=logging.DEBUG)
        app_logger.addHandler(handler)
        try:
            app_logger.info("global message")
            content = (tmp_path / "logs" / "bot.log").read_text()
            assert "global message" in content
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    def test_separates_guilds(self, app_logger, tmp_path):
        handler = PerGuildFileHandler(str(tmp_path), level=logging.DEBUG)
        app_logger.addHandler(handler)
        try:
            with guild_log_context(1):
                app_logger.info("guild one")
            with guild_log_context(2):
                app_logger.info("guild two")
            assert "guild one" in (tmp_path / "logs" / "guild_1.log").read_text()
            assert "guild two" in (tmp_path / "logs" / "guild_2.log").read_text()
            assert "guild one" not in (tmp_path / "logs" / "guild_2.log").read_text()
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    def test_level_filtering(self, app_logger, tmp_path):
        handler = PerGuildFileHandler(str(tmp_path), level=logging.WARNING)
        app_logger.addHandler(handler)
        try:
            app_logger.info("too verbose")
            app_logger.warning("important warning")
            content = (tmp_path / "logs" / "bot.log").read_text()
            assert "too verbose" not in content
            assert "important warning" in content
        finally:
            app_logger.removeHandler(handler)
            handler.close()


class TestSetupDevLogging:
    def test_idempotent(self, tmp_path):
        parent = logging.getLogger("eradicateur_bot")
        previous = [h for h in parent.handlers if isinstance(h, PerGuildFileHandler)]
        try:
            for h in previous:
                parent.removeHandler(h)
            setup_dev_logging(str(tmp_path), logging.DEBUG)
            setup_dev_logging(str(tmp_path), logging.INFO)
            handlers = [h for h in parent.handlers if isinstance(h, PerGuildFileHandler)]
            assert len(handlers) == 1
        finally:
            for h in list(parent.handlers):
                if isinstance(h, PerGuildFileHandler):
                    parent.removeHandler(h)
                    h.close()


class TestErrorFileHandler:
    def test_only_errors_and_critical(self, app_logger, tmp_path):
        handler = ErrorFileHandler(str(tmp_path))
        app_logger.addHandler(handler)
        try:
            app_logger.info("not an error")
            app_logger.warning("not an error either")
            app_logger.error("real problem")
            app_logger.critical("worse problem")
            content = (tmp_path / "logs" / "errors.log").read_text()
            assert "real problem" in content
            assert "worse problem" in content
            assert "not an error" not in content
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    def test_aggregates_all_guilds_in_one_file(self, app_logger, tmp_path):
        handler = ErrorFileHandler(str(tmp_path))
        app_logger.addHandler(handler)
        try:
            with guild_log_context(424242):
                app_logger.error("guild-specific failure")
            app_logger.error("global failure")
            content = (tmp_path / "logs" / "errors.log").read_text()
            assert content.count("guild-specific failure") == 1
            assert "global failure" in content
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    async def test_expected_errors_not_logged_as_problems(self, app_logger, tmp_path):
        from bot.main import GuildAwareCommandTree

        parent = logging.getLogger("eradicateur_bot")
        parent.setLevel(logging.DEBUG)
        handler = ErrorFileHandler(str(tmp_path))
        parent.addHandler(handler)
        try:
            client = MagicMock()
            client.loop = asyncio.get_event_loop()
            client._connection._command_tree = None

            tree = GuildAwareCommandTree(client)

            command = MagicMock()
            command.qualified_name = "balance ajouter"
            guild = MagicMock()
            guild.id = 424242
            interaction = MagicMock(spec=discord.Interaction)
            interaction.guild = guild
            interaction.command = command

            with guild_log_context(424242):
                await tree.on_error(interaction, discord.app_commands.CheckFailure("no permission"))
                await tree.on_error(interaction, AppCommandError("boom"))

            content = (tmp_path / "logs" / "errors.log").read_text()
            assert "boom" in content
            assert "no permission" not in content
        finally:
            parent.removeHandler(handler)
            handler.close()
            parent.setLevel(logging.NOTSET)


class TestSetConsoleLevel:
    def test_updates_stream_handlers_only(self):
        root = logging.getLogger()
        stream = logging.StreamHandler()
        stream.setLevel(logging.INFO)
        root.addHandler(stream)
        try:
            set_console_level(logging.ERROR)
            assert stream.level == logging.ERROR
        finally:
            root.removeHandler(stream)
            stream.close()


class TestGuildAwareCommandTree:
    async def test_routes_command_logs_to_guild_file(self, app_logger, tmp_path):
        from bot.main import GuildAwareCommandTree

        handler = PerGuildFileHandler(str(tmp_path), level=logging.DEBUG)
        app_logger.addHandler(handler)
        try:
            client = MagicMock()
            client.loop = asyncio.get_event_loop()
            client._connection._command_tree = None

            tree = GuildAwareCommandTree(client)

            guild = MagicMock()
            guild.id = 424242
            guild.name = "Test Guild"
            user = MagicMock()
            user.id = 999
            user.display_name = "Alice"
            interaction = MagicMock(spec=discord.Interaction)
            interaction.guild = guild
            interaction.user = user

            async def fake_call(_interaction):
                app_logger.debug("executing fake command")

            tree._call = fake_call

            tree._from_interaction(interaction)
            task = next(t for t in asyncio.all_tasks() if t.get_name() == "CommandTree-invoker")
            await task

            content = (tmp_path / "logs" / "guild_424242.log").read_text()
            assert "executing fake command" in content
        finally:
            app_logger.removeHandler(handler)
            handler.close()

    async def test_on_error_logs_technical_failure(self, tmp_path):
        from bot.main import GuildAwareCommandTree

        parent = logging.getLogger("eradicateur_bot")
        parent.setLevel(logging.DEBUG)
        handler = PerGuildFileHandler(str(tmp_path), level=logging.DEBUG)
        parent.addHandler(handler)
        try:
            client = MagicMock()
            client.loop = asyncio.get_event_loop()
            client._connection._command_tree = None

            tree = GuildAwareCommandTree(client)

            command = MagicMock()
            command.qualified_name = "balance ajouter"
            guild = MagicMock()
            guild.id = 424242
            guild.name = "Test Guild"
            user = MagicMock()
            user.id = 999
            user.display_name = "Alice"
            interaction = MagicMock(spec=discord.Interaction)
            interaction.guild = guild
            interaction.command = command
            interaction.user = user

            with guild_log_context(424242):
                await tree.on_error(interaction, AppCommandError("boom"))

            content = (tmp_path / "logs" / "guild_424242.log").read_text()
            assert "boom" in content
            assert "balance ajouter" in content
            assert 'failed for 999 "Alice" in guild 424242 "Test Guild"' in content
        finally:
            parent.removeHandler(handler)
            handler.close()
            parent.setLevel(logging.NOTSET)

    async def test_on_error_logs_expected_errors_at_debug(self, tmp_path):
        from bot.main import GuildAwareCommandTree

        parent = logging.getLogger("eradicateur_bot")
        parent.setLevel(logging.DEBUG)
        handler = PerGuildFileHandler(str(tmp_path), level=logging.DEBUG)
        parent.addHandler(handler)
        try:
            client = MagicMock()
            client.loop = asyncio.get_event_loop()
            client._connection._command_tree = None

            tree = GuildAwareCommandTree(client)

            command = MagicMock()
            command.qualified_name = "balance ajouter"
            guild = MagicMock()
            guild.id = 424242
            guild.name = "Test Guild"
            user = MagicMock()
            user.id = 999
            user.display_name = "Alice"
            interaction = MagicMock(spec=discord.Interaction)
            interaction.guild = guild
            interaction.command = command
            interaction.user = user

            with guild_log_context(424242):
                await tree.on_error(interaction, discord.app_commands.CheckFailure("no permission"))

            content = (tmp_path / "logs" / "guild_424242.log").read_text()
            assert 'skipped by 999 "Alice" in guild 424242 "Test Guild"' in content
            assert "no permission" in content
            assert "failed for" not in content
        finally:
            parent.removeHandler(handler)
            handler.close()
            parent.setLevel(logging.NOTSET)
