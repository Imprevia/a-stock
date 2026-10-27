## Why

The repository has no test ratchet and no working commit gate for tests. Measurement on 2026-10-27 established four facts:

1. **No coverage or ratchet mechanism exists.** `coverage.py` / `pytest-cov` are absent from `requirements.txt` and from the environment; there is no `.coveragerc`, no `pyproject.toml`, no `setup.cfg`, no `tox.ini`, and `pytest.ini` declares markers only. Nothing fails when a test is deleted, weakened, or skipped, and nothing measures which code the suite executes.
2. **The existing local hooks are not mounted.** `git config core.hooksPath` is empty and `.git/hooks/` contains only `*.sample` files. `.githooks/pre-commit` and `.githooks/pre-push` exist but never run, so even the documented docs-contract gate is inactive on a normal checkout.
3. **Interface coverage is incomplete and unmeasured.** Instrumenting `fastapi.routing.APIRoute.handle` across the full suite (`pytest tests`, 1739 tests, exit code 0, 351.3 s) recorded 36 of 39 API operations as actually invoked. `GET /api/health`, `GET /api/v2/market-environment/{as_of}/breadth`, and `GET /api/v2/market-environment/{as_of}/active-direction/workbench` were never called. The first two appear only in a hand-maintained OpenAPI expectation table, which asserts `required <= set(paths)` and therefore only prevents removal; it does not require a new operation to be exercised.
4. **A single-metric gate is already known to be unenforceable.** The full backend suite takes 351.3 s and the frontend suite 22.8 s, while `.githooks/pre-commit` currently completes in 0.16 s. Running everything before every commit would impose roughly six minutes of latency per commit against a history of large, batched commits, which would make the documented escape hatches the default path rather than an exception.

The consequence is that the repository's strong documentation and architecture gates protect documents and imports, but nothing protects the test suite itself. Coverage exists by convention: adding an endpoint without a test, or deleting an inconvenient test, passes every current gate.

## What Changes

- **Mount the hooks as an explicit, verified precondition.** Installing `.githooks` becomes a recorded step with a machine-checkable postcondition, and a hook that cannot run its dependency (for example a missing interpreter) MUST fail or explicitly record the skip instead of silently passing.
- **Close the measured interface-coverage gap.** Add runtime HTTP tests for `GET /api/health`, `GET /api/v2/market-environment/{as_of}/breadth`, and `GET /api/v2/market-environment/{as_of}/active-direction/workbench` before any baseline is recorded, so the ratchet does not freeze the current deficit as the accepted floor.
- **Introduce a test ratchet with an explicit, auditable baseline.** Record a committed baseline over three facts: the executable test inventory, the set of HTTP operations actually exercised at runtime, and per-file line coverage of the backend source tree. The gate fails when a fact falls below the baseline; raising the baseline is an explicit, reviewable commit rather than an implicit side effect. Coverage is enforced as a per-file ceiling on uncovered statements rather than an aggregate ratio, because deleting already-covered code lowers an aggregate ratio without any regression.
- **Introduce a layered commit gate with a stated time budget.** A pre-commit layer restricted to change-scoped tests plus the existing docs contract, a pre-push layer that adds the architecture gate and rule validation, and CI as the authoritative full-suite layer. Each layer MUST declare its budget and its fallback rule.
- **Make the escape hatches auditable.** Test-gate bypasses follow the existing `[skip-plan]` / `SKIP_*` convention: a commit-message marker with a reason, or an explicit emergency environment variable, both recorded in the runbook.
- **Consolidate the pull-request workflow and stop running the backend suite twice.** The single authoritative workflow gains frontend verification (`npm run test`) and ratchet verification, and executes the complete backend suite exactly once. The workflow's existing file name, `name:` field, and job identifier are preserved so configured required status checks keep resolving; renaming is deferred to a separate coordinated operation. The digest-pinned PostgreSQL service and `MARKET_ENVIRONMENT_TEST_DATABASE_URL` injection MUST be preserved, because five test files depend on them and would otherwise silently skip.

## Capabilities

### New Capabilities

- `repository-test-gate`: Defines the repository-wide test ratchet (metrics, baseline semantics, monotonicity, and the explicit baseline-raise procedure), the layered commit-gate contract (layer responsibilities, time budgets, change-scope selection and fallback, cross-platform equivalence, and failure semantics when a dependency is unavailable), the mandatory auditability of bypasses, and the interface-coverage floor for declared HTTP operations.

### Modified Capabilities

- `trading-rule-ci`: Clarify that rule-specific checks and the repository test gate share the existing workflow, with one complete backend suite execution and unchanged rule/documentation obligations. This prevents the duplicate execution proposed in the earlier sibling-workflow design; the current repository was not measured to run the full suite twice.

_Note._ The three unexercised endpoints already have behavioral requirements in `ai-market-data-api`; this change adds verification for existing requirements and does not alter required behavior, so that capability needs no delta.

## Impact

- **Tooling and hooks**: `.githooks/pre-commit`, `.githooks/pre-push`, and `scripts/install-hooks.py`; one new offline gate script under `scripts/` that owns test-gate logic so the hook entry points stay thin, matching the existing `check-docs-contract.py` pattern.
- **Baseline artifact**: a new committed baseline file describing the test inventory and exercised interface set. It contains no raw market data, credentials, or runtime artifacts.
- **Tests**: additive runtime coverage in the existing API test area for the three unexercised operations, including at least one non-success path for the workbench revision precondition. No existing assertion is removed or relaxed.
- **CI**: `.github/workflows/trading-rules-pr.yml` gains frontend verification, ratchet verification, and the single complete backend suite run. Its file name, `name:` field, and job identifier stay unchanged so configured required status checks continue to resolve. The pinned PostgreSQL service digest and `MARKET_ENVIRONMENT_TEST_DATABASE_URL` injection are preserved verbatim.
- **Dependencies**: `coverage>=7,<8` is added to `requirements.txt`. `pytest-cov` is deliberately not added; the gate drives `coverage` directly and consumes its JSON report, keeping the addition to one dependency.
- **Documentation**: `AGENTS.md` (local gate section and escape-hatch list), `docs/runbooks.md` (hook installation and bypass procedure), and `docs/repository-guide.md` (code-to-doc mapping for the new gate script), plus one active plan under `docs/exec-plans/active/` as required by hard rules 2 and 3.
- **Constraints respected**: the gate runs offline and deterministically. It MUST NOT invoke real providers, production databases, Kubernetes or Helm writes, or deployment smoke. Integration tests that require PostgreSQL continue to self-skip through `MARKET_ENVIRONMENT_TEST_DATABASE_URL`, and the offline CI marker set is unchanged.
- **Non-goals**: no change to application behavior, API contracts, schemas, or provider logic; no mutation testing; no coverage target chosen independently of measurement, since the ratchet starts from observed values rather than an aspirational threshold; frontend line coverage is out of scope for this change.