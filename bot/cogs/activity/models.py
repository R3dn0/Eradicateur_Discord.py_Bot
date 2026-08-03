from dataclasses import dataclass, field


@dataclass
class Slot:
    category: str
    description: str = ""
    players: list[int] = field(default_factory=list)


@dataclass
class Activity:
    title: str
    description: str = ""
    date: str = ""
    location: str = ""
    stuff: str = ""
    slots: list[Slot] = field(default_factory=list)
