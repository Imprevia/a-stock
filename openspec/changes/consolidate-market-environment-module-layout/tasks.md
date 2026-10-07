## 1. Inventory and governance baseline

- [x] 1.1 Audit the 30 root-level `src/market_environment/*.py` modules and record status, target package, direct/indirect callers, shim responsibility, and deletion prerequisites in `src/market_environment/AGENTS.md`; verify every root module appears exactly once in the inventory.
- [x] 1.2 Reconcile the root-module inventory with `docs/architecture.md`, `docs/repository-guide.md`, `docs/runbooks.md`, and the active execution plan; verify the documented paths and runtime status labels agree without changing API or storage contracts.
- [x] 1.3 Define and document the root-level Python allowlist and the rule that new implementation modules must live under `bootstrap`, `interfaces`, `application`, `domain`, or `infrastructure`; verify the rule is explicit and reviewable.

## 2. Layout and shim architecture gate

- [x] 2.1 Extend `scripts/check_market_environment_architecture.py` with a root-layout check that reports unlisted root modules, missing inventory entries, and invalid target package declarations; verify the current inventory passes.
- [x] 2.2 Add architecture tests for an allowed stable entry point, an unlisted root module, and a compatibility shim containing business logic; verify the tests fail for the representative violations and pass for the current package.
- [x] 2.3 Add an import-without-I/O regression covering the root entry points and shims; verify importing them does not connect to PostgreSQL, create schema, call a provider, or submit executor work.

## 3. Low-risk module relocation

- [x] 3.1 Move or wrap pure calculation modules into the appropriate `domain/analysis` or `domain/policies` package while preserving stable exports; verify calculation, limits, date, and trading-session focused tests pass.
- [x] 3.2 Move or wrap HTTP DTO/schema implementations under `interfaces/http/schemas` while preserving response aliases and public imports; verify API characterization and OpenAPI contract tests pass.
- [x] 3.3 Move or wrap explicit migration, database compatibility, and maintenance helpers under the appropriate `infrastructure/persistence` or maintenance package; verify migration, date-relabel, and CLI maintenance tests pass without selecting SQLite for normal runtime.

## 4. Provider and application transition

- [x] 4.1 Relocate provider support modules that have no remaining root-level contract into `infrastructure/providers` subpackages, retaining thin root shims where callers still exist; verify provider, capability, shadow, sector, TDX, and Fuyao focused suites pass.
- [x] 4.2 Reduce `collection.py`, `refresh.py`, and related transition modules to explicit application/infrastructure adapters without reintroducing dataset-specific provider branches; verify collection, command, bootstrap, and provider-free query tests pass.
- [x] 4.3 Migrate internal production imports to target subpackages and document any remaining indirect dependency on `infrastructure/legacy`; verify runtime import tracing shows no unexpected root implementation dependency.

## 5. Shim retirement and compatibility proof

- [x] 5.1 For each root shim, record the remaining callers and removal condition; verify the inventory distinguishes stable external compatibility from internal migration debt.
- [x] 5.2 Remove only shims whose callers have migrated and whose contracts are covered by tests; verify old stable imports either remain intentionally supported or fail only through an explicitly reviewed breaking change.
- [x] 5.3 Run the API, CLI, provider, snapshot, collection, PostgreSQL repository, and architecture compatibility matrix; verify response fields, status codes, exact-date behavior, provider-free reads, failure retention, checksums, lease/fencing, and transaction boundaries are unchanged.

## 6. Documentation and final verification

- [x] 6.1 Update `src/market_environment/AGENTS.md`, `docs/architecture.md`, `docs/repository-guide.md`, `docs/runbooks.md`, and the active plan with final module locations, root allowlist, remaining shims, and migration gaps; verify all referenced paths exist.
- [x] 6.2 Run `python scripts/check_market_environment_architecture.py` and the focused market-environment architecture/bootstrap/query/collection/provider tests; verify all intended checks pass and skipped external tests are recorded.
- [x] 6.3 Run `python -m pytest tests -q`, `python scripts/check-docs-contract.py --mode=full`, and `git diff --check`; verify no production provider, database, Kubernetes, Helm, or schedule write was performed.
