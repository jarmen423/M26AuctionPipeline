# M26 Auth + Auction Pipeline (Updated Workflow)

Last touched: 2025-10-16

## 1. Mint persona-scoped tokens (only when swapping accounts or refreshing OAuth)

```powershell
python scripts/select_persona.py --update-tokens
```

- Pulls the latest OAuth code from the companion/Snallabot flow.
- Lets you choose the console persona (Xbox persona for MUT).
- Saves two files:
  - `tokens.json` — access/refresh bundle bound to the selected persona.
  - `auction_data/persona_context.json` — blaze/product overrides + persona metadata.

## 2. Generate a WAL session ticket (reusable across probes/pipeline)

```powershell
python scripts/generate_fresh_session.py --skip-utas
```

- Uses the persona context + tokens to call WAL.
- Saves the ticket (and optional akamai cookie) into `auction_data/current_session_context.json`.
- `--skip-utas` avoids the experimental UTAS probe so the ticket is persisted immediately.

## 3. Optional probes while EA stands up new routes

- **Host sweep** — reuse the same ticket to check candidate hosts:
  ```powershell
  python doesPathExistProbe.py
  ```
  Reads the host list from `endpointCheckSummary.md` and tries `/wal/mca*/Process/<ticket>` on each. Useful to spot the first host that returns something other than `<errorcode>404</errorcode>`.

- **Command sweep** — verify which Blaze command IDs still respond:
  ```powershell
  python probe_auction_commands.py
  ```
  Writes a timestamped snapshot to `probe_auction_commands.json` with status/snippets for the MUT commands (9153/9154/9157, etc.).

## 4. Run the auction collector once a ticket exists

```powershell
python scripts/run_auction_pipeline.py
```

- Collector loads the same `tokens.json` + `current_session_context.json` and posts `Mobile_SearchAuctions` (and eventually `RefreshAuctionDetails`, etc.) to WAL.
- If the Process endpoint is still a 404, the collector logs the response and exits—rerun after EA enables the route.

## Quick reference

| Step | CLI | Notes |
|------|-----|-------|
| Mint persona tokens | `select_persona.py --update-tokens` | Only when changing accounts or after `exchange_oauth_code.py` |
| Mint WAL ticket | `generate_fresh_session.py --skip-utas` | Ticket survives multiple requests; regenerate on auth failure |
| Host/path probe | `doesPathExistProbe.py` | Uses resolved hosts list |
| Command probe | `probe_auction_commands.py` | Dumps results to JSON for comparison |
| Full collector | `run_auction_pipeline.py` | Requires ticket + working Process route |

## Reminders

- Updating tokens with `exchange_oauth_code.py` _invalidates_ the persona binding — always follow up with `select_persona.py --update-tokens` before minting a new ticket.
- `current_session_context.json` is the single source for the session ticket; delete it if you want to force `SessionManager` to generate a fresh ticket on the next run.
- Keep an eye on `ak_bmsc_cookie`; if EA bumps Akamai gates, grab the new cookie via the official app and drop it in `persona_context.json` or `current_session_context.json` before running collectors.
