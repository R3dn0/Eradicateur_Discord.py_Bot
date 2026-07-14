import aiosqlite
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GuildMember:
    discord_id: int
    albion_name: str
    role: str = "member"
