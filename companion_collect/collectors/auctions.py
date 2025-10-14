"""Asynchronous collectors for Companion App auction data."""

from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import monotonic, time
from typing import Any, AsyncIterator, Mapping, cast

import httpx
import json
from pathlib import Path

from ea_constants import AuctionSearchResponse

from companion_collect.adapters.request_template import RequestTemplate
from companion_collect.auth.auth_pool_manager import AuthPoolManager
from companion_collect.auth.blaze_auth import AuthBundle, compute_message_auth
from companion_collect.auth.session_manager import SessionManager
from companion_collect.auth.token_manager import TokenManager
from companion_collect.config import Settings, get_settings
from companion_collect.logging import get_logger


class AuctionCollector:
    """Poll the Companion App `Mobile_SearchAuctions` endpoint."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        request_template: RequestTemplate | None = None,
        auth_pool: AuthPoolManager | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._template = request_template
        self._auth_pool = auth_pool
        self._stopped = asyncio.Event()
        self._logger = get_logger(__name__).bind(component="auction_collector")
        self._page = 0
        # Hybrid request id strategy: random 32-bit seed then increment each request.
        self._request_counter = random.getrandbits(32)
        self.token_manager: TokenManager | None = None
        self.session_manager: SessionManager | None = None

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator["AuctionCollector"]:
        """Context manager to ensure client lifecycle and configuration."""

        async with (
            httpx.AsyncClient(
                timeout=self.settings.collector_request_timeout_seconds,
                headers={"User-Agent": "MutDashboard-Collector/1.0"},
            )
            if self._client is None
            else _existing_client(self._client)
        ) as client:
            self._client = client
            if self._template is None:
                self._template = RequestTemplate.from_path(self.settings.request_template_path)
            if self._auth_pool is None and self.settings.use_auth_pool:
                try:
                    self._auth_pool = AuthPoolManager.from_default_path()
                    self._logger.info(
                        "auth_pool_auto_loaded",
                        pool_size=self._auth_pool.pool_size(),
                    )
                except FileNotFoundError:
                    self._logger.warning("auth_pool_not_found", path=self.settings.auth_pool_path)

            if self.token_manager is None:
                self.token_manager = TokenManager.from_file(Path(self.settings.tokens_path))
                self.session_manager = SessionManager(self.token_manager)
                self._logger.info("token_and_session_loaded")

            self._page = 0
            self._logger.info("collector_ready", poll_interval=self.settings.poll_interval_seconds)
            try:
                yield self
            finally:
                self._logger.info("collector_stopped")

    async def fetch_once(
        self,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> AuctionSearchResponse:
        """Fetch auction data once using the configured request template."""

        if self._client is None or self._template is None:
            msg = "AuctionCollector lifecycle must be entered before fetching."
            raise RuntimeError(msg)

        merged_context: dict[str, Any] = {"page": self._page}
        merged_context.update(self.settings.request_context_overrides)
        if context:
            merged_context.update(context)

        page_size = int(merged_context.get("page_size", self.settings.search_page_size))
        merged_context.setdefault("page_size", page_size)
        merged_context.setdefault("count", page_size)
        merged_context.setdefault("start", self._page * page_size)
        merged_context.setdefault("page_offset", self._page * page_size)
        merged_context.setdefault("api_version", "2")
        merged_context.setdefault("client_device", "3")
        merged_context.setdefault("command_name", "Mobile_SearchAuctions")
        merged_context.setdefault("component_id", 2050)
        merged_context.setdefault("command_id", 9153)
        merged_context.setdefault("component_name", "mut")
        merged_context.setdefault("ip_address", "127.0.0.1")
        merged_context.setdefault("request_payload", "{\\\"filters\\\":[],\\\"itemName\\\":\\\"\\\"}")
        merged_context.setdefault("auth_type", 17_039_361)
        merged_context.setdefault("user_agent", "MutDashboard-Collector/1.0")
        merged_context.setdefault("ak_bmsc_cookie", "")
        merged_context.setdefault("blaze_id", self.settings.m26_blaze_id)
        merged_context.setdefault("device_id", self.settings.device_id or "dev")
        if self.settings.device_id:
            merged_context.setdefault("device_id", self.settings.device_id)
        merged_context.setdefault(
            "message_expiration_time",
            int(time()) + self.settings.poll_interval_seconds * 10,
        )

        # Load session context if not already present
        if "session_ticket" not in merged_context:
            session_context = self._load_session_context()
            if session_context:
                if "session_ticket" in session_context:
                    merged_context["session_ticket"] = session_context["session_ticket"]
                if "persona_id" in session_context:
                    merged_context["persona_id"] = session_context["persona_id"]
                if "personaId" in session_context:
                    merged_context["persona_id"] = session_context["personaId"]
                # Inject ak_bmsc cookie (or Cookie fallback) if provided by session context
                cookie_val = session_context.get("ak_bmsc_cookie") or session_context.get("Cookie")
                if cookie_val:
                    merged_context["ak_bmsc_cookie"] = cookie_val
                # Prefer user agent from session context if present
                if "user_agent" in session_context:
                    merged_context["user_agent"] = session_context["user_agent"]
        
        # --- Auth material ---
        if self._auth_pool:
            auth = self._auth_pool.get_next_auth()
            merged_context.setdefault("auth_code", auth.auth_code)
            merged_context.setdefault("auth_data", auth.auth_data)
            merged_context.setdefault("auth_type", auth.auth_type)
            self._logger.debug(
                "auth_pool_used",
                pool_index=self._auth_pool._index,
                pool_size=self._auth_pool.pool_size(),
            )
        else:
            bundle = self._generate_auth_bundle(merged_context)
            merged_context["auth_code"] = bundle.auth_code
            merged_context["auth_data"] = bundle.auth_data
            merged_context["auth_type"] = bundle.auth_type

        try:
            request_def = self._template.render(context=merged_context)
        except KeyError as exc:
            missing = exc.args[0]
            raise KeyError(
                f"Missing template context key '{missing}'. "
                "Provide it via COMPANION_REQUEST_CONTEXT_OVERRIDES or the auth helper."
            ) from exc
        response = await self._client.request(
            request_def.method,
            request_def.url,
            headers=request_def.headers,
            params=request_def.params,
            json=request_def.json_body,
            data=request_def.data,
        )
        response.raise_for_status()
        response_data = cast(AuctionSearchResponse, response.json())

        # Check for EA API error responses (HTTP 200 but with error object)
        if "error" in response_data:
            error_info = response_data["error"]
            error_code = error_info.get("errorcode")
            error_name = error_info.get("errorname", "UNKNOWN_ERROR")
            error_msg = error_info.get("errortdf", {}).get("errorString", "No error message")

            self._logger.error(
                "api_error_response",
                error_code=error_code,
                error_name=error_name,
                error_message=error_msg,
            )

            # Raise a clear exception for error responses
            raise RuntimeError(
                f"EA API Error {error_code} ({error_name}): {error_msg}. "
                "This usually means auth codes are stale. Try refreshing the auth pool."
            )

        self._logger.debug("fetch_success", status=response.status_code)
        return response_data

    def _load_session_context(self) -> dict[str, Any] | None:
        """Load session context from file."""
        context_path = Path(self.settings.session_context_path)
        print(f"DEBUG: Looking for session context at: {context_path}")
        print(f"DEBUG: File exists: {context_path.exists()}")
        print(f"DEBUG: Absolute path: {context_path.absolute()}")
        
        if not context_path.exists():
            self._logger.warning("session_context_not_found", path=str(context_path))
            return None
        
        try:
            with open(context_path) as f:
                data = json.load(f)
            print(f"DEBUG: Loaded session context: {data}")
            return data
        except Exception as e:
            self._logger.warning("session_context_load_failed", error=str(e))
            print(f"DEBUG: Failed to load session context: {e}")
            return None

    async def stream(self) -> AsyncIterator[AuctionSearchResponse]:
        """Continuously yield auction payloads until stopped."""

        poll_interval = max(1, self.settings.poll_interval_seconds)

        while not self._stopped.is_set():
            start = monotonic()
            try:
                payload = await self.fetch_once()
            except Exception as exc:  # pragma: no cover - logging side-effect only
                self._logger.warning(
                    "fetch_failed",
                    error_type=exc.__class__.__name__,
                    error=str(exc),
                )
                await self._backoff()
                continue

            yield payload
            self._page += 1
            elapsed = monotonic() - start
            sleep_for = max(0, poll_interval - elapsed)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                continue

    async def fetch_auctions(self, filters: list | None = None) -> AuctionSearchResponse:
        """Fetch M26 auctions with optional filters, handling auth refresh on expiry."""
        if self.token_manager is None or self.session_manager is None:
            raise RuntimeError(
                "AuctionCollector lifecycle must be entered before fetch_auctions."
            )

        token_manager = self.token_manager
        session_manager = self.session_manager

        context_path = Path(self.settings.session_context_path)
        if not context_path.exists():
            raise RuntimeError(
                f"Session context not found. Run scripts/generate_fresh_session.py first: {context_path}"
            )

        with open(context_path) as f:
            session_context = json.load(f)

        context = session_context.copy()
        context.update(
            {
                "blaze_id": self.settings.m26_blaze_id,
                "command_name": self.settings.m26_command_name,
                "command_id": self.settings.m26_command_id,
                "component_id": self.settings.m26_component_id,
            }
        )

        if filters is not None:
            payload_dict = {"filters": filters, "itemName": ""}
            payload_json = json.dumps(payload_dict)
            escaped_payload = payload_json.replace("\\", "\\\\").replace('"', '\\"')
            context["request_payload"] = escaped_payload

        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                response = await self.fetch_once(context=context)
                break
            except RuntimeError as e:
                error_str = str(e).lower()
                if (
                    attempt < max_retries
                    and ("auth" in error_str or "stale" in error_str or "expired" in error_str)
                ):
                    self._logger.warning("auth_error_retry", attempt=attempt + 1, error=str(e))
                    await token_manager.refresh_jwt()

                    if self._auth_pool:
                        refreshed = self._auth_pool.get_next_auth()
                        context["auth_code"] = refreshed.auth_code
                        context["auth_data"] = refreshed.auth_data
                        context["auth_type"] = refreshed.auth_type
                    else:
                        refreshed_bundle = self._generate_auth_bundle(context)
                        context["auth_code"] = refreshed_bundle.auth_code
                        context["auth_data"] = refreshed_bundle.auth_data
                        context["auth_type"] = refreshed_bundle.auth_type

                    session_ticket = await session_manager.create_session_ticket()

                    session_context["session_ticket"] = session_ticket
                    context["session_ticket"] = session_ticket
                    with open(context_path, "w") as f:
                        json.dump(session_context, f, indent=2)

                    self._logger.info("refreshed_session_ticket")
                else:
                    raise

        # Save raw response
        save_path = Path("auction_data/fresh_auction_response.json")
        save_path.parent.mkdir(exist_ok=True, parents=True)
        with open(save_path, "w") as f:
            json.dump(response, f, indent=2)
        self._logger.info("saved_raw_response", path=save_path)

        return response

    async def _backoff(self) -> None:
        try:
            await asyncio.wait_for(
                self._stopped.wait(),
                timeout=self.settings.collector_backoff_seconds,
            )
        except asyncio.TimeoutError:
            return

    def _generate_auth_bundle(self, context: Mapping[str, Any]) -> AuthBundle:
        persona_id = self._resolve_persona_id(context)
        expiration_raw = context.get("message_expiration_time")
        message_expiration: datetime | None = None
        if isinstance(expiration_raw, (int, float)):
            message_expiration = datetime.fromtimestamp(expiration_raw, tz=timezone.utc)

        request_id = self._request_counter & 0xFFFFFFFF
        self._request_counter += 1

        device_id = str(context.get("device_id") or self.settings.device_id or "444d362e8e067fe2")

        bundle = compute_message_auth(
            b"",
            device_id=device_id,
            request_id=request_id,
            blaze_id=persona_id,
            message_expiration=message_expiration,
        )

        self._logger.debug(
            "auth_generated",
            request_id=request_id,
            persona_id=persona_id,
            auth_type=bundle.auth_type,
        )

        return bundle

    def _resolve_persona_id(self, context: Mapping[str, Any]) -> int:
        for key in ("persona_id", "personaId", "blaze_persona_id", "blaze_id"):
            value = context.get(key)
            if value is None:
                continue
            try:
                return int(str(value))
            except (TypeError, ValueError):
                self._logger.warning("persona_parse_failed", key=key, value=value)

        if self.session_manager and self.session_manager._primary_ticket:
            return self.session_manager._primary_ticket.blaze_id

        if self.settings.m26_blaze_id:
            try:
                return int(str(self.settings.m26_blaze_id))
            except (TypeError, ValueError):
                self._logger.warning(
                    "persona_parse_failed",
                    key="settings.m26_blaze_id",
                    value=self.settings.m26_blaze_id,
                )

        raise RuntimeError(
            "Unable to derive persona_id for message auth generation."
            " Provide persona_id in session context or settings."
        )

    def stop(self) -> None:
        """Signal the collector to stop."""

        self._stopped.set()


@asynccontextmanager
async def _existing_client(client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    yield client
