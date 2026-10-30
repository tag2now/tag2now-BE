"""Event DTOs: the public board and one player's progress."""

from datetime import datetime

from pydantic import BaseModel


class EventRankOut(BaseModel):
    rank: int
    name: str
    tier: str


class EventCharOut(BaseModel):
    id: int
    character: str


class EventAchieverOut(BaseModel):
    place: int
    username: str
    # Ranks the best character climbed from where the rules started it.
    gain: int
    # Whether that was the main's condition rather than a sub's.
    main: bool
    char: EventCharOut
    from_rank: EventRankOut
    to_rank: EventRankOut
    # The organiser's call, not the rules': under two weeks old, or never above 3rd dan.
    new_player: bool
    number_only: bool


class EventBoardOut(BaseModel):
    start_at: datetime
    # Null until the organiser has set it.
    end_at: datetime | None
    ended: bool
    capacity: int
    achievers: list[EventAchieverOut]


class EventSlotOut(BaseModel):
    char: EventCharOut
    main: bool
    start: EventRankOut
    target: EventRankOut
    rank: EventRankOut
    achieved: bool


class EventPlayerOut(BaseModel):
    username: str
    top_rank: EventRankOut
    best_rank: EventRankOut
    # Ranks the main must climb.
    main_steps: int
    # Ranks a sub must climb, and the rank it counts from at the lowest.
    sub_steps: int
    sub_floor: EventRankOut
    achieved: bool
    # On the board; null until a condition is met.
    place: int | None
    new_player: bool
    number_only: bool
    # The main and every character played since the event began.
    slots: list[EventSlotOut]
