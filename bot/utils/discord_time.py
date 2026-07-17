from datetime import datetime, timezone


def to_discord_timestamp(sqlite_datetime_str: str, style: str = "f") -> str:
    dt = datetime.strptime(sqlite_datetime_str, "%Y-%m-%d %H:%M:%S")
    dt = dt.replace(tzinfo=timezone.utc)
    return f"<t:{int(dt.timestamp())}:{style}>"
