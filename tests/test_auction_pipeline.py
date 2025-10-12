from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import List

import pytest

from companion_collect.pipelines.auction_pipeline import AuctionPipeline, AuctionRecord


class StubSink:
    def __init__(self) -> None:
        self.records: List[AuctionRecord] = []

    async def persist(self, records: List[AuctionRecord]) -> None:
        self.records.extend(records)

    async def publish(self, records: List[AuctionRecord]) -> None:
        self.records.extend(records)


@pytest.mark.asyncio()
async def test_pipeline_persists_records() -> None:
    class FakeCollector:
        def __init__(self) -> None:
            self._stopped = asyncio.Event()

        @asynccontextmanager
        async def lifecycle(self):
            yield self

        async def stream(self):
            yield {
                "responseInfo": {
                    "value": {
                        "details": [
                            {
                                "tradeId": 1,
                                "buyNowPrice": 10,
                                "currentBid": 5,
                                "startingBid": 4,
                                "expires": 60,
                                "itemData": {"platform": "ps"},
                            }
                        ]
                    }
                }
            }
            self._stopped.set()

        def stop(self) -> None:
            self._stopped.set()

    collector = FakeCollector()
    storage = StubSink()
    publisher = StubSink()

    pipeline = AuctionPipeline(
        collector=collector,  # type: ignore[arg-type]
        storage_sinks=[storage],
        publish_sinks=[publisher],
    )

    await pipeline.run(max_batches=1)

    assert len(storage.records) == 1
    assert len(publisher.records) == 1
    record = storage.records[0]
    assert record.trade_id == 1
    assert record.buy_now_price == 10
