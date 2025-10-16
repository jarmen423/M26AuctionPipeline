# M26 Auction Pipeline

M26 Auction Pipeline is a slimmed-down extract of the Companion Collect project that keeps only the production-ready service code, documentation, and runbooks required to poll the EA Companion App auction endpoints. Use it when you want a clean starting point focused on Madden 26 auction ingestion without the historical research artifacts.

## Features

- Async auction collector powered by `httpx`
- Request templating to replay Companion App calls with dynamic context
- Redis recent-auction fan-out list
- Postgres persistence with automatic table migration
- Structlog-based structured logging

## Configuration

The service is configured through environment variables (prefixed with `COMPANION_`) or a local `.env` file. Key settings include:

- `COMPANION_REQUEST_TEMPLATE_PATH`: Path to the request template JSON (defaults to `request_templates/mobile_search_auctions.json`).
- `COMPANION_REDIS_URL`: Redis connection string for the fan-out list.
- `COMPANION_POSTGRES_DSN`: Postgres DSN for historical storage.
- `COMPANION_TOKENS_PATH`: Location of the persisted OAuth tokens file (defaults to `tokens.json`).
- `COMPANION_SESSION_CONTEXT_PATH`: Location where the latest session ticket is stored (`research/captures/current_session_context.json`).
- `COMPANION_M26_SERVICE_BASE_URL`: Override base URL for `madden26.service.easports.com` helper calls.
- `COMPANION_M26_SERVICE_USER_AGENT`: User agent applied by the helper client.

See `companion_collect/config.py` for the full list of tunables.

## Running the pipeline

Create a virtual environment and install the base dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you need the testing toolchain, install the dev extras as well:

```powershell
pip install -r requirements-dev.txt
# or, if you prefer editable installs
pip install -e .[dev]
```

Populate your `.env` file, then run the pipeline:

```powershell
python scripts/run_auction_pipeline.py
```

### Binder probes via WAL

To replay binder calls against `/wal/mca/Process`, reuse the collector stack by providing a binder payload:

```powershell
python scripts/fetch_binder_page.py --binder-command binder --payload-file binder_payload.json --output binder_response.json
```

`binder_payload.json` should contain the unescaped `requestPayload` object captured from the mobile app (the helper escapes it before sending). Use `--binder-command hub` for `GetHubEntryData` (command 9114) or pass explicit overrides via `--command-id` / `--command-name` when experimenting with other commands.

## Tests

After installing the dev extras you can execute the unit tests:

```powershell
pytest
```

## Request template format

The default template under `request_templates/mobile_search_auctions.json` mirrors the Companion Blaze request:

```json
{
  "method": "POST",
  "url": "https://wal2.tools.gos.bio-iad.ea.com/wal/mca/Process/{session_ticket}",
  "headers": {
    "X-BLAZE-ID": "{blaze_id}",
    "User-Agent": "{user_agent}",
    "Cookie": "{ak_bmsc_cookie}",
    "X-Application-Key": "MADDEN-MCA"
  },
  "json": {
    "apiVersion": "{api_version}",
    "clientDevice": "{client_device}",
    "requestInfo": "{…messageAuthData payload…}"
  }
}
```

Every string supports Python-style `{placeholder}` formatting and is filled using the context assembled in `AuctionCollector.fetch_once`. See `request_templates/mobile_search_auctions.sample.json` for a capture-based example payload.

## Session ticket + auth refresh

The pipeline expects to find:

- `research/captures/auth_pool.json`: rotating auth bundles.
- `research/captures/current_session_context.json`: the latest session ticket + headers.
- `tokens.json`: OAuth JWT + refresh token blob.

Use the helper scripts in `scripts/`:

1. `python scripts/refresh_session_ticket.py --once` to extract a session ticket from a fresh mitmproxy capture.
2. `python scripts/rebuild_auth_pool.py` after capturing new auction traffic to refresh `auth_pool.json`.
3. `python scripts/run_live_stream.py` for high-speed streaming once auth is fresh.

See `docs/companion_auth_plan.md` for the full auth refresh plan and `docs/COMPLETE_AUCTION_COMMANDS.md` for discovered Blaze commands.
