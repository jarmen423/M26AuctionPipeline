# Project Tasks Checklist: M26AuctionPipeline

**Purpose**: This checklist refines the project plan into granular, actionable tasks across phases, emphasizing iterative M26 response validation (e.g., 200 OK with M26 identifiers like "madden-2026-ps5", full ingestion without M25 fallbacks) based on latest [PROJECT_PLAN.md](docs/PROJECT_PLAN.md), [PROJECT_SPEC.md](docs/PROJECT_SPEC.md), [SNALLABOT_ANALYSIS.md](docs/SNALLABOT_ANALYSIS.md), and prior tasks. It supports automated real-time auction data collection from Madden 26 APIs, aligning with FRs for endpoint crafting/testing and constitution principles for efficiency/modularity/retries, with focus on snallabot-driven enhancements (e.g., base64 payloads, auth pooling, templating).

**Created**: 2025-10-12 (Updated)

**Feature**: [PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | [PROJECT_SPEC.md](docs/PROJECT_SPEC.md) | [PROJECT_CONSTITUTION.md](docs/PROJECT_CONSTITUTION.md) | [SNALLABOT_ANALYSIS.md](docs/SNALLABOT_ANALYSIS.md)

**Note**: Updated by `/speckit.tasks` incorporating progression toward M26 API success, snallabot adaptations (e.g., payload/auth enhancements in [SNALLABOT_ANALYSIS.md](docs/SNALLABOT_ANALYSIS.md)), and codebase context (e.g., m26_strategy.py, blaze_auth.py, auction_pipeline.py), prioritizing iterative validation per [PROJECT_ANALYSIS.md](docs/PROJECT_ANALYSIS.md).

## Phase 1: Setup & Authentication (Milestone: Functional M26 auth pool with specificity, FR-001; 1-2 days total)

- [ ] CHK001 Create Python virtual environment and install dependencies from requirements.txt (Owner: developer; Effort: 1h; Deps: None; Alignment: Efficiency principle via async deps like asyncio; Metric: Successful pip install without errors)
- [ ] CHK002 Configure Postgres and Redis databases per QUICK_START.md, including env vars for DB_URL and REDIS_URL (Owner: developer; Effort: 2h; Deps: CHK001; Alignment: Reliability for persistent storage; Metric: Connection tests pass)
- [ ] CHK003 Capture fresh M26 auth traffic using mitmproxy and save to research/captures/, focusing on blaze_id "madden-2026-ps5" and command 9153/9154 (Owner: developer; Effort: 3h; Deps: CHK002; Alignment: Non-intrusive API usage; supports auth pool rebuild; Reference: [SNALLABOT_ANALYSIS.md](docs/SNALLABOT_ANALYSIS.md))
- [ ] CHK004 Implement and test auth pool rebuild in scripts/rebuild_auth_pool.py, integrating companion_collect/auth/auth_pool_manager.py with M26 overrides (Owner: developer; Effort: 2h; Deps: CHK003; Alignment: FR-001, Reliability principle with rotation; Metric: Pool generates valid M26 tokens)
- [ ] CHK017 Update m26_strategy.py with M26_BLAZE_IDS (e.g., {"ps5": "madden-2026-ps5"}) for endpoint specificity (Owner: developer; Effort: 2h; Deps: CHK004; Alignment: SPEC FR-002 endpoint crafting, CONSTITUTION modularity, SNALLABOT_ANALYSIS recommendations; Metric: Strategy returns M26-specific IDs without fallbacks)
- [ ] CHK018 Enhance request_templates/madden26_search_auctions.json with base64-encoded payloads per snallabot templating (Owner: developer; Effort: 1h; Deps: CHK017; Alignment: SPEC FR-002, CONSTITUTION efficiency, SNALLABOT_ANALYSIS payload enhancements; Metric: Templates validate against M26 schema)
- [ ] CHK021 Validate updated strategy/templates via mitmproxy diff against snallabot captures (Owner: developer; Effort: 2h; Deps: CHK018; Alignment: SPEC FR-002 testing, CONSTITUTION reliability, SNALLABOT_ANALYSIS validation; Metric: Diff confirms M26-specific payloads and 200 OK responses without M25 data)
- [ ] CHK024 Apply M26_BLAZE_IDS and base64 updates to m26_strategy.py/templates, integrating CHK017/018 enhancements (Owner: developer; Effort: 1h; Deps: CHK021; Alignment: SPEC FR-002, CONSTITUTION modularity, SNALLABOT_ANALYSIS templating; Metric: Integrated updates yield M26-specific requests without fallbacks)

## Phase 2: Core Pipeline (Milestone: End-to-end M26 collection/storage without fallbacks, FR-002/FR-004; 2-3 days total)

- [ ] CHK005 Develop auction collector in companion_collect/collectors/auctions.py using m26_strategy.py and request_templates/madden26_search_auctions.json, incorporating delta refresh (Owner: developer; Effort: 4h; Deps: Phase 1; Alignment: SPEC FR-002, CONSTITUTION modularity, SNALLABOT_ANALYSIS delta refresh; Metric: Collects M26 auctions via command 9154)
- [ ] CHK006 Normalize auction data in auction_data/ models with validation for M26 IDs/prices (Owner: developer; Effort: 3h; Deps: CHK005; Alignment: SPEC FR-004 data integrity, CONSTITUTION reliability; Metric: 100% validation pass rate)
- [ ] CHK007 Integrate pipeline in companion_collect/pipelines/auction_pipeline.py for ingestion to storage/postgres.py and redis_cache.py (Owner: developer; Effort: 4h; Deps: CHK006; Alignment: SPEC FR-003/FR-004, CONSTITUTION modularity, SNALLABOT_ANALYSIS storage scaling; Metric: Data persists without M25 mixing)
- [ ] CHK008 Test batch run via scripts/run_auction_pipeline.py, verifying 1000+ M26 auctions stored (Owner: developer; Effort: 2h; Deps: CHK007; Alignment: SPEC NFR-001 low-latency; Metric: No fallback errors)
- [ ] CHK019 Add async retries with exponential backoff in collectors/auctions.py for M26 rate limits (Owner: developer; Effort: 3h; Deps: CHK008; Alignment: CONSTITUTION retries principle, SPEC FR-002, SNALLABOT_ANALYSIS optimizations; Metric: 95% success on retry simulations)
- [ ] CHK020 Test dry-run for 200 OK M26 responses using m26_strategy.py overrides (Owner: developer; Effort: 1h; Deps: CHK019; Alignment: SPEC FR-002 testing, CONSTITUTION efficiency; Metric: Consistent 200 responses with "madden-2026" identifiers, no M25 degradation)
- [ ] CHK022 Integrate delta refresh in companion_collect/auth/blaze_auth.py for auctions (Owner: developer; Effort: 3h; Deps: CHK020; Alignment: SPEC FR-001/FR-005, CONSTITUTION reliability, SNALLABOT_ANALYSIS auth enhancements; Metric: Delta updates maintain valid M26 sessions without full re-auth)
- [ ] CHK023 Run full test pipeline with M26 auth, verifying end-to-end ingestion (Owner: developer; Effort: 2h; Deps: CHK022; Alignment: SPEC FR-002/FR-004, CONSTITUTION modularity; Metric: 100% M26 data ingestion, no fallbacks)
- [ ] CHK025 Enhance blaze_auth.py with delta refresh and retries, building on CHK022 (Owner: developer; Effort: 2h; Deps: CHK023; Alignment: SPEC FR-001, CONSTITUTION retries/reliability, SNALLABOT_ANALYSIS auth pooling; Metric: Improved session stability with 99% uptime in simulations)
- [ ] CHK026 Execute dry-run test pipeline, log responses for M26 verification (build on CHK020/023; Owner: developer; Effort: 2h; Deps: CHK025; Alignment: SPEC FR-002 testing, CONSTITUTION efficiency; Metric: 80%+ M26 data success rate, confirmed via logs/parsing)

## Phase 3: Streaming & Testing (Milestone: Live M26 runs with validation, FR-005; 2 days total)

- [ ] CHK009 Implement async streaming in scripts/run_live_stream.py with polling <5s intervals and M26 delta refresh (Owner: developer; Effort: 4h; Deps: Phase 2; Alignment: SPEC FR-005, CONSTITUTION efficiency, SNALLABOT_ANALYSIS streaming; Metric: Streams M26 updates in real-time)
- [ ] CHK010 Add error recovery (retries, backoff) in auction_pipeline.py for M26-specific rate limits (Owner: developer; Effort: 3h; Deps: CHK009; Alignment: NFR-002 reliability, Non-intrusive usage; Reference: SNALLABOT_ANALYSIS.md)
- [ ] CHK011 Write integration tests in tests/test_auction_pipeline.py and test_auth_pool_manager.py covering M26 user stories (e.g., blaze_id injection) (Owner: developer; Effort: 4h; Deps: CHK010; Alignment: Comprehensive logging for auditing; Metric: 95% coverage)
- [ ] CHK012 Validate streaming via STREAMING_QUICK_START.md, ensuring <1min latency for M26 data (Owner: developer; Effort: 2h; Deps: CHK011; Alignment: SC-002 data accuracy; Metric: No fallback occurrences)
- [ ] CHK027 Debug/iterate on failures using mitmproxy diffs (Owner: developer; Effort: 1h; Deps: CHK012; Alignment: SPEC FR-002 testing, CONSTITUTION reliability, SNALLABOT_ANALYSIS validation; Metric: Resolved failures yield 90%+ M26 success in iterated runs)

## Phase 4: Deployment & Monitoring (Milestone: Production scaling for M26, NFR-003; 1-2 days total)

- [ ] CHK013 Enhance logging in companion_collect/logging.py for M26 events/errors (e.g., request failures) (Owner: developer; Effort: 2h; Deps: Phase 3; Alignment: SPEC FR-006, CONSTITUTION maintainability, SNALLABOT_ANALYSIS monitoring; Metric: Logs capture blaze_id usage and validation failures)
- [ ] CHK014 Set up weekly cron for auth rebuild and monitor M26 API changes via strategy_picker.py (Owner: developer; Effort: 3h; Deps: CHK013; Alignment: Maintenance principles, Scalability; Reference: m26_strategy.py)
- [ ] CHK015 Dockerize pipeline for server deployment, testing concurrent M26 streams (Owner: developer; Effort: 4h; Deps: CHK014; Alignment: NFR-003/004, Security via env gating; Metric: Handles 10+ concurrent without fallbacks)
- [ ] CHK016 Profile performance with pytest, targeting <100ms auth overhead for M26 requests (Owner: developer; Effort: 2h; Deps: CHK015; Alignment: SC-001 ingestion rate; Metric: Meets latency thresholds)

## Assignments & Effort Summary
- **Owner**: Primary developer (solo or lead); escalate to team for Phase 4 scaling.
- **Total Effort**: ~60h across phases (added 6h for new M26 validation/implementation tasks); buffer 20% for risks like API changes.
- **Dependencies**: Sequential phases; parallel M26 testing in Phases 2-3.

## Completion Criteria
- [ ] All checklists marked [x] with passing tests (95% coverage).
- [ ] Pipeline achieves SC-001 to SC-004 metrics (e.g., 1000+ M26 auctions/hour, 99% uptime without fallbacks, validated 200 OK responses with M26 identifiers).
- [ ] Docs updated (e.g., QUICK_START.md); no violations of constitution principles.
- [ ] Final validation: End-to-end run stores live M26 data without errors or M25 fallbacks, confirmed via mitmproxy diffs and response parsing.

## Notes
- Mark progress: [ ] pending, [-] in progress, [x] completed.
- Reference: Use FR-*/NFR-*/SC-* for traceability; update on discoveries (e.g., new M26 endpoints in SNALLABOT_ANALYSIS.md).
- Risks: Mitigate auth expiry with CHK004; monitor request precision via CHK017/CHK020/CHK024.
- New/Updated Tasks: Enhanced CHK017-023 with M26 focus; added CHK024 (strategy/template integration), CHK025 (auth enhancements), CHK026 (dry-run verification), CHK027 (debug iterations) pending for iterative M26 adaptations and pipeline testing.

(Word count: 950)