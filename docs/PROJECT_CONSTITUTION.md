# PROJECT_CONSTITUTION.md

## Introduction

The M26AuctionPipeline project automates the collection, processing, and storage of auction data from Madden 26 APIs. This constitution defines core principles to ensure reliability, efficiency, and maintainability. It aligns with the project's architecture as outlined in [m26_auction_pipeline_plan.md](m26_auction_pipeline_plan.md) and setup instructions in [QUICK_START.md](QUICK_START.md). Principles emphasize auction-specific focus, non-intrusive API interactions, and modular design.

## Core Principles

- **Reliability in Authentication and Data Handling**: Prioritize robust auth mechanisms using captured traffic for templates and pools, ensuring session validity to prevent data loss (see `companion_collect/auth/`).
- **Efficiency in Data Ingestion**: Optimize polling and streaming for real-time auction data, leveraging async patterns for scalability without overwhelming APIs.
- **Auction-Specific Scope**: Focus exclusively on auction endpoints; exclude broader game features to maintain simplicity and reduce complexity.
- **Data Integrity and Validation**: Enforce strict validation at each layer to guarantee accurate normalization and storage, using structured schemas.
- **Modular Decoupling**: Maintain independent layers (auth, collectors, pipelines, storage) for flexibility; experimental features (e.g., auth generation) gated via environment variables.
- **Non-Intrusive API Usage**: Adhere to rate limits through backoff strategies and pool rotation, avoiding detection or bans.
- **Comprehensive Logging**: Implement structured logging across all operations for traceability and debugging.

## Implementation Guidelines

- Depend on captured traffic in `research/captures/` for auth and request templates (e.g., `request_templates/madden26_search_auctions.json`).
- Use async Python patterns in collectors (`companion_collect/collectors/auctions.py`) and pipelines (`companion_collect/pipelines/auction_pipeline.py`) for concurrent operations.
- Integrate storage backends like PostgreSQL (`companion_collect/storage/postgres.py`) and Redis (`companion_collect/storage/redis_cache.py`) with validation hooks.
- Gate non-core features behind env vars to preserve stability; reference [STREAMING_QUICK_START.md](STREAMING_QUICK_START.md) for deployment.
- Follow Speckit templates in `.specify/` for new specs, ensuring formal language and checklists.

## Maintenance Principles

- Conduct weekly auth pool rebuilds via `scripts/rebuild_auth_pool.py` to sustain reliability.
- Monitor API changes through regular traffic captures and update strategies in `companion_collect/api/strategies/`.
- Perform routine validation of data flows using tests in `tests/` to uphold integrity.
- Review and refactor modular layers annually, prioritizing decoupling and efficiency metrics.

This constitution serves as the guiding framework, ensuring the pipeline remains focused, scalable, and resilient. (Word count: 378)