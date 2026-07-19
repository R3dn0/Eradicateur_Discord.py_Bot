import aiosqlite


class BaseRepository:
    _TABLE_NAME: str = ""
    _COLUMNS: dict[str, str] = {}

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def _run_migrations(self) -> None:
        if not self._TABLE_NAME or not self._COLUMNS:
            return
        cursor = await self._db.execute(f"PRAGMA table_info({self._TABLE_NAME})")
        existing = {row["name"] for row in await cursor.fetchall()}
        for col_name, col_type in self._COLUMNS.items():
            if col_name not in existing:
                await self._db.execute(
                    f"ALTER TABLE {self._TABLE_NAME} ADD COLUMN {col_name} {col_type}"
                )
