"""Streaming DTOs: what the platform answers, and what the API returns."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class PlatformChannel:
    channel_id: str
    channel_name: str


@dataclass(frozen=True)
class LiveBroadcast:
    title: str
    viewer_count: int
    category: str


@dataclass(frozen=True)
class StreamChannel:
    username: str
    platform: str
    channel_id: str
    channel_name: str
    registered_at: datetime


class ChannelRequest(BaseModel):
    # A chzzk.naver.com URL or the bare channel id.
    channel: str = Field(..., min_length=1, max_length=200)


class StreamChannelOut(BaseModel):
    platform: str
    channel_id: str
    channel_name: str
    channel_url: str
    registered_at: datetime


class MyStreamChannelOut(BaseModel):
    # null when the account has no channel registered.
    channel: StreamChannelOut | None


class AdminStreamChannelOut(StreamChannelOut):
    username: str


class AdminStreamChannelsOut(BaseModel):
    channels: list[AdminStreamChannelOut]
