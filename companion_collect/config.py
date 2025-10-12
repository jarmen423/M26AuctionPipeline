"""Application configuration for the Companion ingest service."""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven runtime settings."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="COMPANION_", extra="allow")

    # General
    environment: str = "development"
    log_level: str = "INFO"

    # Collector configuration
    ws_url: str | None = None
    poll_interval_seconds: int = 10
    max_concurrent_collectors: int = 4
    collector_request_timeout_seconds: int = 10
    collector_backoff_seconds: int = 5
    search_page_size: int = 21
    request_template_path: str = "request_templates/mobile_search_auctions.json"
    request_context_overrides: dict[str, str] = {}

    # Auth / Companion App credentials
    auth_email: str | None = None
    auth_password: str | None = None
    device_id: str | None = None

    # M26 Auction House settings
    m26_blaze_id: str = "madden-2026-ps5"
    m26_command_id: int = 9153
    m26_component_id: int = 2050
    m26_command_name: str = "Mobile_SearchAuctions"
    tokens_path: str = "tokens.json"
    session_context_path: str = "auction_data/current_session_context.json"

    # Storage
    redis_url: str = "redis://localhost:6379/0"
    redis_prefix: str = "companion:"
    redis_recent_key: str = "recent:auctions"
    redis_recent_limit: int = 400
    postgres_dsn: str = "postgresql+psycopg://companion:companion@localhost:5432/companion"
    postgres_table: str = "auction_events"
    postgres_batch_size: int = 50

    # API / broadcaster
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    allowed_origins: List[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
