import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_DIR = Path(__file__).resolve().parent.parent.parent.joinpath("env")
profile = os.getenv('FAST_API_PROFILE', 'local')

class Settings(BaseSettings):
    profile: str = profile

    rpcn_user: str
    rpcn_password: str
    rpcn_token: str
    rpcn_host: str = "rpcn.mynarco.xyz"
    rpcn_port: int = 31313

    redis_url: str
    cache_ttl_servers: int = 3600
    cache_ttl_leaderboard: int = 60
    cache_ttl_rooms: int = 10
    cache_ttl_rooms_all: int = 10
    cache_ttl_community: int = 30
    matchmaking_ttl: int = 60

    db_type: str = "postgresql"
    db_url: str = "postgresql://localhost:5432/tag2now-community"

    dynamodb_region: str = "ap-northeast-2"
    dynamodb_table_name: str = "tag2now-community"
    dynamodb_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    rpcn_metric_enable: bool = False

    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=(_ENV_DIR / ".env", _ENV_DIR / f".env.{profile}"),
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    # noinspection PyArgumentList
    return Settings()
