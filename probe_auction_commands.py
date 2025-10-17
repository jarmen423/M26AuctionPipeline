#!/usr/bin/env python3
"""Probe known MUT Mobile commands against the WAL Process endpoint.

Uses the current Madden 26 session ticket and persona metadata to send command
requests for the command/component IDs documented in docs/COMPLETE_AUCTION_COMMANDS.md.
Outputs status codes and short snippets so we can spot non-404 behaviour quickly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

import httpx

from companion_collect.auth.blaze_auth import compute_message_auth
from companion_collect.auth.session_manager import SessionManager
from companion_collect.auth.token_manager import TokenManager
from companion_collect.config import get_settings

SESSION_CONTEXT_PATH = Path("auction_data/current_session_context.json")

COMMAND_SPECS: Iterable[dict[str, Any]] = (
    {"id": 9114, "name": "GetHubEntryData", "payload": {}},
    {"id": 9121, "name": "GetBinderPage", "payload": {"offset": 0, "count": 25}},
    {"id": 9153, "name": "Mobile_SearchAuctions", "payload": {"filters": [], "itemName": ""}},
    {"id": 9154, "name": "Mobile_RefreshAuctionDetails", "payload": {"auctionIdList": []}},
    {"id": 9157, "name": "Mobile_GetAuctionBids", "payload": {"offset": 0, "count": 50}},
)

HOST = "wal2.tools.gos.bio-iad.ea.com"
PROCESS_PATH = "wal/mca/Process"


def _load_cookie() -> str | None:
    if not SESSION_CONTEXT_PATH.exists():
        return None
    try:
        ctx = json.loads(SESSION_CONTEXT_PATH.read_text())
        cookie = ctx.get("ak_bmsc_cookie")
        if isinstance(cookie, str) and cookie.strip():
            return cookie.strip()
    except json.JSONDecodeError:
        pass
    return None


async def prepare_session(settings):
    token_mgr = TokenManager.from_file(settings.tokens_path)
    session_mgr = SessionManager(token_mgr)
    ticket = await session_mgr.ensure_primary_ticket()
    return session_mgr, ticket


def build_headers(settings, cookie: str | None) -> dict[str, str]:
    headers = {
        "Accept-Charset": "UTF-8",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
        "X-BLAZE-ID": settings.m26_blaze_id,
        "X-Application-Key": "MADDEN-MCA",
        "X-BLAZE-VOID-RESP": "XML",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def probe_commands() -> None:
    settings = get_settings()
    _, primary_ticket = await prepare_session(settings)
    persona_id = primary_ticket.persona_id or primary_ticket.blaze_id

    if persona_id is None:
        raise RuntimeError("Unable to determine persona_id from session ticket.")

    cookie = _load_cookie()
    headers = build_headers(settings, cookie)

    component_id = settings.m26_component_id
    component_name = "mut"
    device_id = settings.device_id or "444d362e8e067fe2"

    results: list[dict[str, Any]] = []
    request_id = 1

    async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
        for command in COMMAND_SPECS:
            command_id = command["id"]
            command_name = command["name"]
            payload = command.get("payload", {})
            payload_str = json.dumps(payload, separators=(",", ":"))

            expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
            message_expiration_time = int(expires_at.timestamp())
            request_id = (request_id & 0xFFFFFFFF) or 1

            bundle = compute_message_auth(
                b"",
                device_id=device_id,
                request_id=request_id,
                blaze_id=persona_id,
                message_expiration=expires_at,
            )

            request_info = {
                "messageExpirationTime": message_expiration_time,
                "deviceId": device_id,
                "commandName": command_name,
                "componentId": component_id,
                "commandId": command_id,
                "ipAddress": "127.0.0.1",
                "requestPayload": payload_str,
                "componentName": component_name,
                "messageAuthData": {
                    "authCode": bundle.auth_code,
                    "authData": bundle.auth_data,
                    "authType": bundle.auth_type,
                },
            }

            body = {
                "apiVersion": 2,
                "clientDevice": 3,
                "requestInfo": json.dumps(request_info, separators=(",", ":")),
            }

            url = f"https://{HOST}/{PROCESS_PATH}/{primary_ticket.ticket}"

            try:
                response = await client.post(url, headers=headers, json=body)
                snippet = response.text.strip().replace("\n", " ")[:200]
                results.append(
                    {
                        "command_id": command_id,
                        "command_name": command_name,
                        "status": response.status_code,
                        "snippet": snippet,
                        "payload": payload,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "command_id": command_id,
                        "command_name": command_name,
                        "status": "ERROR",
                        "error": str(exc),
                        "payload": payload,
                    }
                )

    output = {
        "session_ticket": primary_ticket.ticket,
        "persona_id": persona_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    Path("probe_auction_commands.json").write_text(json.dumps(output, indent=2))
    print("Wrote probe results to probe_auction_commands.json")


if __name__ == "__main__":
    asyncio.run(probe_commands())
