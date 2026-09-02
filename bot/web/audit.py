import logging
from fastapi import Request

from bot.dev_logs import guild_log_context

web_logger = logging.getLogger("eradicateur_bot.web")


def log_db_action(
    request: Request,
    guild_id: int,
    action: str,
    details: str,
) -> None:
    current_user = getattr(request.state, "user", None) or {}
    actor_id = current_user.get("id", "0")
    actor_name = current_user.get("display_name", "Dashboard Admin")

    with guild_log_context(guild_id):
        web_logger.info(
            "[Dash] User: %s (ID: %s) | Action: %s | %s",
            actor_name,
            actor_id,
            action,
            details,
        )

