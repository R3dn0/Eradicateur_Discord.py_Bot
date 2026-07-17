import aiosqlite
from dataclasses import dataclass


_TRANSACTION_COLUMNS: dict[str, str] = {}


@dataclass
class Transaction:
    id: int
    discord_id: int
    amount: float
    reason: str
    payout_id: int | None
    created_by: int
    created_at: str


class TransactionRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def _ensure_table(self) -> None:
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
        cursor = await self._db.execute("PRAGMA table_info(transactions)")
        existing = {row["name"] for row in await cursor.fetchall()}
        for col_name, col_type in _TRANSACTION_COLUMNS.items():
            if col_name not in existing:
                await self._db.execute(f"ALTER TABLE transactions ADD COLUMN {col_name} {col_type}")

    async def add_transaction(
        self,
        discord_id: int,
        amount: float,
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

    async def get_balance(self, discord_id: int) -> float:
        await self._ensure_table()
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE discord_id = ?",
            (discord_id,),
        )
        row = await cursor.fetchone()
        return row[0]

    async def list_balances(self) -> list[tuple[int, float]]:
        await self._ensure_table()
        cursor = await self._db.execute("""
            SELECT discord_id, SUM(amount) AS balance
            FROM transactions
            GROUP BY discord_id
            HAVING SUM(amount) != 0
            ORDER BY balance DESC
        """)
        rows = await cursor.fetchall()
        return [(row["discord_id"], row["balance"]) for row in rows]

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
