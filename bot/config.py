import os
from dataclasses import dataclass
from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_id: int | None
    database_path: str

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise RuntimeError("DISCORD_TOKEN missing from .env")

        guild_id_raw = os.getenv("GUILD_ID")
        return cls(
            discord_token=token,
            guild_id=int(guild_id_raw) if guild_id_raw else None,
            database_path=os.getenv("DATABASE_PATH", "data/eradicateur.db"),
        )
