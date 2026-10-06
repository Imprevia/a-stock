## Context

See `proposal.md` for motivation. The current package is a working modular monolith in deployment terms, but not in code structure: `api.py` constructs runtime dependencies during import, `MarketEnvironmentService` mixes live acquisition and provider-free reads, `CollectionCoordinator` constructs analysis services internally, `MarketDataProvider` owns unrelated dataset fallback chains, and `SnapshotStore` combines several repositories with SQLite/PostgreSQL compatibility and schema initialization.

The refactor must preserve the following existing contracts:

- `src.market_environment.api:app` and `python -m src.market_environment.cli ...` remain valid entry points.
- Existing HTTP paths, response fields and Pydantic validation remain compatible.
- Normal GET and status paths remain provider-free and exact-date only.
- Five dataset tasks remain independently committed and retain same-date success after failure.
- PostgreSQL lease/fencing, checksum, materialized aggregate, quality state and provider fallback behavior remain unchanged.
- Runtime schema changes remain Alembic-managed; production data, deployments and provider feature flags are outside this change.
- The current deployment boundary remains one Dashboard process/Pod and one primary PostgreSQL instance.

The repository currently has more than 340 focused market-environment tests. They are the characterization baseline, but many tests instantiate concrete classes or monkeypatch module globals, so test seams must be introduced before the corresponding global objects are removed.

## Goals / Non-Goals

**Goals:**

- Establish an enforceable inward dependency direction rather than only reorganizing files.
- Make application startup, shutdown and dependency construction explicit and testable.
- Separate provider-free query use cases from provider-backed collection commands.
- Give each dataset an isolated collector and fallback chain.
- Split persistence responsibilities without weakening atomic operations, lease fencing or exact-date integrity.
- Introduce typed internal results at cross-layer boundaries while preserving public response models.
- Allow each migration stage to be verified and reverted independently.

**Non-Goals:**

- No microservices, distributed queue, new daemon, new network boundary or second deployment unit.
- No change to API routes, JSON naming, market formulas, provider priority, quality semantics or feature flag defaults.
- No asynchronous rewrite of synchronous provider clients.
- No database redesign, destructive migration or production SQLite fallback.
- No real-provider smoke, production deployment, schedule activation or production database write.
- No requirement that every private helper become a class; pure calculations remain functions where appropriate.

## Decisions

### 1. Use a layered modular monolith with dataset-oriented collectors

The target dependency direction is:

```text
interfaces/http ----> application ----> domain
       |                   ^               ^
       |                   |               |
       +---- bootstrap ----+               |
                    |                      |
                    +---- infrastructure --+
```

Only `bootstrap` may know concrete implementations from all layers. `domain` contains market concepts and pure policies and imports no FastAPI, SQLAlchemy, requests or infrastructure module. `application` coordinates use cases through ports. `interfaces` maps HTTP/CLI inputs and outputs. `infrastructure` implements persistence, provider and executor ports.

Dataset acquisition remains vertically separated inside infrastructure/application boundaries because `core`, `breadth`, `limits`, `sectors` and `activeDirection` have different date capabilities, validation rules and fallback chains.

Proposed package shape:

```text
src/market_environment/
  bootstrap/
    app.py
    container.py
    settings.py
  interfaces/
    http/
      routers/
      dependencies.py
      errors.py
      schemas/
    cli/
  application/
    ports/
    queries/
    commands/
    collection/
  domain/
    models/
    analysis/
    policies/
  infrastructure/
    persistence/postgres/
    persistence/sqlite_import/
    providers/
    execution/
```

Existing public modules remain as transitional compatibility facades until all repository callers and tests use the new paths.

Alternatives considered:

- A conventional `controllers/services/repositories` split was rejected because it would preserve the current cross-domain service and provider classes under different filenames.
- Microservices were rejected because all workflows share one exact-date transaction/lease model and one deployment; new network boundaries would add failure modes without solving the immediate maintainability issue.
- A framework replacement was rejected because FastAPI, Pydantic and SQLAlchemy already satisfy the runtime needs.

### 2. Make `create_app` and a small composition container the only HTTP composition root

`bootstrap.app.create_app(settings=None, overrides=None)` creates the FastAPI object, installs middleware and routers, and registers a lifespan handler. The lifespan handler opens runtime resources and closes the bounded executor/database resources. `src.market_environment.api` remains a thin compatibility entry point exporting `app = create_app()` so the documented Uvicorn command does not change.

Creating the FastAPI object at import time is acceptable; opening a database connection, creating schema, creating provider clients or starting executors is not. These resources are created lazily by lifespan or supplied as test overrides.

The container is an explicit dataclass/factory, not a service-locator framework. Router dependency functions read typed use cases from `request.app.state` and tests construct an app with fake ports. CLI commands reuse the same lower-level container builder but do not create a FastAPI application.

Configuration uses a top-level immutable settings object assembled from environment values. Existing specialized configuration objects such as Fuyao and TDX settings remain responsible for their own validation and are composed into the top-level settings. No new dependency-injection or settings library is introduced.

Alternative considered: module-level singleton replacement hooks. Rejected because they retain import side effects and make resource ownership ambiguous.

### 3. Separate read use cases from collection commands at the type and construction boundaries

Read use cases include:

- market-environment aggregate query;
- core query;
- Chapter 01 section query;
- next-session comparison;
- collection status and run-status query;
- timezone preference query.

Their constructors receive only read repositories, clocks and pure analysis services. They cannot receive a collector registry or provider transport. This makes provider-free GET behavior enforceable by construction, not merely by convention.

Command use cases include starting/executing a collection run, refreshing a dataset, rebuilding an aggregate, updating timezone preferences and migration/admin commands. Only command wiring receives provider-backed collectors and a task executor.

The HTTP POST remains asynchronous from the caller's perspective. A `TaskExecutor` port wraps the existing bounded in-process thread pool; tests use an immediate or no-op executor. This preserves current behavior without introducing Celery or another service.

Alternative considered: one application service exposing both reads and writes. Rejected because the current mixed service is the main route by which provider access can leak into normal reads.

### 4. Introduce typed application results before changing provider internals

Cross-layer values use dataclasses or narrow protocols for:

- exact dataset/date identity;
- collection candidate and collection outcome;
- source, observations, actual date, settled state and warnings;
- quality and cache state;
- run/task transitions;
- lease token and materialization revision.

Pydantic models remain HTTP boundary DTOs. Repository row records remain persistence records. Mapper functions translate between domain/application results, persistence records and API DTOs. Arbitrary provider payload fragments may remain dictionaries inside an adapter initially, but a dictionary is not passed as an undocumented contract between layers.

Migration is seam-first: introduce typed wrappers around existing results, prove equivalent serialization, then move logic. Provider parsing and calculation logic should not be rewritten in the same step as it is relocated.

Alternative considered: convert every existing payload to a full object graph immediately. Rejected because it would create a large behavioral rewrite and make regression attribution difficult.

### 5. Split persistence ports but retain one PostgreSQL unit-of-work boundary

Application ports are separated by responsibility:

- `SnapshotRepository`;
- `CollectionRunRepository` and `CollectionTaskRepository`;
- `LeaseRepository`;
- `TradingSessionRepository`;
- `MaterializedAggregateRepository`;
- `ProviderCapabilityRepository`;
- limit-fact/detail repositories;
- timezone preference repository.

Concrete PostgreSQL repositories share one connection/transaction through a `MarketEnvironmentUnitOfWork` where operations must remain atomic. Lease acquisition, fenced writes, limit fact + manifest writes, task transitions and aggregate compare-and-swap must not be decomposed into unrelated transactions merely because interfaces are split.

The existing `SnapshotStore` becomes a temporary facade delegating to these repositories. Existing tests and migration utilities may continue to construct it while callers are migrated. The facade is removed from runtime wiring only after all application use cases depend on ports.

PostgreSQL runtime construction validates connectivity and schema compatibility but does not call `create_schema`. Alembic remains authoritative for runtime schema migration. SQLite support moves to a clearly named legacy/test adapter and one-time import path; it is never selected as a silent production fallback when `MARKET_ENVIRONMENT_DATABASE_URL` is required.

Alternative considered: retain one universal repository because it simplifies transactions. Rejected because its interface exposes unrelated persistence concerns to every caller; the unit of work preserves transactions without preserving the giant surface.

### 6. Replace `MarketDataProvider` dataset methods with a collector registry

The application defines a `DatasetCollector` port with a dataset identifier and a `collect(as_of)` operation returning a typed candidate/outcome. A registry maps the stable dataset identifiers to collectors:

```text
core            -> CoreCollector
breadth         -> BreadthCollector
limits          -> LimitsCollector
sectors         -> SectorsCollector
activeDirection -> ActiveDirectionCollector
```

Each collector owns its current fallback ordering, date capability, validation and warning construction. Shared HTTP transport, Eastmoney client, Fuyao clients, TDX package client, request gates and normalization helpers remain reusable infrastructure dependencies rather than being reimplemented.

`CollectionCoordinator` is reduced to run/task creation, request validation, lease/fencing, invoking the selected collector, committing or retaining results, aggregate rebuild triggering and parent status derivation. Dataset-specific `if` branches migrate out incrementally.

The first move of each fallback chain is mechanical and covered by existing focused tests; cleanup or algorithm changes are deferred. This protects source attribution, quality statuses and exact warning behavior.

Alternative considered: one provider class per external vendor. Vendor clients remain useful, but they do not by themselves model the product's dataset-specific fallback chains. The collector is the correct application-facing boundary; vendor clients sit below it.

### 7. Split query composition from pure analysis

Pure functions in `calculations.py`, limit normalization and other deterministic algorithms move only when their domain ownership is clear. They are grouped under `domain.analysis` or `domain.policies` and continue to accept explicit values without database/provider access.

Current `MarketEnvironmentService` responsibilities are separated into:

- query use cases that load exact-date records;
- an aggregate composer and materialization command;
- core/index analysis;
- breadth enrichment and history analysis;
- limit ecosystem composition;
- API response mapping.

Historical reads use repository ports and keep exact-date rules. Aggregate composition may read several repositories but cannot invoke collectors. Materialized response validation continues through the existing Pydantic response contract before commit.

Alternative considered: keep `MarketEnvironmentService` as a facade permanently. A short-lived facade is allowed for compatibility, but retaining it as the runtime center would leave the main coupling problem unresolved.

### 8. Preserve public compatibility through thin facades and characterization tests

During migration, the following remain stable:

- Uvicorn and CLI module paths;
- API routes, status codes and response aliases;
- existing stable dataset identifiers;
- public imports used by tests or scripts until their callers migrate;
- database table names, checksums and migration history.

Compatibility facades contain delegation only and no new business logic. Each facade has an explicit removal task and is removed before the change is complete, except the intentionally stable entry-point modules.

Golden response/schema tests compare representative success, partial, missing, degraded and failed-retained payloads. Provider fixture tests compare source, warnings, observations, exact date and quality status before and after collector extraction. Repository contract tests run the same behavioral suite against the SQLite test adapter where applicable and an isolated PostgreSQL fixture for PostgreSQL-only transaction/fencing semantics.

### 9. Enforce architecture with repository-native static checks

A lightweight AST/import check is added to the existing scripts/tests instead of adding an import-linter dependency. It enforces at minimum:

- `domain` does not import FastAPI, SQLAlchemy, requests, application, interfaces or infrastructure;
- `application` does not import concrete PostgreSQL/provider/HTTP implementations;
- infrastructure does not import HTTP routers;
- routers do not instantiate repositories, providers, executors or coordinators;
- query packages do not import collector/provider modules;
- only bootstrap modules assemble concrete implementations.

The gate also checks that `api.py` stays a thin entry point and that runtime code does not call schema-creation helpers. The existing provider-free GET tests remain mandatory because static imports alone cannot prove absence of network calls.

Alternative considered: rely on code review. Rejected because the repository explicitly treats architecture and provider-free reads as enforceable contracts.

### 10. Treat documentation and OpenSpec calibration as part of the migration

Before implementation, the active exec plan records stage boundaries, acceptance, completion evidence, remaining gaps and next step. `docs/architecture.md` is updated before structural code changes, followed by `docs/repository-guide.md`, `docs/runbooks.md`, the market-environment product spec and `docs/status.md` as affected behavior and operational paths are verified.

The accompanying delta spec corrects the durable scheduling capability to PostgreSQL and fail-closed defaults. Historical completed plans remain historical evidence and are not rewritten merely because they mention the former SQLite design.

## Risks / Trade-offs

- **[Risk] A broad file move masks a behavior change** -> Introduce seams first, move one responsibility at a time, and require focused characterization tests before deleting the old path.
- **[Risk] Splitting repositories breaks transaction or fencing atomicity** -> Keep a shared PostgreSQL unit of work and add PostgreSQL-specific concurrency/CAS contract tests before switching runtime wiring.
- **[Risk] Provider fallback source, warning or date evidence drifts** -> Extract one dataset collector at a time without algorithm cleanup and compare complete fixture outcomes, not only numeric payloads.
- **[Risk] Query code regains access to collectors through a general container** -> Give query and command use cases different constructor dependencies and enforce imports statically.
- **[Risk] App factory tests pass while documented Uvicorn entry point breaks** -> Keep `src.market_environment.api:app`, add an import-without-I/O test and exercise the documented startup command in offline verification.
- **[Risk] Compatibility facades become permanent duplicate APIs** -> Track every facade in tasks, prohibit new logic inside facades and make facade removal part of completion acceptance.
- **[Risk] More files initially increase navigation cost** -> Organize around stable responsibilities and dataset names, document the map, and avoid one-class-per-file fragmentation for small pure helpers.
- **[Risk] Test runtime grows substantially** -> Keep fast unit/architecture tests separate from the existing full suite and restrict PostgreSQL concurrency tests to the persistence contract surface.
- **[Trade-off] The in-process executor remains process-local** -> This preserves the current deployment and avoids a new service; PostgreSQL leases remain the cross-trigger duplicate guard within the documented single-process/Pod boundary.
- **[Trade-off] Some dictionaries remain inside provider adapters during early stages** -> Typed cross-layer boundaries deliver most safety while avoiding a risky all-at-once payload rewrite.

## Migration Plan

1. Create the mandatory active exec plan and update architecture/document maps before code changes. Record baseline file metrics, API payload fixtures, provider-free GET behavior, warm-read performance and focused test results.
2. Add settings, container interfaces, application factory and lifespan management while retaining legacy services behind adapters. Keep `api:app` and all routes unchanged.
3. Introduce application ports and typed cross-layer results. Adapt the existing `SnapshotStore`, `MarketDataProvider`, service and coordinator to those ports without moving algorithms yet.
4. Split PostgreSQL repositories and unit of work behind the `SnapshotStore` facade. Move SQLite to the explicit legacy/test/migration adapter and remove runtime `create_schema` calls.
5. Extract dataset collectors in low-risk order: `core`, `breadth`, `activeDirection`, `sectors`, then `limits`. Run the corresponding provider and collection tests after each extraction; `limits` is last because it has the largest membership/fact transaction surface.
6. Split provider-free queries, aggregate composition and domain analysis from `MarketEnvironmentService`; switch routers and CLI to the new use cases.
7. Remove runtime use of legacy facades, migrate remaining tests/imports, then delete dead delegation code while keeping the stable entry-point modules.
8. Add architecture gates, update all mapped documentation and active plan evidence, run OpenSpec validation, focused tests, full pytest and docs-contract full.

No database schema or persisted payload migration is expected. Rollback is stage-local: restore the previous composition/facade wiring for the failed stage while leaving PostgreSQL data untouched. Because this change performs no production deployment or write, operational rollback is not part of apply; a later production rollout requires its own reviewed plan and authorization.

## Open Questions

None that affect scope or task ordering. Fine-grained filenames may be adjusted during implementation as long as the dependency rules, dataset boundaries and compatibility/removal criteria remain unchanged.
