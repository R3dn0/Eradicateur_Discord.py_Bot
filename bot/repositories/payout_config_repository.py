import aiosqlite
from dataclasses import dataclass

from bot.repositories.base_repository import BaseRepository


@dataclass
class PayoutConfig:
    tax_market: float
    tax_guild: float
    tax_transport: float
    officer_role_id: int | None
    leader_role_id: int | None
    updated_at: str
    updated_by: int | None
    pay_add_permission_level: str = "officer"
    payout_channel_id: int | None = None


_DEFAULT_MARKET = 0.02
_DEFAULT_GUILD = 0.10
_DEFAULT_TRANSPORT = 0.03


class PayoutConfigRepository(BaseRepository):
    _TABLE_NAME = "payout_config"
    _COLUMNS: dict[str, str] = {
        "updated_by": "INTEGER",
        "pay_add_permission_level": "TEXT NOT NULL DEFAULT 'officer'",
        "payout_channel_id": "INTEGER",
    }

    def __init__(self, db: aiosqlite.Connection) -> None:
        super().__init__(db)

    async def _ensure_table(self) -> None:
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS payout_config (
                id INTEGER PRIMARY KEY DEFAULT 1
                    CHECK (id = 1),
                tax_market REAL NOT NULL,
                tax_guild REAL NOT NULL,
                tax_transport REAL NOT NULL,
                officer_role_id INTEGER,
                leader_role_id INTEGER,
                updated_at TEXT NOT NULL
                    DEFAULT (datetime('now'))
            )
        """)
        await self._db.execute(
            """
            INSERT OR IGNORE INTO payout_config (id, tax_market, tax_guild, tax_transport)
            VALUES (1, ?, ?, ?)
        """,
            (_DEFAULT_MARKET, _DEFAULT_GUILD, _DEFAULT_TRANSPORT),
        )
        await self._run_migrations()
        await self._db.commit()

    async def get_config(self) -> PayoutConfig:
        await self._ensure_table()
        cursor = await self._db.execute("SELECT * FROM payout_config WHERE id = 1")
        row = await cursor.fetchone()
        assert row is not None
        payout_channel_id = row["payout_channel_id"] if "payout_channel_id" in row.keys() else None
        return PayoutConfig(
            tax_market=row["tax_market"],
            tax_guild=row["tax_guild"],
            tax_transport=row["tax_transport"],
            officer_role_id=row["officer_role_id"],
            leader_role_id=row["leader_role_id"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            pay_add_permission_level=row["pay_add_permission_level"],
            payout_channel_id=payout_channel_id,
        )

    async def update_rates(
        self, market: float, guild: float, transport: float, *, updated_by: int
    ) -> None:
        await self._ensure_table()
        await self._db.execute(
            """
            UPDATE payout_config
            SET tax_market = ?, tax_guild = ?, tax_transport = ?,
                updated_at = datetime('now'),
                updated_by = ?
            WHERE id = 1
        """,
            (market, guild, transport, updated_by),
        )
        await self._db.commit()

    async def update_roles(
        self,
        officer_role_id: int | None,
        leader_role_id: int | None,
        *,
        updated_by: int,
    ) -> None:
        await self._ensure_table()
        await self._db.execute(
            """
            UPDATE payout_config
            SET officer_role_id = ?, leader_role_id = ?,
                updated_at = datetime('now'),
                updated_by = ?
            WHERE id = 1
        """,
            (officer_role_id, leader_role_id, updated_by),
        )
        await self._db.commit()

    async def update_pay_add_permission_level(self, level: str, *, updated_by: int) -> None:
        if level not in ("officer", "leader"):
            raise ValueError(f"Invalid permission level: {level!r}")
        await self._ensure_table()
        await self._db.execute(
            """
            UPDATE payout_config
            SET pay_add_permission_level = ?,
                updated_at = datetime('now'),
                updated_by = ?
            WHERE id = 1
        """,
            (level, updated_by),
        )
        await self._db.commit()

    async def update_payout_channel(self, channel_id: int | None, *, updated_by: int) -> None:
        await self._ensure_table()
        await self._db.execute(
            """
            UPDATE payout_config
            SET payout_channel_id = ?,
                updated_at = datetime('now'),
                updated_by = ?
            WHERE id = 1
        """,
            (channel_id, updated_by),
        )
        await self._db.commit()
