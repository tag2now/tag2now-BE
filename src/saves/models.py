from datetime import datetime

from pydantic import BaseModel


class PlayerSaveCharOut(BaseModel):
    id: int
    character: str
    rank: int
    rank_name: str
    tier: str
    points: int
    streak: int
    wins: int
    losses: int


class PlayerSaveOut(BaseModel):
    username: str
    # When the game last wrote the save.
    saved_at: datetime
    account_rank: int
    total: int
    wins: int
    losses: int
    # The characters the player has used, by save slot.
    chars: list[PlayerSaveCharOut]
