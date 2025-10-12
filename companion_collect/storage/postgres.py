"""Postgres persistence for auction records."""

from __future__ import annotations

from typing import Iterable

import asyncpg

from companion_collect.config import Settings, get_settings
from companion_collect.logging import get_logger
from companion_collect.pipelines.auction_pipeline import AuctionRecord, AuctionStorage


class PostgresAuctionStore(AuctionStorage):
    """Persist normalized auctions into Postgres."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._pool: asyncpg.Pool | None = None
        self._logger = get_logger(__name__).bind(component="postgres_store")

    async def open(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(dsn=self.settings.postgres_dsn)
            await self._ensure_table()
            self._logger.info("postgres_connected", dsn=self.settings.postgres_dsn)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self._logger.info("postgres_closed")

    async def persist(self, records: Iterable[AuctionRecord]) -> None:
        materialized = list(records)
        if not materialized:
            return

        if self._pool is None:
            await self.open()

        assert self._pool is not None
        batch_size = max(1, self.settings.postgres_batch_size)
        rows = [
            (
                record.trade_id,
                record.buy_now_price,
                record.current_price,
                record.starting_price,
                record.expires,
                record.seller_id,
                record.platform,
                record.item,
                record.raw,
            )
            for record in materialized
        ]

        async with self._pool.acquire() as connection:
            for index in range(0, len(rows), batch_size):
                chunk = rows[index : index + batch_size]
                await connection.executemany(
                    f"""
                    INSERT INTO {self.settings.postgres_table}
                    (trade_id, buy_now_price, current_price, starting_price, expires, seller_id, platform, item, raw)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (trade_id) DO UPDATE SET
                        buy_now_price = EXCLUDED.buy_now_price,
                        current_price = EXCLUDED.current_price,
                        starting_price = EXCLUDED.starting_price,
                        expires = EXCLUDED.expires,
                        seller_id = EXCLUDED.seller_id,
                        platform = EXCLUDED.platform,
                        item = EXCLUDED.item,
                        raw = EXCLUDED.raw
                    """,
                    chunk,
                )
        self._logger.info("postgres_persisted", count=len(rows))

    async def _ensure_table(self) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as connection:
            await connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.settings.postgres_table} (
                    trade_id BIGINT PRIMARY KEY,
                    buy_now_price BIGINT NOT NULL,
                    current_price BIGINT NOT NULL,
                    starting_price BIGINT NOT NULL,
                    expires INTEGER NOT NULL,
                    seller_id BIGINT,
                    platform TEXT,
                    item JSONB NOT NULL,
                    raw JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            await connection.execute(
                f"""
                CREATE OR REPLACE FUNCTION set_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            await connection.execute(
                f"""
                CREATE OR REPLACE TRIGGER {self.settings.postgres_table}_updated_at
                BEFORE UPDATE ON {self.settings.postgres_table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
                """
            )
