import re
from datetime import datetime, timedelta, timezone

_TIMESTAMP_RE = re.compile(r"<t:(\d+)[^>]*>")
_FULL_PATTERNS = ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m %H:%M", "%d/%m/%y %H:%M")
_DATE_PATTERNS = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m")


def to_discord_timestamp(sqlite_datetime_str: str, style: str = "f") -> str:
    dt = datetime.strptime(sqlite_datetime_str, "%Y-%m-%d %H:%M:%S")
    dt = dt.replace(tzinfo=timezone.utc)
    return f"<t:{int(dt.timestamp())}:{style}>"


def parse_user_time(text: str) -> str:
    """Best-effort conversion of a user-entered time into a Discord timestamp.

    Returns ``<t:<epoch>:F>`` when the input can be parsed, otherwise the raw
    text unchanged. Naive inputs are interpreted in the local server timezone.
    """
    raw = text.strip()
    if not raw:
        return text

    match = _TIMESTAMP_RE.fullmatch(raw)
    if match is not None:
        return f"<t:{int(match.group(1))}:F>"

    normalized = raw.replace("–", "-").replace("—", "-")
    normalized = re.sub(r"[àa]\s+", "", normalized, flags=re.IGNORECASE).strip()
    normalized = re.sub(r"h", ":", normalized, flags=re.IGNORECASE)

    now = datetime.now()
    parsed = _parse_with(*_FULL_PATTERNS, value=normalized)
    if parsed is None:
        parsed = _parse_with(*_DATE_PATTERNS, value=normalized)
    if parsed is not None:
        if parsed.year == 1900:
            parsed = parsed.replace(year=now.year)
        return f"<t:{int(parsed.timestamp())}:F>"

    try:
        parsed = datetime.strptime(normalized, "%H:%M")
    except ValueError:
        return text
    parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
    if parsed <= now:
        parsed += timedelta(days=1)
    return f"<t:{int(parsed.timestamp())}:F>"


def _parse_with(*formats: str, value: str) -> datetime | None:
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
