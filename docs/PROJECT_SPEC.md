# Project Specification: M26 Auction Pipeline

**Project Branch**: `main`  
**Created**: 2025-10-12  
**Status**: Draft  
**Input**: Automate real-time auction data collection from Madden 26 APIs, building on codebase analysis (data ingestion/normalization/storage; priorities: auth/streaming; constraints: API/auth dependencies) and PROJECT_CONSTITUTION.md principles.

## Introduction

The M26 Auction Pipeline automates the collection, processing, and storage of real-time auction data from Madden 26 game APIs. It supports live streaming and batch runs, ensuring reliable data flow for analysis. This spec draws from existing codebase (e.g., companion_collect/pipelines/auction_pipeline.py, scripts/run_auction_pipeline.py) and QUICK_START.md, emphasizing modularity for extensibility.

## User Scenarios & Testing

User stories are prioritized as independent journeys (P1 highest), each testable standalone for MVP viability.

### User Story 1 - Initial Setup and Run Pipeline (Priority: P1)

As an operator, I want to configure and execute the auction data pipeline to ingest initial auction listings.

**Why this priority**: Core functionality for data bootstrapping; enables all downstream analysis.

**Independent Test**: Run `python scripts/run_auction_pipeline.py` with env vars; verify auctions stored in Postgres/Redis via queries.

**Acceptance Scenarios**:

1. **Given** valid env vars (e.g., DB creds, auth pool), **When** pipeline runs, **Then** fetches and normalizes auctions without errors.
2. **Given** invalid auth, **When** pipeline runs, **Then** logs error and retries per constitution's reliability principle.

---

### User Story 2 - Live Streaming Auction Updates (Priority: P1)

As a user, I want real-time auction data streaming for monitoring market changes.

**Why this priority**: Enables low-latency insights; aligns with efficiency principle.

**Independent Test**: Execute `python scripts/run_live_stream.py`; check STREAMING_QUICK_START.md outputs for continuous updates.

**Acceptance Scenarios**:

1. **Given** active session, **When** stream runs, **Then** polls APIs (via companion_collect/api/strategies/m26_strategy.py) and upserts deltas to storage.
2. **Given** network interruption, **When** stream resumes, **Then** recovers state without data loss.

---

### User Story 3 - Auth Management and Refresh (Priority: P2)

As an admin, I want automated auth handling to maintain pipeline uptime.

**Why this priority**: Prevents downtime from token expiry; supports scalability.

**Independent Test**: Run `python scripts/refresh_session_ticket.py`; validate new tickets in auth pool (companion_collect/auth/auth_pool_manager.py).

**Acceptance Scenarios**:

1. **Given** expiring tickets, **When** pool rotates, **Then** selects valid auth without interrupting runs.
2. **Given** auth failure, **When** rebuild runs (`python scripts/rebuild_auth_pool.py`), **Then** regenerates pool from captured traffic.

---

### User Story 4 - Error Recovery and Maintenance (Priority: P3)

As an operator, I want tools for error handling and weekly maintenance.

**Why this priority**: Ensures long-term reliability; secondary to core data flow.

**Independent Test**: Simulate errors in tests/test_auction_pipeline.py; confirm retries and logging.

**Acceptance Scenarios**:

1. **Given** API rate limit, **When** collector retries, **Then** backs off exponentially per constitution.
2. **Given** storage outage, **When** pipeline queues data, **Then** syncs on recovery.

### Edge Cases

- What happens on API schema changes? Strategy picker (companion_collect/api/strategies/strategy_picker.py) must adapt via templates (request_templates/madden26_search_auctions.json).
- How does system handle high-volume auctions? Async processing in auction_pipeline.py to prevent overload.

## Requirements

### Functional Requirements

- **FR-001**: System MUST manage auth via pool rotation and ticket refresh (companion_collect/auth/*).
- **FR-002**: System MUST collect auction data using API strategies (m26_strategy.py, request templates).
- **FR-003**: System MUST normalize/validate data (e.g., auction IDs, prices) before storage.
- **FR-004**: System MUST store data via Redis cache and Postgres upserts (companion_collect/storage/*).
- **FR-005**: System MUST support scripted runs: batch pipeline and live streaming (scripts/*.py).
- **FR-006**: System MUST log events and errors for auditing (companion_collect/logging.py).

### Non-Functional Requirements

- **NFR-001**: Performance: Low-latency polling (<5s intervals) for streaming.
- **NFR-002**: Reliability: Implement retries, circuit breakers; 99% uptime target.
- **NFR-003**: Scalability: Async handling for concurrent API calls; modular for multi-game extension.
- **NFR-004**: Security: Gated experimental auth; env var config only.

### Key Entities

- **Auction**: Represents listings with attributes (ID, player, price, timestamp); relationships to sessions.
- **AuthSession**: Manages tokens/tickets; pooled for rotation.

## Dependencies & Assumptions

- **Dependencies**: Captured traffic for auth/templates (research/captures/); env vars (DB_URL, API_KEYS); Postgres/Redis setup per QUICK_START.md.
- **Assumptions**: Weekly maintenance for auth rebuild; API stable per Madden 26 docs; no direct game access needed.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Pipeline ingests 1000+ auctions/hour without failures.
- **SC-002**: Streaming handles 1min latency; 95% data accuracy via validation.
- **SC-003**: Auth rotation succeeds 100% in tests; reduces manual intervention by 80%.
- **SC-004**: System scales to 10 concurrent streams without >10% CPU spike.