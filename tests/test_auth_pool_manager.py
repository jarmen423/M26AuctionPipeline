"""Tests for AuthPoolManager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from companion_collect.auth.auth_pool_manager import AuthPoolManager, CapturedAuth


@pytest.fixture
def temp_pool_file(tmp_path):
    """Create temporary auth pool file with 2 auth bundles."""
    pool_data = [
        {
            "auth_code": "code1",
            "auth_data": "data1",
            "auth_type": 17039361,
            "source_timestamp": 1234567890.0,
        },
        {
            "auth_code": "code2",
            "auth_data": "data2",
            "auth_type": 17039361,
            "source_timestamp": 1234567891.0,
        },
    ]

    pool_file = tmp_path / "auth_pool.json"
    with open(pool_file, "w") as f:
        json.dump(pool_data, f)

    return pool_file


@pytest.fixture
def empty_pool_file(tmp_path):
    """Create temporary empty auth pool file."""
    pool_file = tmp_path / "empty_pool.json"
    with open(pool_file, "w") as f:
        json.dump([], f)

    return pool_file


def test_load_pool(temp_pool_file):
    """Test loading auth pool from JSON file."""
    manager = AuthPoolManager(temp_pool_file)

    assert manager.pool_size() == 2
    assert isinstance(manager._pool[0], CapturedAuth)
    assert manager._pool[0].auth_code == "code1"
    assert manager._pool[1].auth_code == "code2"


def test_get_next_auth_rotates(temp_pool_file):
    """Test auth rotation cycles through pool."""
    manager = AuthPoolManager(temp_pool_file)

    # First auth
    auth1 = manager.get_next_auth()
    assert auth1.auth_code == "code1"
    assert auth1.auth_data == "data1"
    assert auth1.auth_type == 17039361

    # Second auth
    auth2 = manager.get_next_auth()
    assert auth2.auth_code == "code2"
    assert auth2.auth_data == "data2"

    # Wraps back to first
    auth3 = manager.get_next_auth()
    assert auth3.auth_code == "code1"

    # Verify continuous rotation
    auth4 = manager.get_next_auth()
    assert auth4.auth_code == "code2"


def test_refresh_pool(temp_pool_file, tmp_path):
    """Test adding new auth bundles to pool."""
    manager = AuthPoolManager(temp_pool_file)
    initial_size = manager.pool_size()
    assert initial_size == 2

    # Create new captures file
    new_captures = tmp_path / "new_captures.json"
    new_data = [
        {
            "auth_code": "code3",
            "auth_data": "data3",
            "auth_type": 17039361,
            "source_timestamp": 1234567892.0,
        },
        {
            "auth_code": "code4",
            "auth_data": "data4",
            "auth_type": 17039361,
            "source_timestamp": 1234567893.0,
        },
    ]
    with open(new_captures, "w") as f:
        json.dump(new_data, f)

    # Refresh pool
    added = manager.refresh_pool(new_captures)
    assert added == 2
    assert manager.pool_size() == 4

    # Verify new auths are accessible
    manager._index = 2  # Move to new auths
    auth3 = manager.get_next_auth()
    assert auth3.auth_code == "code3"


def test_pool_size(temp_pool_file):
    """Test pool_size returns correct count."""
    manager = AuthPoolManager(temp_pool_file)

    assert manager.pool_size() == 2

    # Size should update after refresh
    temp_path = temp_pool_file.parent
    new_captures = temp_path / "single_capture.json"
    with open(new_captures, "w") as f:
        json.dump(
            [
                {
                    "auth_code": "code3",
                    "auth_data": "data3",
                    "auth_type": 17039361,
                    "source_timestamp": 1234567892.0,
                }
            ],
            f,
        )

    manager.refresh_pool(new_captures)
    assert manager.pool_size() == 3


def test_empty_pool_error(empty_pool_file):
    """Test that empty pool raises RuntimeError on get_next_auth."""
    manager = AuthPoolManager(empty_pool_file)

    assert manager.pool_size() == 0

    with pytest.raises(RuntimeError, match="Auth pool is empty"):
        manager.get_next_auth()


def test_missing_file_error(tmp_path):
    """Test that missing pool file raises FileNotFoundError."""
    missing_file = tmp_path / "nonexistent.json"

    with pytest.raises(FileNotFoundError, match="Auth pool not found"):
        AuthPoolManager(missing_file)


def test_captured_auth_dataclass():
    """Test CapturedAuth dataclass properties."""
    auth = CapturedAuth(
        auth_code="test_code",
        auth_data="test_data",
        auth_type=17039361,
        source_timestamp=1234567890.0,
    )

    assert auth.auth_code == "test_code"
    assert auth.auth_data == "test_data"
    assert auth.auth_type == 17039361
    assert auth.source_timestamp == 1234567890.0
