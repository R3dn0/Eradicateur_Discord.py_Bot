import re
from dataclasses import replace

import discord

from bot.cogs.activity.models import Activity, Slot

MENTION_RE = re.compile(r"<@!?(\d+)>")
SLOT_SPLIT_RE = re.compile(r"^\s*(.*?)\s*-\s*(.*)$", re.DOTALL)
SLOT_LINE_RE = re.compile(r"^\s*(\d+)\.\s*(.*)$", re.DOTALL)

DATE_SYMBOL = "\U0001f570\ufe0f"
LOCATION_SYMBOL = "\U0001f4cd"
STUFF_SYMBOL = "\U0001f392"

FILL_CATEGORY = "FILL"
DESCRIPTION_MAX = 100


def parse_slots_text(text: str) -> list[Slot]:
    slots: list[Slot] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = SLOT_SPLIT_RE.match(line)
        if match is not None:
            category = match.group(1).strip()
            rest = match.group(2).strip()
        else:
            category = line
            rest = ""
        if not category:
            continue
        players = [int(uid) for uid in MENTION_RE.findall(rest)]
        description = MENTION_RE.sub("", rest).strip()[:DESCRIPTION_MAX]
        slots.append(Slot(category=category, description=description, players=players))
    return slots


def ensure_fill_slot(slots: list[Slot]) -> list[Slot]:
    if any(slot.category.strip().lower() == FILL_CATEGORY.lower() for slot in slots):
        return slots
    slots.append(Slot(category=FILL_CATEGORY))
    return slots


def is_activity_embed(embed: discord.Embed) -> bool:
    for field in embed.fields:
        if field.name.startswith((DATE_SYMBOL, LOCATION_SYMBOL, STUFF_SYMBOL)):
            return True
        if not field.name.strip():
            continue
        for line in field.value.splitlines():
            if SLOT_LINE_RE.match(line):
                return True
    return False


def render_embed(activity: Activity, labels: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(
        title=activity.title or None,
        description=activity.description or None,
        color=0xF1C40F,
    )
    if activity.date:
        embed.add_field(name=f"{DATE_SYMBOL} {labels['date']}", value=activity.date, inline=True)
    if activity.location:
        embed.add_field(
            name=f"{LOCATION_SYMBOL} {labels['location']}", value=activity.location, inline=True
        )
    if activity.stuff:
        embed.add_field(
            name=f"{STUFF_SYMBOL} {labels['stuff']}", value=activity.stuff, inline=False
        )

    grouped: list[tuple[str, list[Slot]]] = []
    by_category: dict[str, list[Slot]] = {}
    for slot in activity.slots:
        if slot.category not in by_category:
            by_category[slot.category] = []
            grouped.append((slot.category, by_category[slot.category]))
        by_category[slot.category].append(slot)

    index = 0
    for category, slots in grouped:
        lines = []
        for slot in slots:
            index += 1
            line = f"{index}. {slot.description}".rstrip()
            if slot.players:
                mentions = " ".join(f"<@{uid}>" for uid in slot.players)
                line = f"{line} {mentions}".rstrip()
            lines.append(line)
        embed.add_field(name=category, value="\n".join(lines), inline=False)

    return embed


def parse_embed(embed: discord.Embed) -> Activity:
    date = ""
    location = ""
    stuff = ""
    slots: list[Slot] = []
    for field in embed.fields:
        if field.name.startswith(DATE_SYMBOL):
            date = field.value
        elif field.name.startswith(LOCATION_SYMBOL):
            location = field.value
        elif field.name.startswith(STUFF_SYMBOL):
            stuff = field.value
        else:
            for line in field.value.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                players = [int(uid) for uid in MENTION_RE.findall(stripped)]
                description = MENTION_RE.sub("", stripped).strip()
                match = SLOT_LINE_RE.match(description)
                if match is not None:
                    description = match.group(2).strip()
                slots.append(
                    Slot(
                        category=field.name,
                        description=description[:DESCRIPTION_MAX],
                        players=players,
                    )
                )
    return Activity(
        title=embed.title or "",
        description=embed.description or "",
        date=date,
        location=location,
        stuff=stuff,
        slots=slots,
    )


def set_activity_field(activity: Activity, field_key: str, value: str) -> Activity:
    return replace(activity, **{field_key: value})
