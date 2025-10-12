# Quick Start

This repo keeps only the production pipeline and the scripts you actually need. The fastest path to a healthy dev setup:

## 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt  # optional tooling/tests
```

## 2. Capture a fresh auction request

1. Run mitmproxy and capture a Companion App auction search:
   ```powershell
   mitmdump -p 8888 -w companion_collect/savedFlows/fresh_capture.mitm
   ```
2. On the device/emulator, configure the proxy and perform a single auction search.

## 3. Extract auth + session context

```powershell
python scripts/refresh_session_ticket.py --once
python scripts/rebuild_auth_pool.py
```

These commands populate `research/captures/current_session_context.json` and `research/captures/auth_pool.json`.

## 4. Run the pipeline

```powershell
python scripts/run_auction_pipeline.py
```

The pipeline publishes normalized auctions to Redis (`COMPANION_REDIS_URL`) and upserts into Postgres (`COMPANION_POSTGRES_DSN`).

## 5. Run tests (optional)

```powershell
pytest
```

That is all you need for the trimmed-down service. Check `docs/COMPLETE_AUCTION_COMMANDS.md` and `docs/m26_auction_pipeline_plan.md` for deeper background.
