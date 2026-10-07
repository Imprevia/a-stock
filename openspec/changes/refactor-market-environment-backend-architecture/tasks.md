## 1. Governance, contracts, and baseline

- [x] 1.1 Create `docs/exec-plans/active/refactor-market-environment-backend-architecture.md`, add it to the active index, include all required plan fields, stage boundaries, rollback notes and explicit no-production-write scope, and verify `python scripts/check-docs-contract.py --mode=fast` accepts the plan structure.
- [x] 1.2 Update `docs/architecture.md` before code changes with the target layered dependency direction, application composition root, provider-free query boundary, dataset collector boundary and PostgreSQL/SQLite responsibilities; update `docs/repository-guide.md` with the planned package map and verify the documented paths and ownership rules are internally consistent.
- [x] 1.3 Reconcile the fail-closed scheduling and PostgreSQL runtime wording in mapped runbook/product documentation, verify Helm defaults remain `enabled=false` and `suspend=true`, and run the relevant scheduling cases in `tests/test_deployment_manifests.py` without applying a deployment.
- [x] 1.4 Add or freeze characterization fixtures/tests for representative API success, partial, missing, degraded and failed-retained responses, including route paths, aliases, status codes, source, warning, exact-date and quality fields; verify the existing API tests and the new characterization tests pass before structural moves.
- [x] 1.5 Record the pre-refactor module sizes, import coupling, focused market-environment test count, provider-free GET assertions and warm-read timing in the active plan's baseline evidence, and verify no provider, production database or Kubernetes target is accessed while collecting the baseline.

## 2. Application bootstrap and HTTP seams

- [x] 2.1 Create the `bootstrap`, `interfaces`, `application`, `domain` and `infrastructure` package skeleton plus immutable top-level settings composition, and verify importing the skeleton succeeds without constructing a database, provider or executor.
- [x] 2.2 Implement the explicit composition container using existing services behind temporary adapters, with separate read and command dependency groups, and verify unit tests can build the container with fake repositories, collectors, clocks and executors.
- [x] 2.3 Implement `create_app` and FastAPI lifespan ownership for container resources while preserving `src.market_environment.api:app`; verify importing `src.market_environment.api` performs no database connection, schema creation, provider request or worker submission.
- [x] 2.4 Split health, market-environment, collection and timezone-preference routes into routers with typed dependency functions and centralized HTTP error mapping; verify every existing route, method, response model and status code remains unchanged in API tests.
- [x] 2.5 Replace API tests that monkeypatch module-level service/coordinator/executor globals with `create_app` dependency overrides or fake ports, and verify the API suite no longer depends on mutable production singletons.
- [x] 2.6 Add a CLI container builder that reuses the same settings and lower-level factories without constructing FastAPI, and verify representative offline CLI help, capability fixture and scheduled-refresh fake-provider tests retain their output/exit-code contracts.
- [x] 2.7 Add offline entry-point tests for the documented Uvicorn target and CLI module path, verify startup/shutdown closes executor and database resources, and confirm no runtime artifact is created merely by importing either entry point.

## 3. Typed application boundaries and read/write separation

- [x] 3.1 Introduce typed domain/application values for dataset/date identity, collection candidate/outcome, quality/cache metadata, run/task state and materialization revision, and verify round-trip mappers reproduce the existing stored and API payload representations.
- [x] 3.2 Define narrow repository, unit-of-work, dataset-collector and task-executor protocols under application ports without importing concrete FastAPI, SQLAlchemy, requests or provider modules, and verify static import tests cover those restrictions.
- [x] 3.3 Adapt the existing `SnapshotStore`, `MarketDataProvider`, `MarketEnvironmentService` and `CollectionCoordinator` to the new ports without moving algorithms, and verify all focused service, collection and provider tests still pass at this seam-first checkpoint.
- [x] 3.4 Implement provider-free query use cases for full aggregate, core, Chapter 01 section and next-session comparison using only read repositories and pure analysis dependencies; verify network/provider fakes fail the tests if any query attempts collection.
- [x] 3.5 Implement provider-free collection-status and run-status queries plus timezone-preference query/update use cases with explicit read/write ports, and verify status reads remain available when every provider fake raises.
- [x] 3.6 Implement start-run, execute-run, aggregate-rebuild and refresh command use cases plus the bounded in-process `TaskExecutor` adapter, and verify HTTP POST still returns 202 before execution while immediate/no-op executors remain usable in tests.
- [x] 3.7 Switch routers and CLI commands to the new query/command use cases behind compatibility adapters, and verify existing route, CLI JSON and exit-code tests pass before persistence or provider extraction begins.

## 4. Persistence repositories and transaction boundaries

- [x] 4.1 Introduce the PostgreSQL connection factory and `MarketEnvironmentUnitOfWork`, preserving transaction isolation and rollback behavior, and verify runtime construction checks connectivity/schema compatibility without calling `create_schema` or executing DDL.
- [x] 4.2 Extract snapshot, trading-session and provider-capability PostgreSQL repositories from `SnapshotStore`, and verify exact-date isolation, checksum validation, list/read/write and capability report tests against the new adapters.
- [x] 4.3 Extract collection-run, collection-task and core-index-result repositories, preserving legal transitions and restart recovery, and verify the existing collection lifecycle and expired-task tests pass.
- [x] 4.4 Extract lease/fencing repositories while retaining generation/token audit semantics and atomic fenced writes, and verify duplicate acquisition, expiry, renewal, stale-token rejection and fence-event tests, including isolated PostgreSQL concurrency coverage.
- [x] 4.5 Extract materialized aggregate repository and compare-and-swap revision handling under the shared unit of work, and verify conflict retry, checksum and provider-free aggregate read tests pass.
- [x] 4.6 Extract limit membership/fact/detail persistence while keeping manifest/fact/checksum writes in one transaction, and verify limit contract, fixture, matrix, promotion and date-relabel persistence tests pass.
- [x] 4.7 Extract timezone-preference persistence behind its repository port and verify personal/workspace authorization, fallback and PostgreSQL behavior remain compatible.
- [x] 4.8 Convert `SnapshotStore` into delegation-only compatibility facade over the repositories/unit of work, migrate application callers to ports, and verify no new business rule or SQL is added to the facade.
- [x] 4.9 Move SQLite support to an explicitly named legacy/test/migration adapter, require PostgreSQL for normal runtime composition, and verify one-time SQLite import/read fixtures still work while missing production database configuration fails closed rather than selecting SQLite.
- [x] 4.10 Add the non-destructive `0003_provider_capability_reports` Alembic compatibility migration, shared repository contract tests and PostgreSQL-only transaction/fencing tests; verify runtime-required table/index names and schema version 6 are Alembic-managed while persisted checksums and all existing table/payload shapes require no rewrite.

## 5. Dataset collector extraction

- [x] 5.1 Implement the `DatasetCollector` registry with the five stable dataset identifiers and an adapter around the existing provider methods, and verify unknown/duplicate dataset registration fails deterministically while current collection tests remain green.
- [x] 5.2 Extract `CoreCollector`, preserving five-index sub-result isolation, history depth, quote validation, fallback order and same-date retention, and verify core provider/collection fixtures produce equivalent source, warnings, observations and task status.
- [x] 5.3 Extract `BreadthCollector`, preserving Fuyao/TDX/Eastmoney gates, exact-date evidence, stock-universe validation and missing/insufficient semantics, and verify breadth, TDX daily package and stock-universe tests pass unchanged.
- [x] 5.4 Extract `ActiveDirectionCollector`, preserving Eastmoney primary/delay and independently gated TDX-derived fallback behavior, ranking metadata and `fallback-derived` quality, and verify active-direction focused collection tests pass.
- [x] 5.5 Extract `SectorsCollector`, preserving Eastmoney primary/delay, capability-gated Fuyao fallback, optional enrichment, lineage and current-date restrictions, and verify sector, enrichment, shadow and Fuyao collection tests pass.
- [x] 5.6 Extract `LimitsCollector` last, preserving Fuyao/Eastmoney membership merge, date evidence, normalization, facts, promotion dependencies, failure retention and transactional detail writes, and verify all limit contract/fixture/matrix/performance tests pass.
- [x] 5.7 Reduce `CollectionCoordinator` to validation, run/task lifecycle, lease/fencing, registry invocation, persistence, aggregate rebuild triggering and parent status derivation; verify it contains no dataset-specific provider/fallback implementation and the full collection suite passes.

## 6. Query, analysis, and response decomposition

- [x] 6.1 Extract materialized aggregate composition/rebuild into its command/domain service, preserving component revisions, Pydantic validation and conflict retries, and verify aggregate rebuild tests pass with byte-equivalent logical payloads.
- [x] 6.2 Extract core/index analysis and synchronization policies from `MarketEnvironmentService` into pure domain analysis modules, and verify calculation, combination and synchronization tests pass without repository or provider imports.
- [x] 6.3 Extract breadth history, percentile, momentum, index-consistency and width-label analysis behind explicit repository inputs, and verify exact previous-date and insufficient-history tests retain their outputs.
- [x] 6.4 Extract limit ecosystem composition and promotion policies from query orchestration while preserving quality layering and missing evidence rules, and verify the focused limit ecosystem/promotion suites pass.
- [x] 6.5 Move API response assembly into boundary mappers that consume typed application results and existing Pydantic DTOs, and verify golden success/partial/missing/degraded/failed-retained responses remain compatible.
- [ ] 6.6 Switch all query and materialization paths away from `MarketEnvironmentService`, reduce any temporary service facade to delegation only, and verify ordinary GET/status/next-session paths have zero provider calls and warm local reads remain under the existing 500 ms threshold.

## 7. Architecture enforcement and compatibility cleanup

- [ ] 7.1 Add a repository-native AST/import architecture check enforcing the documented layer rules, query/provider separation, bootstrap-only concrete assembly and thin `api.py` entry point, and verify it fails against representative forbidden-import fixtures and passes the refactored package.
- [ ] 7.2 Remove runtime use of `SnapshotStore`, `MarketDataProvider`, `MarketEnvironmentService` and old coordinator compatibility facades, migrate remaining tests/imports, and delete dead delegation code while retaining only intentionally stable API/CLI entry modules.
- [ ] 7.3 Verify the refactored package no longer has the original giant mixed-responsibility modules, record new module-size/import-coupling metrics, and confirm dataset/provider/persistence responsibilities can be located through `docs/repository-guide.md`.
- [ ] 7.4 Run the complete compatibility matrix for API schemas, provider fixtures, exact-date reads, failure retention, lease/fencing, materialized aggregate, scheduling render and import-without-I/O behavior, and record the results in the active plan.

## 8. Documentation and final verification

- [ ] 8.1 Update `docs/architecture.md`, `docs/repository-guide.md`, `docs/runbooks.md`, `docs/product-specs/market-environment-dashboard.md` and `docs/status.md` to the implemented structure and verified operational paths, and verify no documentation claims a runtime SQLite fallback or default-active schedule.
- [ ] 8.2 Run focused market-environment, provider HTTP, deployment manifest and architecture tests; record exact commands/results and any intentionally unrun checks in the active plan.
- [ ] 8.3 Run `python -m pytest tests -q` and resolve all regressions attributable to the refactor without weakening exact-date, quality, provider-free or safety assertions.
- [ ] 8.4 Run `openspec validate refactor-market-environment-backend-architecture --type change --strict --no-interactive` and `python scripts/check-docs-contract.py --mode=full`, and verify both complete successfully.
- [ ] 8.5 Update the active plan's Status, Completion Evidence, Remaining Gaps and Next Step, confirm `git diff --check` and a clean scope review, and explicitly record that no real provider, production database, Kubernetes write, schedule activation or feature-flag rollout was performed.
