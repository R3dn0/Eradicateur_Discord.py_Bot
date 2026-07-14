import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GuildMember:
    discord_id: int
    albion_name: str
    role: str = "member"


class MemberRepository:
    """SQLite data access for guild members."""

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    discord_id INTEGER PRIMARY KEY,
                    albion_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member'
                )
            """)

    def add(self, member: GuildMember) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO members (discord_id, albion_name, role) VALUES (?, ?, ?)",
                (member.discord_id, member.albion_name, member.role),
            )

    def get_by_discord_id(self, discord_id: int) -> GuildMember | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM members WHERE discord_id = ?", (discord_id,)
            ).fetchone()
            return GuildMember(**dict(row)) if row else None

    def list_all(self) -> list[GuildMember]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM members").fetchall()
            return [GuildMember(**dict(row)) for row in rows]
