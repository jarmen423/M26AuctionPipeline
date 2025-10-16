"""Client helpers for https://madden26.service.easports.com."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, MutableMapping

import httpx

from companion_collect.config import Settings, get_settings
from companion_collect.logging import get_logger

_LOGGER = get_logger(__name__).bind(component="m26_service_client")


@dataclass
class ServiceRequest:
    """Description of a request to send to the M26 service."""

    method: str
    path: str
    params: Mapping[str, Any] | None = None
    json: Any | None = None
    headers: Mapping[str, str] | None = None


class Madden26ServiceClient:
    """Thin wrapper around httpx for the madden26.service.easports.com host.

    The client keeps only transport-level defaults (headers, base URL). Callers must
    supply identity-bearing headers per request so usage stays stateless.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._default_headers = dict(default_headers or {})
        if "User-Agent" not in self._default_headers:
            self._default_headers["User-Agent"] = self.settings.m26_service_user_agent
        if "Accept" not in self._default_headers:
            self._default_headers["Accept"] = "application/json"
        self._logger = _LOGGER

    @property
    def base_url(self) -> str:
        return self.settings.m26_service_base_url.rstrip("/")

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator["Madden26ServiceClient"]:
        """Ensure an AsyncClient is available for the duration of the context."""

        if self._client is not None:
            yield self
            return

        timeout = httpx.Timeout(self.settings.m26_service_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            self._client = client
            try:
                yield self
            finally:
                self._client = None

    async def request(self, request: ServiceRequest) -> httpx.Response:
        """Perform a raw request against the service."""

        if self._client is None:
            raise RuntimeError("Madden26ServiceClient.lifecycle must be entered before requesting")

        url = f"{self.base_url}/{request.path.lstrip('/')}"
        headers: MutableMapping[str, str] = dict(self._default_headers)
        if request.headers:
            headers |= request.headers

        self._logger.debug(
            "service_request",
            method=request.method,
            url=url,
            has_json=request.json is not None,
            params_present=bool(request.params),
        )

        response = await self._client.request(
            request.method,
            url,
            params=request.params,
            json=request.json,
            headers=headers,
        )
        return response

    async def request_json(self, request: ServiceRequest) -> Any:
        """Perform a request and return the JSON body, raising for HTTP errors."""

        response = await self.request(request)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - pass through with context
            self._logger.warning(
                "service_request_failed",
                status_code=exc.response.status_code,
                url=str(exc.request.url),
            )
            raise
        return response.json()

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Convenience helper for GET JSON endpoints."""

        request = ServiceRequest(method="GET", path=path, params=params, headers=headers)
        return await self.request_json(request)

    async def post_json(
        self,
        path: str,
        *,
        json_body: Any,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Convenience helper for POST JSON endpoints."""

        request = ServiceRequest(method="POST", path=path, json=json_body, headers=headers)
        return await self.request_json(request)