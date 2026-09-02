import aiosqlite

from bot.repositories.base_repository import BaseRepository


class ActivityPoolRepository(BaseRepository):
    _TABLE_NAME = "activity_pool"
    _COLUMNS: dict[str, str] = {}

    def __init__(self, db: aiosqlite.Connection) -> None:
        super().__init__(db)

    async def _ensure_table(self) -> None:
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS activity_pool (
                guild_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                label TEXT NOT NULL,
                PRIMARY KEY (guild_id, position)
            )
        """)
        await self._run_migrations()
        await self._db.commit()

    async def get_labels(self, guild_id: int) -> list[str]:
        await self._ensure_table()
        cursor = await self._db.execute(
            """
            SELECT label FROM activity_pool
            WHERE guild_id = ?
            ORDER BY position ASC
            """,
            (str(guild_id),),
        )
        rows = await cursor.fetchall()
        return [row["label"] for row in rows]

    async def add_label(self, guild_id: int, label: str) -> None:
        await self._ensure_table()
        cursor = await self._db.execute(
            """
            SELECT COALESCE(MAX(position), 0) FROM activity_pool
            WHERE guild_id = ?
            """,
            (str(guild_id),),
        )
        row = await cursor.fetchone()
        position = (row[0] or 0) + 1
        await self._db.execute(
            """
            INSERT INTO activity_pool (guild_id, position, label)
            VALUES (?, ?, ?)
            """,
            (str(guild_id), position, label),
        )
        await self._db.commit()

    async def remove_position(self, guild_id: int, position: int) -> bool:
        await self._ensure_table()
        cursor = await self._db.execute(
            """
            DELETE FROM activity_pool
            WHERE guild_id = ? AND position = ?
            """,
            (str(guild_id), position),
        )
        await self._db.commit()
        if cursor.rowcount == 0:
            return False
        await self._db.execute(
            """
            UPDATE activity_pool SET position = position - 1
            WHERE guild_id = ? AND position > ?
            """,
            (str(guild_id), position),
        )
        await self._db.commit()
        return True

    async def clear(self, guild_id: int) -> None:
        await self._ensure_table()
        await self._db.execute(
            "DELETE FROM activity_pool WHERE guild_id = ?",
            (str(guild_id),),
        )
        await self._db.commit()

    async def update_label(self, guild_id: int, position: int, label: str) -> bool:
        await self._ensure_table()
        cursor = await self._db.execute(
            """
            UPDATE activity_pool
            SET label = ?
            WHERE guild_id = ? AND position = ?
            """,
            (label, str(guild_id), position),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def set_order(self, guild_id: int, labels: list[str]) -> None:
        await self._ensure_table()
        await self._db.execute(
            "DELETE FROM activity_pool WHERE guild_id = ?",
            (str(guild_id),),
        )
        await self._db.executemany(
            """
            INSERT INTO activity_pool (guild_id, position, label)
            VALUES (?, ?, ?)
            """,
            [(str(guild_id), i, label) for i, label in enumerate(labels, start=1)],
        )
        await self._db.commit()
