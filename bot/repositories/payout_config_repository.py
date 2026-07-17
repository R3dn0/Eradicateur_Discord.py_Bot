import aiosqlite
from dataclasses import dataclass


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


_DEFAULT_MARKET = 0.02
_DEFAULT_GUILD = 0.10
_DEFAULT_TRANSPORT = 0.03

_PAYOUT_CONFIG_COLUMNS: dict[str, str] = {
    "updated_by": "INTEGER",
    "pay_add_permission_level": "TEXT NOT NULL DEFAULT 'officer'",
}


class PayoutConfigRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

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
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        cursor = await self._db.execute("PRAGMA table_info(payout_config)")
        existing = {row["name"] for row in await cursor.fetchall()}
        for col_name, col_type in _PAYOUT_CONFIG_COLUMNS.items():
            if col_name not in existing:
                await self._db.execute(
                    f"ALTER TABLE payout_config ADD COLUMN {col_name} {col_type}"
                )

    async def get_config(self) -> PayoutConfig:
        await self._ensure_table()
        cursor = await self._db.execute("SELECT * FROM payout_config WHERE id = 1")
        row = await cursor.fetchone()
        assert row is not None
        return PayoutConfig(
            tax_market=row["tax_market"],
            tax_guild=row["tax_guild"],
            tax_transport=row["tax_transport"],
            officer_role_id=row["officer_role_id"],
            leader_role_id=row["leader_role_id"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            pay_add_permission_level=row["pay_add_permission_level"],
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
