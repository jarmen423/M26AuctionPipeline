# Companion Auth Refresh Execution Plan

_Last updated: 2025-10-07_

## Goal
Produce fresh `messageAuthData` values (`authCode`, `authData`, `authType`) for Madden Companion App Blaze requests so our ingest pipeline can poll commands such as `Mobile_SearchAuctions` without relying on captured tokens.

## Status Snapshot
- **Captures available:** `mutdashboard.comApp/NewUpstreamSource/*_flow.json` holding raw request/response pairs including valid auth bundles.
- **Template refreshed:** `request_templates/mobile_search_auctions.json` now reflects the Blaze request shape with placeholders for dynamic fields.
- **Helper code:** `companion_collect/auth/blaze_auth.py` stub and `scripts/analyze_message_auth.py` added to drive the reverse-engineering workflow.

## Step-by-Step Plan

| Step | Description | Artifacts / Owners | Notes |
| --- | --- | --- | --- |
| 1 | **Static APK reconnaissance** – pull the current Madden Companion APK, decompile with JADX, and locate classes building `requestInfo` / `messageAuthData`. | TODO | Capture fully qualified class names and method signatures. Export key smali/java snippets into `docs/` for reference. |
| 2 | **Code-path tracing** – map the runtime flow from login → `Mobile_EnterMut` → request builder. Identify inputs (session key, device ID, persona) used to derive auth material. | TODO | Prioritize methods referencing constants `MADDEN-MCA`, `wal/mca/Process`, or `authType` 17039361. |
| 3 | **Dynamic instrumentation** – attach Frida (or equivalent) to an emulator/device, hook `javax.crypto.Cipher`/`Mac` to log algorithm, key, IV/nonce, and plaintext/ciphertext around the auth generation routines. | TODO | Store collected traces under `research/blaze_auth/` (to be created). Use `scripts/analyze_message_auth.py` to compare captured vs live values. |
| 4 | **Algorithm derivation** – from traces determine exact crypto recipe (e.g., AES-GCM, HMAC-SHA256). Document formulas and required inputs (session key, timestamp, sequence numbers, device secrets). | TODO | Record formulas and parameter sizes. Add results to this document once confirmed. |
| 5 | **Python implementation** – implement `companion_collect/auth/blaze_auth.py::compute_message_auth()` returning `AuthBundle` with `authCode`, `authData`, `authType`, `expires_at`. Include deterministic unit tests that recreate captured outputs. | TODO | Use `python -m pytest tests/test_blaze_auth.py` once authored. |
| 6 | **Collector integration** – update `AuctionCollector` to call the helper on each poll (or when expiration nears), refreshing headers/`requestInfo` automatically. | TODO | Ensure graceful fallback/logging when auth refresh fails. |
| 7 | **End-to-end verification** – run the ingest pipeline against Companion endpoints, confirm successful responses and downstream Redis fan-out. | TODO | Capture logs/screenshots and update README once verified. |

## Research Checklist
- [ ] Acquire the Madden Companion APK matching the captured traffic build.
- [ ] Record package/version metadata.
- [ ] Extract relevant smali/java path references (e.g., `messageAuthData`, `Mobile_SearchAuctions`).
- [ ] Hook crypto primitives via Frida and archive logs.
- [ ] Decode logged data with `scripts/analyze_message_auth.py` to validate assumptions.
- [ ] Update this plan with confirmed algorithms and implementation notes.

## Helpful Artifacts
- `mutdashboard.comApp/NewUpstreamSource/search_auction_flow.json`
- `mutdashboard.comApp/NewUpstreamSource/process_flow.json` (contains `Mobile_EnterMut` auth bundle)
- `scripts/analyze_message_auth.py` (JSON utility to inspect captured flows)
- `companion_collect/auth/blaze_auth.py` (implementation stub)


## Next Actions
1. Pull latest Companion APK and drop it under `research/blaze_auth/apk/` (git-ignored).
2. Populate a research log in `docs/companion_auth_notes.md` (create on first update) summarizing static findings.
3. Use the included analysis script to parse captured auth values and prepare test fixtures for future unit tests.

2025-10-08: Bulk requestId extraction attempted using scripts/classify_requestid_histogram.py; no valid requestId values found in current NewUpstreamSource flows (most failed with 'Decrypted payload is not valid UTF-8' or empty/invalid JSON). See requestid_histogram.json for output (empty). Next: try mitmproxyMadden.json if feasible, or validate pipeline against new captures. Once the algorithm is confirmed, circle back to this document and update each step’s status, adding links to code/tests as they land.
