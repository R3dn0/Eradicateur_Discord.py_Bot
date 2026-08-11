import re
from datetime import datetime, timedelta, timezone

_TIMESTAMP_RE = re.compile(r"<t:(\d+)[^>]*>")
_FULL_PATTERNS = ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%y %H:%M")
_DATE_PATTERNS = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y")


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
    parsed = _parse_date_time(normalized, now)
    if parsed is None:
        parsed = _parse_bare_time(normalized, now)
    if parsed is None:
        return text
    return f"<t:{int(parsed.timestamp())}:F>"


def _parse_date_time(value: str, now: datetime) -> datetime | None:
    for fmt in _FULL_PATTERNS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # Yearless formats ("03/08 20:00", "03/08"): parse with the current year
    # appended so Python never falls back to ambiguous no-year parsing, and
    # roll forward by one year when the result already lies in the past.
    if " " in value:
        date_part, sep, time_part = value.partition(" ")
        if not sep or not time_part:
            return None
        try:
            parsed = datetime.strptime(date_part + f"/{now.year}", "%d/%m/%Y")
            parsed_time = datetime.strptime(time_part, "%H:%M")
        except ValueError:
            return None
        parsed = parsed.replace(hour=parsed_time.hour, minute=parsed_time.minute)
    else:
        try:
            parsed = datetime.strptime(value + f"/{now.year}", "%d/%m/%Y")
        except ValueError:
            return None
    if parsed <= now:
        parsed = parsed.replace(year=parsed.year + 1)
    return parsed


def _parse_bare_time(value: str, now: datetime) -> datetime | None:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        return None
    parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
    if parsed <= now:
        parsed += timedelta(days=1)
    return parsed
