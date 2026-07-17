import asyncio
import logging
import os
import time
from pathlib import Path

import aiosqlite

from bot.repositories.bot_config_repository import BotConfigRepository
from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)
from bot.repositories.payout_repository import PayoutRepository
from bot.repositories.transaction_repository import (
    TransactionRepository,
)

logger = logging.getLogger("eradicateur_bot.db_manager")


class GuildDatabaseManager:
    def __init__(self, data_dir: str, idle_minutes: int = 30) -> None:
        self._guilds_dir = os.path.join(data_dir, "guilds")
        self._idle_seconds = idle_minutes * 60
        self._connections: dict[int, tuple[aiosqlite.Connection, float]] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._globals_lock: asyncio.Lock = asyncio.Lock()

    async def _ensure_guilds_dir(self) -> None:
        Path(self._guilds_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    async def _init_schema(conn: aiosqlite.Connection) -> None:
        bot_config_repo = BotConfigRepository(conn)
        await bot_config_repo._ensure_table()

        payout_config_repo = PayoutConfigRepository(conn)
        await payout_config_repo._ensure_table()

        transaction_repo = TransactionRepository(conn)
        await transaction_repo._ensure_table()

        payout_repo = PayoutRepository(conn, transaction_repo)
        await payout_repo._ensure_tables()

    async def get_connection(self, guild_id: int) -> aiosqlite.Connection:
        if guild_id not in self._locks:
            async with self._globals_lock:
                if guild_id not in self._locks:
                    self._locks[guild_id] = asyncio.Lock()

        async with self._locks[guild_id]:
            if guild_id in self._connections:
                conn, _ = self._connections[guild_id]
                self._connections[guild_id] = (conn, time.monotonic())
                return conn

            await self._ensure_guilds_dir()
            db_path = os.path.join(self._guilds_dir, f"{guild_id}.db")
            conn = await aiosqlite.connect(db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await self._init_schema(conn)
            self._connections[guild_id] = (conn, time.monotonic())
            logger.info("Opened database for guild %s", guild_id)
            return conn

    async def evict_idle(self) -> None:
        now = time.monotonic()
        to_evict = [
            gid
            for gid, (_, ts) in self._connections.items()
            if now - ts > self._idle_seconds
        ]
        for guild_id in to_evict:
            conn, _ = self._connections.pop(guild_id)
            await conn.close()
            self._locks.pop(guild_id, None)
            logger.info("Evicted idle database for guild %s", guild_id)

    async def close_all(self) -> None:
        for guild_id, (conn, _) in list(self._connections.items()):
            await conn.close()
            del self._connections[guild_id]
            logger.info("Closed database for guild %s", guild_id)
        self._locks.clear()
