import aiosqlite
from dataclasses import dataclass


@dataclass
class BotConfig:
    notification_opt_out_role_id: int | None
    log_channel_id: int | None
    updated_at: str
    updated_by: int | None


_BOT_CONFIG_COLUMNS: dict[str, str] = {
    "updated_by": "INTEGER",
    "log_channel_id": "INTEGER",
}


class BotConfigRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def _ensure_table(self) -> None:
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                id INTEGER PRIMARY KEY DEFAULT 1
                    CHECK (id = 1),
                notification_opt_out_role_id INTEGER,
                updated_at TEXT NOT NULL
                    DEFAULT (datetime('now'))
            )
        """)
        await self._db.execute(
            """
            INSERT OR IGNORE INTO bot_config (id)
            VALUES (1)
        """,
        )
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        cursor = await self._db.execute("PRAGMA table_info(bot_config)")
        existing = {row["name"] for row in await cursor.fetchall()}
        for col_name, col_type in _BOT_CONFIG_COLUMNS.items():
            if col_name not in existing:
                await self._db.execute(f"ALTER TABLE bot_config ADD COLUMN {col_name} {col_type}")

    async def get_config(self) -> BotConfig:
        await self._ensure_table()
        cursor = await self._db.execute("SELECT * FROM bot_config WHERE id = 1")
        row = await cursor.fetchone()
        assert row is not None
        return BotConfig(
            notification_opt_out_role_id=row["notification_opt_out_role_id"],
            log_channel_id=row["log_channel_id"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
        )

    async def update_opt_out_role(self, role_id: int | None, *, updated_by: int) -> None:
        await self._ensure_table()
        await self._db.execute(
            """
            UPDATE bot_config
            SET notification_opt_out_role_id = ?,
                updated_at = datetime('now'),
                updated_by = ?
            WHERE id = 1
        """,
            (role_id, updated_by),
        )
        await self._db.commit()

    async def update_log_channel(self, channel_id: int | None, *, updated_by: int) -> None:
        await self._ensure_table()
        await self._db.execute(
            """
            UPDATE bot_config
            SET log_channel_id = ?,
                updated_at = datetime('now'),
                updated_by = ?
            WHERE id = 1
        """,
            (channel_id, updated_by),
        )
        await self._db.commit()
