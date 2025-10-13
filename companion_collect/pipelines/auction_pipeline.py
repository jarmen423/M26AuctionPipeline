"""Auction ingestion pipeline orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence, Optional

from ea_constants import AuctionDetail, AuctionSearchResponse

from companion_collect.collectors.auctions import AuctionCollector
from companion_collect.logging import get_logger

from dataclasses import asdict
import json
from pathlib import Path


@dataclass(slots=True)
class AuctionRecord:
    """Normalized auction output."""

    trade_id: int
    buy_now_price: int
    current_price: int
    starting_price: int
    expires: int
    seller_id: int | None
    platform: str | None
    item: dict[str, Any]
    raw: dict[str, Any]


def normalize_auction(raw: AuctionDetail) -> AuctionRecord:
    """Normalize Companion App auction responses into a stable schema."""
    try:
        trade_identifier = raw.get("tradeId") or raw.get("auctionId")
        if trade_identifier is None:
            raise KeyError("tradeId/auctionId")

        buy_now_source = raw.get("buyNowPrice")
        if buy_now_source is None:
            buy_now_source = raw.get("buyoutPrice", 0)

        current_price = raw.get("currentBid", raw.get("currentPrice", 0))
        starting_price = raw.get("startingBid", raw.get("nextBid", current_price))
        expires = raw.get("expires", raw.get("secondsRemaining", 0))

        item_data = raw.get("itemData") or raw.get("card", {})
        platform: str | None = None
        if isinstance(item_data, dict):
            platform = item_data.get("platform") or item_data.get("cardAssetType")
        return AuctionRecord(
            trade_id=int(trade_identifier),
            buy_now_price=int(buy_now_source),
            current_price=int(current_price),
            starting_price=int(starting_price),
            expires=int(expires),
            seller_id=(int(raw["sellerId"]) if "sellerId" in raw else None),
            platform=platform,
            item=item_data if isinstance(item_data, dict) else {},
            raw=raw,
        )
    except KeyError as e:
        raise KeyError(f"Missing mandatory auction field: {e}")


class AuctionPipeline:
    """Glue collector output into storage and broadcaster sinks."""

    def __init__(
        self,
        *,
        collector: AuctionCollector,
        storage_sinks: Sequence["AuctionStorage"] | None = None,
        publish_sinks: Sequence["AuctionPublisher"] | None = None,
    normalizer: Callable[[AuctionDetail], AuctionRecord] = normalize_auction,
    ) -> None:
        self.collector = collector
        self.storage_sinks = tuple(storage_sinks or ())
        self.publish_sinks = tuple(publish_sinks or ())
        self.normalizer = normalizer
        self._logger = get_logger(__name__).bind(component="auction_pipeline")
        self._running = False

    async def _persist(self, records: Iterable[AuctionRecord]) -> None:
        records_list = list(records)
        if not records_list:
            return

        tasks = [sink.persist(records_list) for sink in self.storage_sinks]
        tasks.extend(sink.publish(records_list) for sink in self.publish_sinks)
        if tasks:
            await asyncio.gather(*tasks)

    async def process_payload(self, payload: AuctionSearchResponse) -> None:
        """Process a raw payload from the collector."""

        auction_info = (
            payload.get("responseInfo", {})
            .get("value", {})
            .get("details", [])
        )
        normalized: list[AuctionRecord] = []
        for raw in auction_info:
            try:
                normalized.append(self.normalizer(raw))
            except Exception as exc:  # pragma: no cover - logging only branch
                self._logger.warning(
                    "normalize_failed",
                    error=str(exc),
                    raw=raw,
                )
        if not normalized:
            return

        self._logger.info("auctions_processed", count=len(normalized))
        await self._persist(normalized)

    async def run(self, *, max_batches: int | None = None) -> None:
        """Run the pipeline."""

        self._running = True
        batches = 0
        try:
            async with self.collector.lifecycle():
                async for payload in self.collector.stream():
                    await self.process_payload(payload)
                    batches += 1
                    if max_batches is not None and batches >= max_batches:
                        break
        finally:
            self.collector.stop()
            self._running = False

    def stop(self) -> None:
        self.collector.stop()

    async def single_run(self, filters: Optional[list] = None) -> list[AuctionRecord]:
        """Run a single auction fetch and process for integration testing."""
        async with self.collector.lifecycle():
            raw_payload = await self.collector.fetch_auctions(filters=filters)

            auction_info = (
                raw_payload.get("responseInfo", {})
                .get("value", {})
                .get("details", [])
            )
            normalized: list[AuctionRecord] = []
            for raw in auction_info:
                try:
                    normalized.append(self.normalizer(raw))
                except Exception as exc:
                    self._logger.warning(
                        "normalize_failed",
                        error=str(exc),
                        raw=raw,
                    )

            if normalized:
                self._logger.info("auctions_processed_single", count=len(normalized))

                # Save processed data for test
                save_path = Path("auction_data/integrated_test.json")
                save_path.parent.mkdir(exist_ok=True, parents=True)
                with open(save_path, "w") as f:
                    json.dump([asdict(record) for record in normalized], f, indent=2)
                self._logger.info("saved_test_output", path=save_path, count=len(normalized))

            return normalized


class AuctionStorage:
    """Protocol for durable auction storage."""

    async def persist(self, records: Sequence[AuctionRecord]) -> None:  # pragma: no cover - interface only
        raise NotImplementedError


class AuctionPublisher:
    """Protocol for pub/sub style fan-out."""

    async def publish(self, records: Sequence[AuctionRecord]) -> None:  # pragma: no cover - interface only
        raise NotImplementedError
