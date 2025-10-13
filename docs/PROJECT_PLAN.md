# Implementation Plan: M26AuctionPipeline

**Branch**: `main` | **Date**: 2025-10-12 | **Spec**: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)
**Input**: Project specification from docs/PROJECT_SPEC.md and constitution from docs/PROJECT_CONSTITUTION.md

**Note**: This plan fulfills the /speckit.plan command, providing a phased roadmap for automated real-time auction data collection from Madden 26 APIs. It draws from prior codebase analysis (ingestion/normalization/storage priorities: auth/streaming) and ensures alignment with principles like reliability and modularity.

## Summary

The M26AuctionPipeline automates ingestion, normalization, and storage of real-time auction data from Madden 26 APIs, enabling efficient data collection for analysis. High-level approach: Phased rollout starting with authentication setup, building core pipeline components, integrating streaming, and scaling to production with monitoring. This adheres to functional requirements (e.g., FR-001: Secure auth handling) and non-functional goals (e.g., low-latency processing <200ms).

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: asyncio, requests, psycopg2, redis-py, pytest  
**Storage**: PostgreSQL (persistent auction data), Redis (caching sessions/tokens)  
**Testing**: pytest (unit/integration for collectors, auth, pipelines)  
**Target Platform**: Linux server (deployable via Docker)  
**Project Type**: Single CLI pipeline (monorepo structure)  
**Performance Goals**: Process 1000+ auctions/sec, <100ms auth overhead  
**Constraints**: API rate limits (mitigated by pooling), auth expiration (weekly rebuilds)  
**Scale/Scope**: Handle live streams (100k+ auctions/day), integrate with existing scripts like run_auction_pipeline.py

## Constitution Check

*GATE: Passes pre-implementation checks.* Aligns with PROJECT_CONSTITUTION.md: Reliability (redundant auth strategies), Modularity (separated collectors/storage), Efficiency (async processing), Maintainability (clear docs like QUICK_START.md).

## Project Structure

### Documentation
```
docs/
├── PROJECT_CONSTITUTION.md  # Principles
├── PROJECT_SPEC.md          # Requirements/use cases
├── PROJECT_PLAN.md          # This file (phased roadmap)
├── QUICK_START.md           # Setup guide
└── m26_auction_pipeline_plan.md  # Legacy notes (archive if redundant)
```

### Source Code (repository root)
```
auction_data/                # Core models/normalization
companion_collect/           # Collectors, auth, pipelines
├── auth/                    # blaze_auth.py, auth_pool_manager.py
├── collectors/              # auctions.py
├── pipelines/               # auction_pipeline.py
├── storage/                 # postgres.py, redis_cache.py
└── api/strategies/          # m26_strategy.py
scripts/                     # Entry points: run_auction_pipeline.py, rebuild_auth_pool.py
tests/                       # pytest coverage
```

**Structure Decision**: Leverage existing monorepo for modularity; extend companion_collect/ for new phases without restructuring.

## Phases and Milestones

### Phase 1: Setup & Authentication (1-2 days)
- Milestone: Functional auth pool (FR-001). Rebuild via scripts/rebuild_auth_pool.py; integrate mitmproxy for captures.
- Dependencies: Env config (Postgres/Redis setup per QUICK_START.md).

### Phase 2: Core Pipeline (2-3 days)
- Milestone: End-to-end collection/storage (FR-002: Data ingestion). Implement auction_pipeline.py integration.
- Dependencies: Phase 1 auth; normalize via auction_data/.

### Phase 3: Streaming & Testing (2 days)
- Milestone: Live runs with pytest validation (FR-003: Real-time processing). Test scripts/live_auction_stream.py.
- Dependencies: Phase 2; add async streaming.

### Phase 4: Deployment & Monitoring (1-2 days)
- Milestone: Production scaling (NFR-001: Reliability). Add logging, error handling; deploy to server.
- Dependencies: All prior; tools like Docker for scaling.

## Timeline and Resources

Total: 6-9 days. Resources: Python async for streaming, Postgres/Redis for storage, mitmproxy for API research. Team: 1-2 devs; dependencies on Madden API stability.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Auth expiration | Weekly pool rebuilds via cron job on auth_pool_manager.py |
| API changes | Fallback strategies in strategy_picker.py; monitor via captures/ |
| Data loss | Redundant storage (Postgres + Redis); transaction logging |
| Performance bottlenecks | Async optimizations; pytest profiling |

## Complexity Tracking

No violations; plan adheres to constitution simplicity (e.g., single pipeline vs. microservices).

*Word count: 548*