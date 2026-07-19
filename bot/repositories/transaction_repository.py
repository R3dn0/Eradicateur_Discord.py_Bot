import aiosqlite
from dataclasses import dataclass

from bot.repositories.base_repository import BaseRepository


@dataclass
class Transaction:
    id: int
    discord_id: int
    amount: int
    reason: str
    payout_id: int | None
    created_by: int
    created_at: str


class TransactionRepository(BaseRepository):
    _TABLE_NAME = "transactions"
    _COLUMNS: dict[str, str] = {}

    def __init__(self, db: aiosqlite.Connection) -> None:
        super().__init__(db)

    async def _ensure_table(self) -> None:
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                payout_id INTEGER,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
                    DEFAULT (datetime('now'))
            )
        """)
        await self._run_migrations()
        await self._db.commit()

    async def add_transaction(
        self,
        discord_id: int,
        amount: int,
        reason: str,
        created_by: int,
        payout_id: int | None = None,
    ) -> int:
        await self._ensure_table()
        cursor = await self._db.execute(
            """
            INSERT INTO transactions
                (discord_id, amount, reason, payout_id, created_by)
            VALUES (?, ?, ?, ?, ?)
        """,
            (discord_id, amount, reason, payout_id, created_by),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_balance(self, discord_id: int) -> int:
        await self._ensure_table()
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE discord_id = ?",
            (discord_id,),
        )
        row = await cursor.fetchone()
        return int(row[0])

    async def list_balances(self) -> list[tuple[int, int]]:
        await self._ensure_table()
        cursor = await self._db.execute("""
            SELECT discord_id, SUM(amount) AS balance
            FROM transactions
            GROUP BY discord_id
            HAVING SUM(amount) != 0
            ORDER BY balance DESC
        """)
        rows = await cursor.fetchall()
        return [(row["discord_id"], int(row["balance"])) for row in rows]

    async def list_transactions_for_payout(self, payout_id: int) -> list[Transaction]:
        await self._ensure_table()
        cursor = await self._db.execute(
            """
            SELECT id, discord_id, amount, reason, payout_id,
                   created_by, created_at
            FROM transactions
            WHERE payout_id = ?
            ORDER BY created_at ASC, id ASC
        """,
            (payout_id,),
        )
        rows = await cursor.fetchall()
        return [
            Transaction(
                id=row["id"],
                discord_id=row["discord_id"],
                amount=row["amount"],
                reason=row["reason"],
                payout_id=row["payout_id"],
                created_by=row["created_by"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def list_transactions(self, discord_id: int) -> list[Transaction]:
        await self._ensure_table()
        cursor = await self._db.execute(
            """
            SELECT id, discord_id, amount, reason, payout_id,
                   created_by, created_at
            FROM transactions
            WHERE discord_id = ?
            ORDER BY created_at DESC, id DESC
        """,
            (discord_id,),
        )
        rows = await cursor.fetchall()
        return [
            Transaction(
                id=row["id"],
                discord_id=row["discord_id"],
                amount=row["amount"],
                reason=row["reason"],
                payout_id=row["payout_id"],
                created_by=row["created_by"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
