"""Redis-backed recent auction cache."""

from __future__ import annotations

import json

from redis import asyncio as aioredis

from companion_collect.config import Settings, get_settings
from companion_collect.logging import get_logger
from companion_collect.pipelines.auction_pipeline import AuctionPublisher, AuctionRecord


class RedisAuctionCache(AuctionPublisher):
    """Push normalized auctions into a Redis list for fast fan-out."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: aioredis.Redis | None = None
        self._logger = get_logger(__name__).bind(component="redis_cache")

    async def open(self) -> None:
        if self._client is None:
            self._client = aioredis.from_url(self.settings.redis_url, encoding="utf-8", decode_responses=True)
            self._logger.info("redis_connected", url=self.settings.redis_url)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._logger.info("redis_closed")

    async def publish(self, records: list[AuctionRecord]) -> None:
        if not records:
            return
        if self._client is None:
            await self.open()

        key = f"{self.settings.redis_prefix}{self.settings.redis_recent_key}"
        payloads = [json.dumps(record.raw) for record in records]
        assert self._client is not None
        await self._client.lpush(key, *payloads)
        await self._client.ltrim(key, 0, self.settings.redis_recent_limit - 1)
        self._logger.info("redis_published", count=len(records))
