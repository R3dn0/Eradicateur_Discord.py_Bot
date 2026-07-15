import os
from dataclasses import dataclass
from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_id: list[int]
    database_path: str

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise RuntimeError("DISCORD_TOKEN missing from .env")

        guild_id_raw = os.getenv("GUILD_ID", "")
        guild_ids = [int(gid.strip()) for gid in guild_id_raw.split(",") if gid.strip()]
        return cls(
            discord_token=token,
            guild_id=guild_ids,
            database_path=os.getenv("DATABASE_PATH", "data/eradicateur.db"),
        )
