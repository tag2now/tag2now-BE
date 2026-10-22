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
    cache_ttl_rooms_all: int = 10
    cache_ttl_community: int = 30
    cache_ttl_activity: int = 300
    cache_ttl_player_hours: int = 300
    # A player's TTT2 save on their profile; an admin's edit clears it sooner.
    cache_ttl_player_save: int = 600
    # The current-rank leaderboard; save-admin rereads only saves the game wrote since.
    cache_ttl_current_rank_leaderboard: int = 300
    # One channel's live status; a failed check is cached as offline for as long.
    cache_ttl_live_streams: int = 30
    # Every registered channel; a registration change clears it sooner.
    cache_ttl_stream_channels: int = 300
    matchmaking_ttl: int = 60
    match_history_collection_interval_seconds: int = 30
    # RPCN usernames (= npid) kept off every ranking, e.g. test accounts.
    ranking_excluded_npids: list[str] = []

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

    # Account login. rpcn-narco's API server verifies the password; this service
    # only signs the result. Base URL with no path, e.g. http://127.0.0.1:31315.
    # Login answers 502 while any of the three is empty.
    rpcn_api_server_url: str = ""
    # SecretStr: app.py logs the settings at startup, and these must not be in it.
    rpcn_api_server_key: SecretStr = SecretStr("")
    rpcn_api_server_timeout_seconds: float = 5.0
    # tag2now-save-admin's server; empty leaves the save admin routes answering 502.
    save_admin_url: str = ""
    save_admin_key: SecretStr = SecretStr("")
    # A write waits on RPCN twice (admin check, online check) before it lands.
    save_admin_timeout_seconds: float = 20.0
    # HS256 key for access tokens; at least 32 bytes. Rotating it signs everyone out.
    jwt_secret: SecretStr = SecretStr("")
    jwt_ttl_seconds: int = 7 * 24 * 3600

    # Chzzk's web API, not the official Open API, which cannot look up one channel.
    chzzk_api_url: str = "https://api.chzzk.naver.com"
    chzzk_timeout_seconds: float = 3.0

    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=(_ENV_DIR / ".env", _ENV_DIR / f".env.{profile}"),
        env_file_encoding="utf-8",
    )

    def is_ranking_excluded(self, npid: str) -> bool:
        # RPCN usernames are unique case-insensitively, so the list is too.
        return npid.casefold() in {n.casefold() for n in self.ranking_excluded_npids}


@lru_cache
def get_settings() -> Settings:
    # noinspection PyArgumentList
    return Settings()
