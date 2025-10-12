"""Entry-point for running the auction ingestion pipeline."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

from companion_collect.collectors.auctions import AuctionCollector
from companion_collect.config import get_settings
from companion_collect.logging import configure_logging
from companion_collect.pipelines.auction_pipeline import AuctionPipeline
from companion_collect.storage import PostgresAuctionStore, RedisAuctionCache


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    collector = AuctionCollector(settings=settings)
    redis_cache = RedisAuctionCache(settings=settings)
    postgres_store = PostgresAuctionStore(settings=settings)

    pipeline = AuctionPipeline(
        collector=collector,
        storage_sinks=[postgres_store],
        publish_sinks=[redis_cache],
    )

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(_managed(redis_cache))
        await stack.enter_async_context(_managed(postgres_store))
        await stack.enter_async_context(_managed_collector(collector))
        await pipeline.run()


class _managed:
    def __init__(self, resource) -> None:
        self.resource = resource

    async def __aenter__(self):
        if hasattr(self.resource, "open"):
            await self.resource.open()
        return self.resource

    async def __aexit__(self, exc_type, exc, tb):
        close = getattr(self.resource, "close", None)
        if close:
            await close()


class _managed_collector:
    def __init__(self, collector: AuctionCollector) -> None:
        self.collector = collector

    async def __aenter__(self) -> AuctionCollector:
        return self.collector

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.collector.stop()


if __name__ == "__main__":
    asyncio.run(main())
