"""Application configuration for the Companion ingest service."""

from __future__ import annotations

from functools import cached_property, lru_cache
from typing import Any, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from companion_collect.madden import MaddenIdentifiers, get_identifiers


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
    use_auth_pool: bool = False

    # Auth / Companion App credentials
    auth_email: str | None = None
    auth_password: str | None = None
    device_id: str | None = None

    # Madden cycle configuration
    madden_year: int = Field(default=2026, description="Four digit Madden cycle year")
    madden_platform: str = Field(default="xbsx", description="Primary platform slug")

    # M26 Auction House settings
    m26_blaze_id: str | None = None
    m26_command_id: int = 9153
    m26_component_id: int = 2050
    m26_command_name: str = "Mobile_SearchAuctions"
    m26_product_name: str | None = None
    wal_madden_year: int | None = None
    wal_blaze_id: str | None = None
    wal_product_name: str | None = None
    tokens_path: str = "tokens.json"
    session_context_path: str = "auction_data/current_session_context.json"
    auth_pool_path: str = "research/captures/auth_pool.json"

    # Storage
    redis_url: str = "redis://localhost:6379/0"
    redis_prefix: str = "companion:"
    redis_recent_key: str = "recent:auctions"
    redis_recent_limit: int = 400
    postgres_dsn: str = "postgresql+psycopg://companion:companion@localhost:5432/companion"
    postgres_table: str = "auction_events"
    postgres_batch_size: int = 50

    # UTAS (Ultimate Team Automation Service)
    utas_base_url: str = Field(default="https://utas.mob.v2.madden.ea.com", description="UTAS host")
    utas_route: str = Field(default="m26", description="UTAS year route segment, e.g., m26, m25")

    # Madden 26 service API
    m26_service_base_url: str = Field(
        default="https://madden26.service.easports.com",
        description="Base URL for the Madden 26 service endpoints",
    )
    m26_service_timeout_seconds: float = Field(
        default=10.0,
        description="HTTP timeout for Madden 26 service requests",
    )
    m26_service_user_agent: str = Field(
        default="MutDashboard-Service/1.0",
        description="User-Agent header for Madden 26 service requests",
    )

    # API / broadcaster
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    allowed_origins: List[str] = ["*"]


    def model_post_init(self, __context: Any) -> None:
        identifiers = get_identifiers(self.madden_year, self.madden_platform)
        if self.m26_blaze_id is None:
            self.m26_blaze_id = identifiers.blaze_header
        if self.m26_product_name is None:
            self.m26_product_name = identifiers.product_name

        wal_identifiers = get_identifiers(self.wal_madden_year or self.madden_year, self.madden_platform)
        if self.wal_blaze_id is None:
            self.wal_blaze_id = wal_identifiers.blaze_header
        if self.wal_product_name is None:
            self.wal_product_name = wal_identifiers.product_name

    @cached_property
    def resolved_wal_identifiers(self) -> tuple[str, str]:
        """Return the WAL X-BLAZE-ID and productName using snallabot-matching defaults.

        Prefers explicit overrides (wal_*). Falls back to computed identifiers for
        (wal_madden_year or madden_year, madden_platform).
        """
        blaze = self.wal_blaze_id
        product = self.wal_product_name
        if blaze and product:
            return blaze, product
        ident = get_identifiers(self.wal_madden_year or self.madden_year, self.madden_platform)
        return (blaze or ident.blaze_header, product or ident.product_name)

    @cached_property
    def madden_identifiers(self) -> MaddenIdentifiers:
        return get_identifiers(self.madden_year, self.madden_platform)


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
