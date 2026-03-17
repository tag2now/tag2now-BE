import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_DIR = Path(__file__).resolve().parent
profile = os.getenv('FAST_API_PROFILE', 'local')

class Settings(BaseSettings):
    rpcn_user: str
    rpcn_password: str
    rpcn_token: str
    rpcn_host: str
    rpcn_port: int

    redis_url: str = "redis://localhost:6379"
    cache_ttl_servers: int = 86400
    cache_ttl_leaderboard: int = 300
    cache_ttl_rooms: int = 60
    cache_ttl_rooms_all: int = 60

    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=(_ENV_DIR / ".env", _ENV_DIR / f".env.{profile}"),
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
