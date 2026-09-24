import os
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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

    redis_url: str = ""
    cache_ttl_servers: int = 3600
    cache_ttl_leaderboard: int = 300
    cache_ttl_rooms: int = 10
    cache_ttl_rooms_all: int = 10
    cache_ttl_community: int = 30
    cache_ttl_activity: int = 300
    cache_ttl_player_hours: int = 300
    matchmaking_ttl: int = 60
    match_history_collection_interval_seconds: int = 30

    # host:port only — shared.database.build_dsn() adds scheme and credentials
    db_url: str = "127.0.0.1:5432"
    db_name: str = "tag2now"
    db_user: str = "postgres"
    db_password: str = "postgres"

    #community db_type. this should be removed
    db_type: str = "postgresql"
    dynamodb_region: str = "ap-northeast-2"
    dynamodb_table_name: str = "tag2now-community"

    dynamodb_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    rpcn_metric_enable: bool = False

    # Account login. RPCN's stat server verifies the password; this service only
    # signs the result. Base URL up to and including StatServerPath, e.g.
    # http://127.0.0.1:31314/rpcn_stats. Login answers 502 while any of the three is empty.
    rpcn_stat_url: str = ""
    # SecretStr: app.py logs the settings at startup, and these must not be in it.
    rpcn_external_api_key: SecretStr = SecretStr("")
    rpcn_stat_timeout_seconds: float = 5.0
    # HS256 key for access tokens; at least 32 bytes. Rotating it signs everyone out.
    jwt_secret: SecretStr = SecretStr("")
    jwt_ttl_seconds: int = 7 * 24 * 3600

    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=(_ENV_DIR / ".env", _ENV_DIR / f".env.{profile}"),
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    # noinspection PyArgumentList
    return Settings()
