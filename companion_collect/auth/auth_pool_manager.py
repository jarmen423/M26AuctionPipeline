"""Auth pool manager for rotating captured messageAuthData."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class CapturedAuth:
    """A captured messageAuthData bundle."""

    auth_code: str
    auth_data: str
    auth_type: int
    source_timestamp: float


class AuthPoolManager:
    """
    Manages pool of captured messageAuthData bundles.

    Rotates through bundles to avoid reusing same auth repeatedly.
    Supports dynamic pool refresh from new captures.
    """

    def __init__(self, pool_path: Path | str):
        """
        Initialize auth pool manager.

        Args:
            pool_path: Path to auth_pool.json
        """
        self._pool_path = Path(pool_path)
        self._pool: list[CapturedAuth] = []
        self._index = 0
        self._logger = logger.bind(component="auth_pool")

        self._load_pool()

    def _load_pool(self) -> None:
        """Load auth pool from disk."""
        if not self._pool_path.exists():
            raise FileNotFoundError(f"Auth pool not found: {self._pool_path}")

        with open(self._pool_path) as f:
            data = json.load(f)

        self._pool = [
            CapturedAuth(
                auth_code=item["auth_code"],
                auth_data=item["auth_data"],
                auth_type=item["auth_type"],
                source_timestamp=item["source_timestamp"],
            )
            for item in data
        ]

        self._logger.info(
            "auth_pool_loaded",
            pool_size=len(self._pool),
            pool_path=str(self._pool_path),
        )

    def get_next_auth(self) -> CapturedAuth:
        """
        Get next auth bundle from pool.

        Rotates through pool to distribute usage evenly.

        Returns:
            CapturedAuth bundle

        Raises:
            RuntimeError: If pool is empty
        """
        if not self._pool:
            raise RuntimeError("Auth pool is empty")

        auth = self._pool[self._index]
        self._index = (self._index + 1) % len(self._pool)

        self._logger.debug(
            "auth_retrieved",
            pool_index=self._index,
            pool_size=len(self._pool),
        )

        return auth

    def pool_size(self) -> int:
        """Get current pool size."""
        return len(self._pool)

    def refresh_pool(self, new_captures_path: Path | str) -> int:
        """
        Add new auth bundles from capture.

        Args:
            new_captures_path: Path to JSON with new auth bundles

        Returns:
            Number of bundles added
        """
        with open(new_captures_path) as f:
            data = json.load(f)

        new_bundles = [
            CapturedAuth(
                auth_code=item["auth_code"],
                auth_data=item["auth_data"],
                auth_type=item["auth_type"],
                source_timestamp=item["source_timestamp"],
            )
            for item in data
        ]

        initial_size = len(self._pool)
        self._pool.extend(new_bundles)

        # Save updated pool
        self._save_pool()

        added_count = len(self._pool) - initial_size
        self._logger.info(
            "auth_pool_refreshed",
            added=added_count,
            new_size=len(self._pool),
        )

        return added_count

    def _save_pool(self) -> None:
        """Save current pool to disk."""
        data = [
            {
                "auth_code": auth.auth_code,
                "auth_data": auth.auth_data,
                "auth_type": auth.auth_type,
                "source_timestamp": auth.source_timestamp,
            }
            for auth in self._pool
        ]

        with open(self._pool_path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def from_default_path(cls) -> AuthPoolManager:
        """Create manager from default pool path."""
        # Use Path.cwd() to get project root (assumes running from project root)
        pool_path = Path.cwd() / "research" / "captures" / "auth_pool.json"
        return cls(pool_path)
