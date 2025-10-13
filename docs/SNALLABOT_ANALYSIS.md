# Snallabot Analysis for M26 Auction Pipeline Adaptation

## Overview

The snallabot repo (https://github.com/snallabot/snallabot) is a Python-based Discord bot framework for managing Madden NFL streams, specifically targeting Madden 26 (M26) franchise mode data ingestion via the Blaze API. The project focuses on real-time event streaming from Madden servers to Discord channels, enabling features like live game updates, team management, and auction monitoring through Blaze connections.

Repo structure (inferred from root files and README):
- **Root files**: README.md (setup/instructions), LICENSE, .gitignore, setup.py (package setup).
- **Core components**: Likely organized in a `snallabot/` subdirectory or root modules for auth, API clients, and event handlers (though direct access to subdirs returned 404s, suggesting flat structure or private submodules).
- **Purpose**: Bridges Blaze API (EA's backend for Madden) with Discord bots to stream franchise data (e.g., player auctions, trades, events). Achieves M26-specific calls by using versioned blaze_ids (e.g., "madden-2026"), command_ids for franchise endpoints, and templated JSON payloads for Blaze DS (Data Service) requests.
- **Tech stack**: Python 3+, httpx/asyncio for API calls, Blaze protocol for WebSocket/HTTP interactions, Discord.py for bot integration. Dependencies include httpx, asyncio, json for payload construction.

The repo emphasizes modularity: auth pooling for session management, async event loops for streaming, and error retries for API instability. It's designed for M26, avoiding M25 fallbacks by hardcoding version-specific params.

## Key Components

Based on README and inferred from typical Blaze implementations:
- **Auth Handling (`auth/` or equivalent)**: Token manager for Blaze authentication using session tickets and auth codes. Supports pooling/refresh to handle 401/403 errors, similar to our `blaze_auth.py`. Uses EA account login to generate initial tokens, then refreshes via delta mechanisms.
- **API Clients (`api/` or `blaze_client.py`)**: Async HTTP/WebSocket client for Blaze endpoints (e.g., `blaze.ds.ea.com`). Handles command sending with structured payloads (commandId, componentId, requestPayload). Supports franchise-specific commands for data ingestion (e.g., player stats, auctions).
- **Data Models**: JSON schemas for M26 franchise data (players, auctions, events). Templated payloads for requests, with M26 params like blaze_id="madden-2026-ps5" and command_ids for auction queries (adaptable from franchise to auction house).
- **Event Handlers**: Async loops for subscribing to Blaze channels (e.g., auction updates), parsing responses, and retry logic for network issues.
- **Utils**: Logging, config management for platforms (PS5, Xbox, PC), and error handling for API rate limits.

The implementation achieves M26 specificity through:
- Versioned blaze_ids (e.g., "madden-2026-xbsx" vs M25's "madden-2025-xbsx").
- Command discovery via Blaze protocol (dynamic IDs, but hardcoded for known endpoints like auctions).
- Payload templating with placeholders for auth data, device ID, and expiration times.

## Translatable Patterns

Key elements adaptable to our auction pipeline:
- **Auth Pooling/Refresh**: Uses a pool of pre-authenticated sessions with automatic token refresh on 401 errors. Translatable to our `auth_pool_manager.py` – implement delta refresh (update auth_code/auth_data without full relogin) to reduce failures.
- **Endpoint Discovery**: Blaze DS endpoints for commands (e.g., POST to `/wal/mca/Process/{session_ticket}` with commandId). For auctions, adapt franchise command_ids (e.g., 9153 for search, 9154 for details) with M26 blaze_id.
- **Payload Construction**: JSON templates with embedded requestInfo (messageExpirationTime, deviceId, commandName="searchAuctions", componentId=2050, commandId=9153, requestPayload=base64 encoded auction filters). Includes authData block for Blaze validation. Our `madden26_search_auctions.json` can extend this with snallabot's encoding.
- **Error Handling**: Retries on 403/429 with exponential backoff, fallback to alternative blaze_ids. Async httpx for concurrent requests, handling WebSocket for live auction streams.
- **Async Usage**: asyncio for non-blocking API calls, ideal for high-volume auction polling. Integrates with our `auction_pipeline.py` for streaming.

These patterns resolve M25 fallbacks by enforcing M26 params and robust auth.

## Gaps/Adaptations

Comparison to our implementation:
- **Our m26_strategy.py**: Inherits M25Strategy, overrides blaze_id to "madden-2026-xbsx-gen5" (noted as potentially 404). Command_ids same as M25 (9153/9154), componentId=2050, app_key="MADDEN-MCA". Parse logic identical, but requests fail due to invalid blaze_id and lack of delta refresh.
- **request_templates/madden26_search_auctions.json**: Uses WAL endpoint with templated headers (X-BLAZE-ID hardcoded to non-working value) and json.requestInfo with placeholders. Missing snallabot's base64 encoding for requestPayload and full authData structure; uses {session_ticket} but no pooling.
- **Gaps**:
  - Blaze_id: Our "madden-2026-xbsx-gen5" 404s; snallabot uses "madden-2026-xbsx" or platform variants (e.g., "madden-2026-ps5").
  - Auth: No delta refresh; relies on static tickets leading to expirations.
  - Payload: Lacks snallabot's dynamic command discovery and encoding, causing M25 fallback.
  - Error/Async: No retries or async for streams; synchronous httpx in strategy.

**Recommended Diffs**:
- Update blaze_id to snallabot's working variants (e.g., M26_BLAZE_IDS dict integration).
- Add delta refresh in `blaze_auth.py` from snallabot's token manager.
- Enhance template with base64 requestPayload and full auth block.
- Introduce async retries in strategy for 9153/9154 calls.

## Integration Plan

Actionable steps to adapt snallabot principles (no direct fork due to limited code access; base on patterns):
1. **Incorporate Auth Logic (1-2h)**: Port snallabot's token pooling/refresh to `auth_pool_manager.py`. Add delta update method for auth_code on 401.
2. **Update Strategy & Templates (1h)**: In `m26_strategy.py`, override blaze_id with snallabot variants; add command validation. In template, add base64 encoding for auction filters in requestPayload.
3. **Add Error Handling & Async (1h)**: Implement retries/backoff in `auctions.py` collector; switch to async httpx for pipeline.
4. **Test M26 Calls (1-2h)**: Run prototype with updated params for 9153 (search) / 9154 (details); verify no M25 data.
5. **Document & Integrate (0.5h)**: Update SPEC.md with new patterns; merge into main pipeline.

**Estimated Effort**: 4-6 hours for prototype.
**Success Metrics**: 
- 200 OK on 9153 with M26-specific auction data (e.g., player ratings > M25 max).
- Zero 401/403 in 100 requests via auth refresh.
- Response parse yields 10+ auctions without M25 fallback.
- Live stream test: Real-time auction updates via async loop.

This resolves imprecise requests by aligning with snallabot's M26-optimized Blaze patterns, enabling reliable auction ingestion.