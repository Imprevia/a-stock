## Why

The production `industry-ranking` collector currently reuses the fixed Fuyao capability revision as the catalog primary key, then removes catalog relations whose daily market fields are all null before calculating the catalog checksum. A normal day-to-day change in catalog content or live-field availability therefore attempts to attach different content to the same immutable revision, fails with `conflicting THS catalog revision checksum`, and blocks `sector-turnover` and `sector-breadth` even when most same-day evidence is usable.

## What Changes

- Separate the fixed provider capability revision from an immutable THS catalog observation revision derived from provider, capability revision, Shanghai trading date, and the canonical checksum of the complete four-tag catalog.
- Calculate catalog counts and checksum before daily snapshot reconciliation. Daily missing market values MUST NOT remove or rename catalog relations or change catalog identity.
- Distinguish a missing, duplicated, or wrong-date snapshot identity from a same-date row whose market fields are all null. Identity/date failures remain fail-closed; all-null market rows are retained as explicit row-level insufficient evidence, are ranked last with nullable values, and do not create fabricated or all-null bars.
- Allow compatible partial `industry-ranking` evidence to feed `sector-turnover` and `sector-breadth`. Turnover uses only proven bars; breadth excludes unrankable rows and becomes insufficient only when a classification lacks enough valid candidates or required member evidence.
- Expose stable reason codes, bounded missing-code diagnostics, coverage counts, and upstream dependency details so the collection page explains partial or blocked outcomes instead of showing only “失败，暂无数据” or “依赖阻塞”.
- Preserve all legacy catalog revisions, rankings, bars, collection attempts, and failed/blocked audit records verbatim. The repair is additive and introduces one narrow PostgreSQL migration that removes the redundant `UNIQUE (provider, capability_revision, checksum, fetched_at)` constraint so date-addressed observations cannot collide; it does not rewrite history.

## Capabilities

### New Capabilities

- `ths-catalog-revision-integrity`: Defines immutable THS catalog observation identity, complete-catalog checksums, partial daily market-fact semantics, compatible downstream consumption, and append-only legacy preservation.

### Modified Capabilities

- `market-data-collection-management`: Makes compatible partial THS results valid dependency inputs and requires structured, provider-free diagnostics for partial, insufficient, failed, and blocked task outcomes.

## Impact

- Backend: THS domain models and ranking logic, Fuyao adapter construction and normalization, collection candidates/committers, dependency coordination, PostgreSQL repositories, local queries, API schemas, and Chapter 01 materialization.
- Frontend: collection status types/view models and the data-management/sector views that present coverage, missing codes, and dependency reasons.
- Data: new date-and-content-addressed revision rows coexist with the legacy fixed revision; no existing row is updated or deleted. PostgreSQL advances to schema version 10 / Alembic `0007_ths_catalog_identity`, whose ID fits the default 32-character Alembic version column and whose only structural change is dropping the redundant non-date uniqueness constraint.
- Operations: ordinary GET paths remain provider-free. Production rollout adds a controlled same-image/manual-off freeze and requires clean reviewed source plus imported/runtime manifest-digest verification for the immutable candidate. Real provider probes, production backup/deployment, targeted after-market recollection, capability promotion, and schedule changes remain separately authorized operations.
- Documentation and verification: update the active execution plan, architecture, product specification, runbook, repository mapping, status, OpenAPI/TypeScript contracts, offline fixtures, backend/frontend tests, OpenSpec validation, and docs-contract evidence.
