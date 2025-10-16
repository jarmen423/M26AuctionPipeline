"""Companion Collect: Companion App ingest service package."""

from __future__ import annotations

import sys
from pathlib import Path

# Guarantee top-level modules (for example ``ea_constants.py``) stay importable
# when scripts are executed directly (which sets sys.path[0] to ``scripts/``).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from .collectors import AuctionCollector
from .config import Settings, get_settings
from .pipelines import AuctionPipeline
from .storage import PostgresAuctionStore, RedisAuctionCache
from .api.m26_service import Madden26ServiceClient, ServiceRequest

__all__ = [
    "AuctionCollector",
    "AuctionPipeline",
    "PostgresAuctionStore",
    "RedisAuctionCache",
    "Settings",
    "get_settings",
    "Madden26ServiceClient",
    "ServiceRequest",
]
