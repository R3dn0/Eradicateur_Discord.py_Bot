from dataclasses import dataclass, field
import os
from dotenv import load_dotenv

from bot.dev_logs import parse_log_level


load_dotenv()


@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_id: list[int]
    data_dir: str
    log_level: int
    dashboard_enabled: bool = False
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 38291
    dashboard_token: str | None = None
    discord_client_id: str | None = None
    discord_client_secret: str | None = None
    discord_redirect_uri: str | None = None
    dashboard_allowed_users: list[int] = field(default_factory=list)

    @property
    def session_secret(self) -> str:
        return self.dashboard_token or self.discord_client_secret or self.discord_token

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise RuntimeError("DISCORD_TOKEN missing from .env")

        guild_id_raw = os.getenv("GUILD_ID", "")
        guild_ids = [int(gid.strip()) for gid in guild_id_raw.split(",") if gid.strip()]
        
        dashboard_enabled_raw = os.getenv("DASHBOARD_ENABLED", "false").strip().lower()
        dashboard_enabled = dashboard_enabled_raw in ("1", "true", "yes", "on")
        dashboard_host = os.getenv("DASHBOARD_HOST", "0.0.0.0").strip()
        dashboard_port = int(os.getenv("DASHBOARD_PORT", "38291").strip())
        dashboard_token = os.getenv("DASHBOARD_TOKEN", "").strip() or None

        discord_client_id = os.getenv("DISCORD_CLIENT_ID", "").strip() or None
        discord_client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip() or None
        discord_redirect_uri = os.getenv("DISCORD_REDIRECT_URI", "").strip() or None

        allowed_users_raw = os.getenv("DASHBOARD_ALLOWED_USERS", "")
        dashboard_allowed_users = [
            int(uid.strip()) for uid in allowed_users_raw.split(",") if uid.strip() and uid.strip().isdigit()
        ]

        return cls(
            discord_token=token,
            guild_id=guild_ids,
            data_dir=os.getenv("DATA_DIR", "data"),
            log_level=parse_log_level(os.getenv("LOG_LEVEL")),
            dashboard_enabled=dashboard_enabled,
            dashboard_host=dashboard_host,
            dashboard_port=dashboard_port,
            dashboard_token=dashboard_token,
            discord_client_id=discord_client_id,
            discord_client_secret=discord_client_secret,
            discord_redirect_uri=discord_redirect_uri,
            dashboard_allowed_users=dashboard_allowed_users,
        )
