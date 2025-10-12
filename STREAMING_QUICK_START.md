# Live Streaming Quick Start

Use these steps to keep the high-speed streamer running reliably.

## Prerequisites

- `research/captures/auth_pool.json` populated with fresh auth bundles (`python scripts/rebuild_auth_pool.py`).
- `research/captures/current_session_context.json` containing a valid session ticket (`python scripts/refresh_session_ticket.py --once`).
- `tokens.json` with a valid JWT + refresh token (use `scripts/generate_fresh_session.py` if you only have auth_pool).
- mitmproxy installed for future captures.

## Refresh the session ticket (every ~4 hours)

```powershell
mitmdump -p 8888 -w companion_collect/savedFlows/fresh_capture.mitm
python scripts/refresh_session_ticket.py  # watch mode
```

Launch the Companion App, search auctions once, and the watcher writes a new session ticket when it sees the traffic.

## Start the live streamer

```powershell
python scripts/run_live_stream.py
```

Useful flags:

- `--interval 1.0` → throttle requests.
- `--max-iterations 100` → run finite batches.
- `--output-dir ./auction_data` → persist every response.

The script prints live stats and handles auth rotation via the pool.

## Stream diagnostics

- Too many consecutive failures → script stops and tells you to refresh auth.
- Missing context file → rerun the session ticket helper (`scripts/refresh_session_ticket.py --once`).
- JWT expired → the streamer logs the refresh; if it fails, run `python scripts/generate_fresh_session.py`.

## Recommended cadence

- Refresh session ticket: every 4 hours.
- Rebuild auth pool: weekly, or when you see EA AUTH errors.
- Rotate tokens.json: monthly or when refresh token expires.

Store captures & tokens outside of git; `.gitignore` already skips the common secrets.
