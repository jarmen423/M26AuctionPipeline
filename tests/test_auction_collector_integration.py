"""Simple integration test: Verify AuthPoolManager integrates with AuctionCollector."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from companion_collect.adapters.request_template import RequestTemplate
from companion_collect.auth import session_manager as session_manager_module
from companion_collect.auth import token_manager as token_manager_module
from companion_collect.auth.auth_pool_manager import AuthPoolManager
from companion_collect.collectors import auctions as auctions_module
from companion_collect.collectors.auctions import AuctionCollector


@pytest.fixture(autouse=True)
def fake_token_and_session(monkeypatch):
    """Stub token/session managers so tests do not require real secrets."""

    class FakeTokenManager:
        async def get_valid_jwt(self):
            return "jwt-token"

        async def refresh_jwt(self):
            return "jwt-token"

    class FakeSessionManager:
        def __init__(self, token_manager):
            self.token_manager = token_manager
            self._ticket = SimpleNamespace(
                ticket="session-token",
                persona_id=123,
                blaze_id=123,
                display_name="TestPersona",
            )

        async def ensure_primary_ticket(self):
            return self._ticket

        async def get_session_ticket(self) -> str:
            return self._ticket.ticket

        async def create_session_ticket(
            self,
            *,
            auth_code: str | None = None,
            auth_data: str | None = None,
            auth_type: int | None = None,
            promote_primary: bool = True,
        ) -> str:
            return "session-token"

        async def mark_failed(self, ticket: str) -> None:
            return None

        async def ensure_backups(self) -> None:
            return None

    monkeypatch.setattr(
        token_manager_module.TokenManager,
        "from_file",
        classmethod(lambda cls, path: FakeTokenManager()),
    )
    monkeypatch.setattr(session_manager_module, "SessionManager", FakeSessionManager)


@pytest.fixture
def auth_pool(tmp_path):
    """Create test auth pool."""
    pool_data = [
        {
            "auth_code": f"code_{i}",
            "auth_data": f"data_{i}",
            "auth_type": 17039361,
            "source_timestamp": 1234567890.0 + i,
        }
        for i in range(5)
    ]

    pool_file = tmp_path / "test_pool.json"
    with open(pool_file, "w") as f:
        json.dump(pool_data, f)

    return AuthPoolManager(pool_file)


@pytest.fixture
def mock_template():
    """Create mock request template."""
    template = MagicMock(spec=RequestTemplate)

    # Mock render to return a simple request definition
    request_def = MagicMock()
    request_def.method = "POST"
    request_def.url = "https://test.api.com/endpoint"
    request_def.headers = {"Content-Type": "application/json"}
    request_def.params = {}
    request_def.json_body = {"test": "data"}
    request_def.data = None

    template.render.return_value = request_def
    return template


@pytest.fixture
def mock_client():
    """Create mock HTTP client."""
    client = AsyncMock()

    # Mock successful response
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "responseInfo": {"value": {"details": [{"id": i} for i in range(100)]}}
    }

    client.request.return_value = response
    return client


@pytest.mark.asyncio
async def test_auth_pool_integration(auth_pool, mock_template, mock_client):
    """Test that AuctionCollector uses AuthPoolManager correctly."""
    # Create collector with auth pool
    collector = AuctionCollector(
        request_template=mock_template,
        client=mock_client,
        auth_pool=auth_pool,
    )

    # Verify auth pool is stored
    assert collector._auth_pool is auth_pool
    assert collector._auth_pool.pool_size() == 5

    # Test fetch_once uses auth pool
    async with collector.lifecycle():
        initial_index = auth_pool._index

        # First fetch
        await collector.fetch_once()
        after_first = auth_pool._index
        first_context = mock_template.render.call_args.kwargs["context"]
        assert first_context["blaze_id"] == collector.settings.m26_blaze_id
        assert first_context["user_agent"] == auctions_module._DEFAULT_COMPANION_USER_AGENT

        # Verify rotation happened
        assert after_first == (initial_index + 1) % 5

        # Second fetch
        await collector.fetch_once()
        after_second = auth_pool._index
        second_context = mock_template.render.call_args.kwargs["context"]
        assert second_context["blaze_id"] == collector.settings.m26_blaze_id
        assert second_context["user_agent"] == auctions_module._DEFAULT_COMPANION_USER_AGENT

        # Verify continued rotation
        assert after_second == (after_first + 1) % 5


@pytest.mark.asyncio
async def test_auth_pool_auto_loads(mock_template, mock_client, tmp_path, monkeypatch):
    """Test that auth pool auto-loads if not provided."""
    # Create a test pool in the expected location
    auth_pool_path = tmp_path / "research" / "captures" / "auth_pool.json"
    auth_pool_path.parent.mkdir(parents=True, exist_ok=True)

    pool_data = [
        {
            "auth_code": "auto_code",
            "auth_data": "auto_data",
            "auth_type": 17039361,
            "source_timestamp": 1234567890.0,
        }
    ]
    with open(auth_pool_path, "w") as f:
        json.dump(pool_data, f)

    # Mock Path.cwd() to return tmp_path
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    # Create collector without auth_pool
    collector = AuctionCollector(
        request_template=mock_template,
        client=mock_client,
    )

    # Initially no auth pool
    assert collector._auth_pool is None

    # Enter lifecycle - should auto-load
    collector.settings.use_auth_pool = True
    async with collector.lifecycle():
        # Auth pool should be loaded
        assert collector._auth_pool is not None
        assert collector._auth_pool.pool_size() == 1

        # Test fetch works
        await collector.fetch_once()
        # If no error, auto-load worked!
        enforced_context = mock_template.render.call_args.kwargs["context"]
        assert enforced_context["blaze_id"] == collector.settings.m26_blaze_id
        assert enforced_context["user_agent"] == auctions_module._DEFAULT_COMPANION_USER_AGENT


@pytest.mark.asyncio
async def test_auth_pool_rotation_multiple_fetches(auth_pool, mock_template, mock_client):
    """Test auth pool rotates correctly across multiple fetches."""
    collector = AuctionCollector(
        request_template=mock_template,
        client=mock_client,
        auth_pool=auth_pool,
    )

    async with collector.lifecycle():
        # Track rotation across 10 fetches (2 full rotations of 5-auth pool)
        indices = []
        for _ in range(10):
            indices.append(auth_pool._index)
            await collector.fetch_once()

        # Verify rotation pattern: 0,1,2,3,4,0,1,2,3,4
        expected = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
        assert indices == expected


@pytest.mark.asyncio
async def test_fetch_once_overrides_incoming_context(mock_template, mock_client):
    collector = AuctionCollector(request_template=mock_template, client=mock_client)

    async with collector.lifecycle():
        await collector.fetch_once(context={"blaze_id": "madden-2025-xbsx-gen5", "user_agent": "bad-agent"})

    render_context = mock_template.render.call_args.kwargs["context"]
    assert render_context["blaze_id"] == collector.settings.m26_blaze_id
    assert render_context["user_agent"] == auctions_module._DEFAULT_COMPANION_USER_AGENT


def test_auth_pool_passed_to_collector(auth_pool):
    """Test that auth_pool parameter is properly stored."""
    collector = AuctionCollector(auth_pool=auth_pool)

    assert collector._auth_pool is auth_pool
    assert collector._auth_pool.pool_size() == 5
