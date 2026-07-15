import aiosqlite
from dataclasses import dataclass

from bot.repositories.transaction_repository import TransactionRepository


_PAYOUT_COLUMNS: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "bag_silvers": "REAL NOT NULL",
    "item_market_value": "REAL NOT NULL",
    "activity_cost": "REAL NOT NULL",
    "tax_market": "REAL NOT NULL",
    "tax_guild": "REAL NOT NULL",
    "tax_transport": "REAL NOT NULL",
    "participant_count": "INTEGER NOT NULL",
    "amount_per_player": "REAL NOT NULL",
    "buyback_value": "REAL NOT NULL",
    "created_by": "INTEGER NOT NULL",
    "created_at": "TEXT NOT NULL DEFAULT (datetime('now'))",
}


@dataclass
class Payout:
    id: int
    bag_silvers: float
    item_market_value: float
    activity_cost: float
    tax_market: float
    tax_guild: float
    tax_transport: float
    participant_count: int
    amount_per_player: float
    buyback_value: float
    created_by: int
    created_at: str


class PayoutRepository:
    def __init__(
        self,
        db: aiosqlite.Connection,
        transaction_repo: TransactionRepository,
    ) -> None:
        self._db = db
        self._transaction_repo = transaction_repo

    async def _ensure_tables(self) -> None:
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bag_silvers REAL NOT NULL,
                item_market_value REAL NOT NULL,
                activity_cost REAL NOT NULL,
                tax_market REAL NOT NULL,
                tax_guild REAL NOT NULL,
                tax_transport REAL NOT NULL,
                 participant_count INTEGER NOT NULL,
                 amount_per_player REAL NOT NULL,
                 buyback_value REAL NOT NULL,
                 created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
                    DEFAULT (datetime('now'))
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                reason TEXT NOT NULL,
                payout_id INTEGER,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
                    DEFAULT (datetime('now'))
            )
        """)
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        cursor = await self._db.execute("PRAGMA table_info(payouts)")
        existing = {row["name"] for row in await cursor.fetchall()}
        for col_name, col_type in _PAYOUT_COLUMNS.items():
            if col_name not in existing:
                await self._db.execute(f"ALTER TABLE payouts ADD COLUMN {col_name} {col_type}")

    async def create_payout(
        self,
        bag_silvers: float,
        item_market_value: float,
        activity_cost: float,
        tax_market: float,
        tax_guild: float,
        tax_transport: float,
        amount_per_player: float,
        buyback_value: float,
        participant_ids: list[int],
        created_by: int,
    ) -> int:
        await self._ensure_tables()

        try:
            await self._db.execute("BEGIN")

            cursor = await self._db.execute(
                """
                INSERT INTO payouts
                    (bag_silvers, item_market_value, activity_cost,
                     tax_market, tax_guild, tax_transport,
                     participant_count, amount_per_player,
                     buyback_value, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    bag_silvers,
                    item_market_value,
                    activity_cost,
                    tax_market,
                    tax_guild,
                    tax_transport,
                    len(participant_ids),
                    amount_per_player,
                    buyback_value,
                    created_by,
                ),
            )
            payout_id = cursor.lastrowid

            for discord_id in participant_ids:
                await self._db.execute(
                    """
                    INSERT INTO transactions
                        (discord_id, amount, reason, payout_id, created_by)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (discord_id, amount_per_player, "payout", payout_id, created_by),
                )

            await self._db.commit()
            return payout_id

        except BaseException:
            await self._db.rollback()
            raise
