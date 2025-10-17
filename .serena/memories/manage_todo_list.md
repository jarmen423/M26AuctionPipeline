# TODO List
- [x] Align message auth generation with snallabot (random nonce + MD5 authData/authCode, enforce requestId sequencing).
- [x] Enforce Madden 26 headers and remove legacy fallbacks in auction collector requests.
- [x] Audit logging/context writes to ensure session context persists ak_bmsc cookie and persona fields consistently.
- [x] Update docs/runbooks to reflect new auth flow and header expectations once code changes are in place.
- [x] Strip legacy entitlement usage from `scripts/exchange_oauth_code.py`.
- [x] Rewrite session-context persistence to emit only the minimal fields required by the collector.
- [x] Update persona-selection flow and helpers in the exchange script to align with the new context shape.
- [x] Add logging/printout to show the new minimal context after running the exchange script.
- [ ] Re-run the exchange script end-to-end and verify the updated context works with session generation.
