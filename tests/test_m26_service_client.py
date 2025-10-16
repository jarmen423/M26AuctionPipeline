import json

import pytest
import httpx

from companion_collect.api.m26_service import Madden26ServiceClient, ServiceRequest
from companion_collect.config import Settings


@pytest.mark.asyncio
async def test_request_json_builds_url_and_headers():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content.decode()) if request.content else None
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    settings = Settings(m26_service_base_url="https://example.test/service")

    async with httpx.AsyncClient(transport=transport) as client:
        service = Madden26ServiceClient(settings=settings, client=client)
        payload = {"hello": "world"}
        result = await service.request_json(
            ServiceRequest(method="POST", path="/foo/bar", json=payload)
        )

    assert captured["url"] == "https://example.test/service/foo/bar"
    assert captured["json"] == {"hello": "world"}
    assert captured["headers"]["user-agent"] == settings.m26_service_user_agent
    assert captured["headers"]["accept"] == "application/json"
    assert result == {"ok": True}
