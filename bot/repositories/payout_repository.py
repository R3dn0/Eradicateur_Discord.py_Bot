import aiosqlite
from dataclasses import dataclass

from bot.repositories.base_repository import BaseRepository
from bot.repositories.transaction_repository import TransactionRepository


@dataclass
class Payout:
    id: int
    bag_silvers: int
    item_market_value: int
    activity_cost: int
    tax_market: float
    tax_guild: float
    tax_transport: float
    participant_count: int
    amount_per_player: int
    buyback_value: int
    created_by: int
    created_at: str
    voided: bool = False
    voided_by: int | None = None
    voided_at: str | None = None


class PayoutRepository(BaseRepository):
    _TABLE_NAME = "payouts"
    _COLUMNS: dict[str, str] = {
        "voided": "INTEGER NOT NULL DEFAULT 0",
        "voided_by": "INTEGER",
        "voided_at": "TEXT",
    }

    def __init__(
        self,
        db: aiosqlite.Connection,
        transaction_repo: TransactionRepository,
    ) -> None:
        super().__init__(db)
        self._transaction_repo = transaction_repo

    async def _ensure_tables(self) -> None:
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bag_silvers INTEGER NOT NULL,
                item_market_value INTEGER NOT NULL,
                activity_cost INTEGER NOT NULL,
                tax_market REAL NOT NULL,
                tax_guild REAL NOT NULL,
                tax_transport REAL NOT NULL,
                 participant_count INTEGER NOT NULL,
                 amount_per_player INTEGER NOT NULL,
                 buyback_value INTEGER NOT NULL,
                 created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
                    DEFAULT (datetime('now')),
                 voided INTEGER NOT NULL DEFAULT 0,
                 voided_by INTEGER,
                 voided_at TEXT
            )
        """)
        await self._transaction_repo._ensure_table()
        await self._run_migrations()
        await self._db.commit()

    async def create_payout(
        self,
        bag_silvers: int,
        item_market_value: int,
        activity_cost: int,
        tax_market: float,
        tax_guild: float,
        tax_transport: float,
        amount_per_player: int,
        buyback_value: int,
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

    async def get_payout(self, payout_id: int) -> Payout | None:
        await self._ensure_tables()
        cursor = await self._db.execute("SELECT * FROM payouts WHERE id = ?", (payout_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return Payout(
            id=row["id"],
            bag_silvers=row["bag_silvers"],
            item_market_value=row["item_market_value"],
            activity_cost=row["activity_cost"],
            tax_market=row["tax_market"],
            tax_guild=row["tax_guild"],
            tax_transport=row["tax_transport"],
            participant_count=row["participant_count"],
            amount_per_player=row["amount_per_player"],
            buyback_value=row["buyback_value"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            voided=bool(row["voided"]),
            voided_by=row["voided_by"],
            voided_at=row["voided_at"],
        )

    async def void_payout(self, payout_id: int, voided_by: int) -> None:
        await self._ensure_tables()
        try:
            await self._db.execute("BEGIN IMMEDIATE")

            cursor = await self._db.execute(
                "SELECT voided, participant_count FROM payouts WHERE id = ?", (payout_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Payout #{payout_id} not found")
            if row["voided"]:
                raise ValueError(f"Payout #{payout_id} already voided")

            await self._db.execute(
                "UPDATE payouts SET voided = 1, voided_by = ?, voided_at = datetime('now') WHERE id = ?",
                (voided_by, payout_id),
            )

            cursor = await self._db.execute(
                "SELECT discord_id, amount FROM transactions WHERE payout_id = ?",
                (payout_id,),
            )
            rows = await cursor.fetchall()
            for tx_row in rows:
                await self._db.execute(
                    "INSERT INTO transactions (discord_id, amount, reason, created_by) VALUES (?, ?, ?, ?)",
                    (
                        tx_row["discord_id"],
                        -tx_row["amount"],
                        f"Void of payout #{payout_id}",
                        voided_by,
                    ),
                )

            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
