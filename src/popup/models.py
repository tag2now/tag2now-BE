"""Popup DTOs: what is stored, and what the API returns."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


@dataclass(frozen=True)
class PopupImage:
    data: bytes
    content_type: str
    # Goes in the image's URL, so a replaced image is a new address to a browser's cache.
    hash: str


@dataclass(frozen=True)
class PopupContent:
    """Everything an admin sets on a popup, apart from its image."""

    title: str
    body: str
    allow_dismiss_forever: bool
    allow_dismiss_day: bool
    active: bool


@dataclass(frozen=True)
class Popup:
    id: int
    content: PopupContent
    image_hash: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class PopupOut(BaseModel):
    id: int
    title: str
    body: str
    # Relative to the API root; null when the popup has no image.
    image_path: str | None
    allow_dismiss_forever: bool
    allow_dismiss_day: bool


class ActivePopupsOut(BaseModel):
    popups: list[PopupOut]


class AdminPopupOut(PopupOut):
    active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class AdminPopupsOut(BaseModel):
    popups: list[AdminPopupOut]
