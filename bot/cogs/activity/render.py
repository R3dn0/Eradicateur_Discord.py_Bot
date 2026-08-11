import re
from dataclasses import replace

import discord

from bot.cogs.activity.models import Activity, Slot

MENTION_RE = re.compile(r"<@!?(\d+)>")
SLOT_SPLIT_RE = re.compile(r"^\s*(.*?)\s*-\s*(.*)$", re.DOTALL)

DATE_SYMBOL = "\U0001f570\ufe0f"
LOCATION_SYMBOL = "\U0001f4cd"
STUFF_SYMBOL = "\U0001f392"
CREATOR_SYMBOL = "\U0001f451"

FILL_CATEGORY = "❓ Fill"
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
    fill_index = next(
        (i for i, slot in enumerate(slots) if "fill" in slot.category.strip().lower().split()),
        None,
    )
    if fill_index is None:
        slots.append(Slot(category=FILL_CATEGORY))
    elif fill_index != len(slots) - 1:
        slots.append(slots.pop(fill_index))
    return slots


def is_activity_embed(embed: discord.Embed) -> bool:
    for field in embed.fields:
        if field.name.startswith((DATE_SYMBOL, LOCATION_SYMBOL, STUFF_SYMBOL)):
            return True
        if MENTION_RE.search(field.value):
            return True
        for line in field.value.splitlines():
            if SLOT_SPLIT_RE.match(line.strip()):
                return True
    return False


def render_embed(activity: Activity, labels: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(
        title=activity.title or None,
        description=activity.description or None,
        color=0xF1C40F,
    )
    if activity.date:
        embed.add_field(
            name=f"{DATE_SYMBOL} {labels['date']}", value=activity.date, inline=False
        )
    if activity.location:
        embed.add_field(
            name=f"{LOCATION_SYMBOL} {labels['location']}",
            value=activity.location,
            inline=False,
        )
    if activity.stuff:
        embed.add_field(
            name=f"{STUFF_SYMBOL} {labels['stuff']}", value=activity.stuff, inline=False
        )

    slot_lines = []
    for slot in activity.slots:
        left = f"{slot.category} - {slot.description}".strip()
        right = " ".join(f"<@{uid}>" for uid in slot.players)
        slot_lines.append((left, right))

    if slot_lines:
        width = max(len(left) for left, _ in slot_lines)
        roster = "\n".join(
            f"{left.ljust(width)}  {right}".rstrip() for left, right in slot_lines
        )
        embed.add_field(name=labels["slots"], value=roster, inline=False)

    if activity.creator_id:
        embed.add_field(
            name=f"{CREATOR_SYMBOL} Organisateur",
            value=f"<@{activity.creator_id}>",
            inline=False,
        )

    return embed


def parse_embed(embed: discord.Embed) -> Activity:
    date = ""
    location = ""
    stuff = ""
    creator = 0
    slots: list[Slot] = []
    for field in embed.fields:
        if field.name.startswith(DATE_SYMBOL):
            date = field.value
        elif field.name.startswith(LOCATION_SYMBOL):
            location = field.value
        elif field.name.startswith(STUFF_SYMBOL):
            stuff = field.value
        elif field.name.startswith(CREATOR_SYMBOL):
            m = MENTION_RE.search(field.value)
            if m is not None:
                creator = int(m.group(1))
        else:
            for line in field.value.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                players = [int(uid) for uid in MENTION_RE.findall(stripped)]
                description = MENTION_RE.sub("", stripped).strip()
                match = SLOT_SPLIT_RE.match(description)
                if match is not None:
                    category = match.group(1).strip()
                    description = match.group(2).strip()
                else:
                    category = field.name
                slots.append(
                    Slot(
                        category=category,
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
        creator_id=creator,
    )


def set_activity_field(activity: Activity, field_key: str, value: str) -> Activity:
    return replace(activity, **{field_key: value})
