## 1. Planning And Documentation Baseline

- [x] 1.1 Create `docs/exec-plans/active/precompute-market-data-snapshots.md`, add it to the active index, include every required plan field, and record the current full-snapshot failure plus breadth cold-load timing as baseline evidence; verify the plan is discoverable from `docs/exec-plans/active/_index.md`.
- [x] 1.2 Update `docs/architecture.md`, `docs/product-specs/market-environment-dashboard.md`, and `docs/runbooks.md` with the persistent snapshot boundary, dataset-specific acquisition, cache metadata, refresh command, storage location, and rollback path before editing code; verify `python scripts/check-docs-contract.py --mode=fast` passes or record the explicit blocker in the plan.

## 2. Persistent Snapshot Store

- [x] 2.1 Implement canonical snapshot records and an idempotent SQLite schema under a configurable `.artifacts/market-environment/` path; verify unit tests cover initialization, atomic upsert, checksum validation, schema versioning, and exact `(dataset, as_of)` lookup.
- [x] 2.2 Implement refresh leases with owner, acquisition time, and bounded expiry; verify two independent store instances cannot hold the same live lease and that an expired lease can be reclaimed.
- [x] 2.3 Implement dataset freshness evaluation for short-lived current-day entries and settled after-market entries; verify tests distinguish fresh, stale, missing, and settled exact-date snapshots without consulting the network.
- [x] 2.4 Implement configurable retention/pruning that never removes a snapshot still needed by an active refresh; verify date-boundary and lease-protection tests pass.

## 3. Dataset-Specific Providers

- [x] 3.1 Split breadth acquisition from active-direction acquisition and route breadth directly to the validated sorted-page algorithm; verify provider tests assert that breadth refresh never calls `_fetch_eastmoney_stock_snapshot` and still returns exact counts and median semantics.
- [x] 3.2 Add a turnover-ranked Top-N active-direction collector with required-field, ordering, and minimum-sample validation; verify fixture tests reproduce the documented top-30 cluster and top-10 display output using one ranked provider request.
- [x] 3.3 Preserve shared Eastmoney limiter, historical-date restrictions, null semantics, and provider warnings across the split collectors; verify existing provider and service contract tests continue to pass.

## 4. Refresh And Precomputation Workflow

- [x] 4.1 Implement a refresh coordinator that collects, derives, validates, checksums, and independently commits configured datasets while retaining the last successful entry on failure; verify tests cover successful, partial, failed, and forced refresh runs.
- [x] 4.2 Add the cross-platform `python -m src.market_environment.cli snapshots refresh` command with `--as-of`, dataset selection, and `--force`; verify CLI tests assert structured output contains dataset, source, observations, duration, cache result, and final quality.
- [x] 4.3 Enforce settlement-time and exact-market-date guards for current-snapshot providers; verify pre-settlement or mismatched-date runs are rejected unless explicitly forced and historical requests never receive current data.

## 5. Service And API Integration

- [x] 5.1 Change Chapter 01 service loading to prefer exact-date persistent snapshots and compose `summary` from independent cached datasets; verify a newly constructed service instance reuses stored breadth and active-direction results with zero provider calls.
- [x] 5.2 Implement stale-while-revalidate and SQLite-backed single-flight behavior for stale and cold entries; verify concurrent same-key requests issue at most one provider refresh, stale hits return immediately, and abandoned leases recover.
- [x] 5.3 Add optional `cacheState`, `snapshotFetchedAt`, `refreshing`, and `refreshWarning` quality fields without changing existing endpoint paths or required fields; verify current response models and compatibility tests accept consumers that ignore the new metadata.
- [x] 5.4 Retain the existing in-memory core cache independently from dataset snapshot freshness and provide a documented configuration switch to disable persistent snapshots for rollback; verify both enabled and disabled modes pass API tests.

## 6. Observability And Performance

- [x] 6.1 Add structured phase timings for cache lookup, lease wait, provider collection, derivation, validation, and store write; verify log-capture tests assert the fields for cache-hit, refresh-success, and refresh-failure paths.
- [x] 6.2 Add a deterministic warm-read performance test using fixture providers and local SQLite; verify a cached Chapter 01 request makes zero external calls and completes within the specified 500 ms acceptance threshold.
- [x] 6.3 Run one explicit after-market real-data refresh and compare cold refresh time with warm API time, recording sources, request counts, observation counts, quality states, and timings in the active plan Completion Evidence.

## 7. Documentation And Gates

- [x] 7.1 Update `docs/status.md`, the active plan Status/Completion Evidence/Remaining Gaps/Next Step, and any final runbook details to match implemented behavior; verify code-to-document mappings are complete.
- [x] 7.2 Run the focused snapshot/provider/service/API tests and then the full backend suite; verify all tests pass with external network access disabled except the explicit after-market evidence command.
- [x] 7.3 Run the frontend production build and `python scripts/check-docs-contract.py --mode=full`; record command outputs and any residual multi-host cache limitation in the active plan before marking the implementation complete.
