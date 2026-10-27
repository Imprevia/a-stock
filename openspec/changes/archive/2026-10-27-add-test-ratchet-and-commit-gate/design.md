## Context

See `proposal.md` - Why for the measured motivation. The constraints that shape this design:

- **Measured budgets.** `pytest tests` = 351.3 s / 1739 tests (exit 0); Vitest = 22.8 s / 172 tests; the docs-contract fast gate = 0.16 s; a three-file API contract subset = 19.0 s / 47 tests. The pre-commit layer has effectively no latency budget today, so anything added to it is a new cost against the 0.16 s status quo.
- **Commit shape.** Recent history contains commits spanning 21, 22, 31, and 58 files, with 126 commits in 2026-09 and 68 in 2026-10. Change-scoped test selection will frequently exceed any useful mapping, so a deterministic fallback is not an edge case but a routine path.
- **No test infrastructure to build on.** There is no `tests/conftest.py` and no root `conftest.py`; `pytest.ini` declares markers only. Anything requiring global pytest hooks changes the behavior of all 1739 tests at once.
- **Evidence that static coverage checks do not work here.** A path-string scan of `tests/` reported all 39 operations as covered; the same set measured by instrumenting `APIRoute.handle` was 36. The difference is `test_market_environment_api.py:85`, a hand-maintained OpenAPI expectation table that names every path without issuing a request. Any ratchet built on static matching would reproduce this false pass.
- **Existing gate conventions to follow.** `.githooks/*` are thin `sh` entry points that `exec` a Python script and contain no business logic; `scripts/check-docs-contract.py` owns the rules. Escape hatches are `[skip-plan]` / `SKIP_PLAN_GATE=1` / `SKIP_DOCS_CONTRACT=1`, documented in `AGENTS.md`.
- **Coverage is measurable and the cost is known.** One `coverage run --source=src -m pytest tests -q` on 2026-10-27 produced 83% (22672/27304 statements) across 236 files in 404.72 s with 1638 passed / 101 skipped: +53 s (+15%) over the uninstrumented 351.3 s. Only three files sit at 0%, totalling 122 statements, all entry-point shaped (`trading_knowledge/cli.py`, `trading_knowledge/mcp_server.py`, `snapshot_migration.py`).
- **CI is configured for database-backed tests; the local measurement was not.** The existing workflow declares a digest-pinned PostgreSQL service and injects `MARKET_ENVIRONMENT_TEST_DATABASE_URL`. The local run reported 101 skips, but individual reasons were not audited; they MUST NOT all be attributed to PostgreSQL. Record the authoritative baseline in a CI-equivalent database-configured environment and inspect skip reasons. The local 83% is exploratory evidence, not the committed baseline.
- **Repository rules that constrain the gate.** Runs must be offline and deterministic; real providers, production databases, Kubernetes/Helm writes and deployment smoke are forbidden in normal tests; Windows/macOS/Linux are equal citizens; `AGENTS.md` states a missing interpreter must not be treated as a passing verification.

## Goals / Non-Goals

**Goals:**

- Make the suite's integrity measurable and monotonic with one new dependency, `coverage`.
- Keep the pre-commit layer inside a budget small enough that it is not routinely bypassed.
- Detect the specific failure mode this investigation found: an operation declared and asserted but never invoked.
- Make every bypass leave a trace that review can see.

**Non-Goals:**

- Choosing a line-coverage percentage target before any measurement exists (see Decision 1).
- Arbitrary percentage mandates, mutation testing, or guarantees of detecting every weakened assertion. Line coverage measures execution, not assertion quality or branch completeness.
- Replacing the authoritative full-suite CI run; the gate adds verification, it does not shorten the suite.
- Changing any application, API, schema, or provider behavior.

## Decisions

### Decision 1: Ratchet on three facts, one of which measures coverage directly

Ratcheted facts:

1. **Executable test inventory** - the sorted node IDs `pytest --collect-only` reports.
2. **Exercised operation set** - the `(method, path)` pairs actually dispatched during the run.
3. **Per-file uncovered statements** - coverage of the backend source tree, enforced per file.

Alternatives considered:

| Option | Verdict |
| --- | --- |
| Test file count or assertion count via AST | Rejected. Trivially gamed by adding a file with no assertions, and invariant under an operation losing its only runtime test. |
| Inventory + exercised operation set only | Rejected after measurement. Coverage is cheap to add here (83% already measured, +15% runtime) and covers whole behavioural areas the first two facts never observe, such as a service-level branch losing its only test without any node ID disappearing. |
| Inventory + exercised operations + per-file uncovered statements | Chosen. Zero new test-framework dependency, deterministic, offline, and each fact catches a failure the others miss. |

The inventory is stored as full node IDs rather than a count so that the gate can name what disappeared. A rename therefore registers as one deletion plus one addition, which is intentional: it forces the baseline update to be explicit.

### Decision 1a: One new dependency, and not the conventional one

`coverage>=7,<8` is added to `requirements.txt`. `pytest-cov` is **not** added.

The gate needs the JSON report rather than pytest's terminal output, because it compares per-file values against the baseline and must name regressed files. That means invoking `coverage` directly (`coverage run` plus `coverage json`) regardless, at which point `pytest-cov` would be a second dependency wrapping the first. Keeping the addition to one dependency also keeps the offline CI solve reviewable, which matters because `requirements.txt` pins a coherent set (`httpx>=0.25,<0.26` is capped by `mootdx`).

Scope is `src/` (backend) only. Frontend line coverage is excluded: it needs a separate provider package (`@vitest/coverage-v8`), a separate baseline concept, and a separate comparison surface, and it is recorded as a follow-up rather than folded into this change.

### Decision 1b: Enforce uncovered statements per file, not a coverage ratio

The enforced fact is each file's count of **uncovered statements**, which must not rise above its baseline value. The aggregate ratio is reported but never enforced.

Why not a ratio, at either the repository or the file level: a ratio conflates two directions. Removing covered code lowers the numerator and the denominator and therefore lowers the ratio while nothing has regressed - a file at 90% (90/100) drops to 88.9% (80/90) if ten covered statements are deleted. An uncovered count is stable under that operation and only rises when tested behaviour is lost or untested behaviour is added. Deleting uncovered code lowers it, which is a genuine improvement and correctly passes.

The measured distribution also makes a ratio ceiling unnecessary here: with only three zero-coverage files totalling 122 statements, a per-file baseline needs effectively **no waiver list**. A repository-wide threshold would instead require one, because the remaining low-coverage files would otherwise sit permanently under the threshold and the list would become the real contract.

New files produce candidate baseline entries and a prominent newly-observed report; verification never rewrites the committed baseline. Persisting entries requires an explicit reviewed baseline update. Renames and intentional removals need documented inventory reconciliation. Compare candidate baseline changes against the trusted parent/target baseline so increasing uncovered-statement ceilings cannot hide regressions. Counts cannot detect all assertion weakening or offsetting coverage changes; those remain review limitations.

### Decision 1c: Coverage is measured and compared only in the authoritative layer

Coverage runs in `--mode=ci` only, never in `--mode=commit` or `--mode=push`.

Two independent reasons, either sufficient on its own:

1. **Runtime.** 404.72 s instrumented versus 351.3 s plain. Change-scoped selection cannot help, because a subset run measures artificially low coverage for every file the subset does not happen to touch, which would false-fail the per-file ratchet.
2. **Environment comparability.** Local skips have not been audited individually. Metadata records Python/coverage versions, the test profile and database backend/schema profile, never URLs or credentials. An environment mismatch or unexpected database-test skip yields a nonzero incomplete result; do not claim a comparable authoritative pass.

### Decision 2: Measure the exercised set by instrumentation, not static matching

A pytest plugin records the actual request method and matched route template, with response statuses associated with passing tests. Compare exact operation sets, not counts or all methods registered on a route. Include API and discovery operations; explicitly exclude Swagger/ReDoc, static files and the frontend catch-all. Restore all instrumentation patches. Invocation is a minimum coverage signal, not evidence of every success/error branch being tested.

Alternatives considered:

- **Static path scanning** - proven to produce false passes on this repository (39 vs 36 measured). Rejected.
- **ASGI middleware recorder** - misses routes short-circuited before middleware and couples the measurement to middleware ordering. Rejected.
- **Assert inside each test file** - puts the ratchet inside the code under change, where it is editable in the same commit. Rejected.

Fragility is real: the installed FastAPI is 0.141.1 and materializes included routers lazily (`_IncludedRouter`), which is why the plugin patches the class rather than enumerating `app.routes` upfront. Mitigation is in Risks.

### Decision 3: Load the plugin with `-p`, not a new global `conftest.py`

The repository has no `conftest.py` anywhere. Adding one at the repository root would apply to all 1739 tests and change collection for every existing file as a side effect of adding a gate.

The gate instead invokes `pytest -p <plugin_module>` inside a subprocess. Alternative rejected: a `tests/conftest.py` autouse fixture, which cannot be disabled per-invocation and would make the instrumentation unconditional.

Subprocess rather than in-process `pytest.main` is chosen so the gate has no in-process state interaction with whatever invoked it, and so a hard crash in collection cannot take the gate script down.

### Decision 4: Three layers with assigned ownership and measured budgets

```
  layer            trigger        owns                                  budget
  --------------------------------------------------------------------------------
  L0 fast          git commit     docs-contract --mode=fast              < 30 s
                                  change-scoped pytest
                                  (fallback: API contract subset 19.0 s)
  L1 intermediate  git push       architecture AST gate                  < 180 s
                                  rules validate + coverage
                                  widened change-scoped pytest
                                  (no full suite)
  L2 authoritative CI            pytest tests -q (once)                405 s
                                  npm run test                23 s
                                  ratchet verification
                                    inventory + exercised operations
                                    + per-file coverage
                                  docs-contract --mode=full
  --------------------------------------------------------------------------------

  L2 workflow identity (see Decision 8)
  +---------------------------------------------------------------+
  | file   .github/workflows/trading-rules-pr.yml   (unchanged)   |
  | name   Trading Rules PR Gate                    (unchanged)   |
  | job    offline-rule-gate                        (unchanged)   |
  | steps  existing rule checks                                   |
  |        + npm run test                  <-- new               |
  |        + check-test-gate --mode=ci                            |
  |          -> coverage run -m pytest tests -q (exactly once)    |
  |          -> compare reports from that same execution         |
  |        (postgres service + DATABASE_URL preserved verbatim)   |
  +---------------------------------------------------------------+
```

The full backend suite is deliberately absent from L0 and L1. At 351 s against a 0.16 s status quo, putting it in pre-commit would convert the documented escape hatches into the normal workflow, which is the specific failure this change exists to prevent. Coverage is likewise absent from L0 and L1 - see Decision 1c.

Budgets are **reported, not enforced**. The gate measures elapsed time and warns when a layer exceeds its budget; it fails only on correctness. Hard timeouts on shared CI hardware and laptops produce flaky failures that train people to bypass the gate.

### Decision 5: Change-scope selection uses the repository's existing naming convention

The suite already follows `tests/test_market_environment_<module>.py` for `src/market_environment/<module>.py`, which makes filename derivation viable without maintaining a mapping table.

```
  changed path                          selected tests
  -----------------------------------------------------------------------
  src/market_environment/<module>.py -> tests/test_market_environment_<module>.py
  src/trading_system/<x>.py          -> tests/test_*<x>*.py (suffix match)
  apps/.../src/<name>.ts             -> apps/.../src/<name>.test.ts
  tests/...py                        -> that file
  docs/**, openspec/**               -> none (fallback only if mixed)
  unmatched                          -> fallback subset
```

Fallback triggers: more than 8 changed testable files, more than 2 distinct top-level areas, or any unmatched path. The backend subset is `tests/test_market_environment_api.py`, `tests/test_market_environment_v2_contract.py`, and `tests/test_market_environment_discovery.py` (47 tests, 19.0 s before additions). It previously did not catch the three gaps; add the missing runtime tests and enforce operation sets in CI. Frontend changes select Vitest tests or a frontend fallback, never a backend-only substitute.

Alternative rejected: running the full suite behind a `-m "not slow"` marker. It requires re-marking an existing 1739-test suite, and no marker currently separates slow from fast tests.

### Decision 6: A new gate script owns the logic; hooks stay thin

New `scripts/check-test-gate.py` with `--mode=commit|push|ci|baseline`. Hooks delegate once to the dispatcher, which chains docs-contract before tests; appending after the current `exec` is unreachable. Push preserves full docs verification. CI launches the suite exactly once under coverage with the route plugin, then compares reports from that run.

Pre-commit cannot read the future commit message. Use the explicit local emergency variable and validate its reason at `commit-msg` time or in an equivalent documented audit step; installation includes any new hook. Never authorize bypass from stale `COMMIT_EDITMSG`; CI ignores local bypasses. Commit checks execute the staged tree, using an isolated index snapshot or failing closed on overlapping unstaged edits without changing the user's index/stash. Push selection preserves the refs Git supplies. Local hooks are bypassable and do not replace required CI checks.

Alternative rejected: extending `check-docs-contract.py`. That script documents itself as the docs-contract gate with Gate 0-7, and `AGENTS.md` ties its error messages to the document contract; adding test semantics there would entangle two independently failing concerns and make the escape-hatch vocabulary ambiguous.

### Decision 7: Missing interpreter fails the gate instead of passing

The current hooks `exit 0` with a warning when Python is absent. The test gate does the opposite: it exits non-zero and names `SKIP_TEST_GATE=1` as the audited way past it.

This follows the spec requirement that a gate must not report success when its dependency is unavailable, and `AGENTS.md`'s statement that a vacuous local pass cannot be treated as verification. The cost is that the first commit on a machine without Python blocks until the escape hatch is used; that is one intentional friction point per machine, and it is visible in the commit message rather than silent.

### Decision 8: One authoritative workflow, extended in place rather than replaced

The existing `.github/workflows/trading-rules-pr.yml` becomes the single authoritative gate. It keeps its rule-specific steps, gains `npm run test`, gains the ratchet verification, and owns the one and only complete backend suite run. The duplicated suite execution disappears.

Alternatives considered:

| Option | Verdict |
| --- | --- |
| Add a sibling `repository-test-gate.yml` and delete the suite step from the trading-rule workflow | Rejected by the user's choice on operational grounds. It reads better semantically, but GitHub matches required status checks by workflow name and job identifier, and renaming or relocating those silently invalidates configured branch protection. |
| Keep both workflows and accept the duplicate suite | Rejected. It doubles the most expensive job for no verification gain, which is exactly the duplication this decision removes. |
| Extend the existing workflow in place | Chosen. File name, `name:` field, and job identifier stay unchanged, so required checks keep resolving with no out-of-repo coordination. |

The cost is a naming mismatch: a workflow called "Trading Rules PR Gate" now also verifies the dashboard and the repository ratchet. That mismatch is accepted here and recorded as an Open Question, because resolving it requires the repository owner to update GitHub settings in the same window as the rename.

`trading-rule-ci`'s "Offline pull request gate" requirement is amended accordingly: it stops enumerating `pytest` as its own step and states that the complete suite and the ratchet belong to the repository test gate, while this gate must still fail the pull request on its own rule-specific result. Without that amendment the requirement would contradict the implementation.

**Hard constraint on this consolidation.** The workflow's PostgreSQL service and `MARKET_ENVIRONMENT_TEST_DATABASE_URL` injection MUST be preserved verbatim when steps are reshuffled. Five test files read that variable and skip when it is absent, so dropping the service would silently convert database-backed verification into skips while the job still reported success. The ratchet would not catch it either without the environment check from Decision 1c, which is the second reason that check exists.

### Decision 9: Baseline artifact lives with the tests, not with fixtures

`tests/baselines/test-ratchet.json`, holding `{"inventory": [...node IDs], "exercisedOperations": [...], "coverage": {"<path>": "<uncovered statements>"}, "environment": {...}, "versions": {...}}`.

`environment` records the facts that make a measurement comparable - most importantly whether a test database was configured - so the gate can refuse an incomparable comparison instead of issuing a verdict from it (Decision 1c).

It is a curated reference artifact, not a runtime product, so it does not conflict with the repository rule against committing runtime artifacts or raw snapshots. `coverage.json` itself is a build output and is not committed; only the derived per-file uncovered counts are. Placing the baseline under `tests/fixtures/` was rejected: fixtures are inputs to application behaviour, while this is a claim about the suite itself.

## Risks / Trade-offs

- **FastAPI internals change and instrumentation silently records nothing** → The gate fails when the recorded set is empty or smaller than the declared operation count, and emits the framework version. A silent zero would otherwise read as "everything is broken" or, worse, as a vacuous pass if the comparison were written naively.
- **Renaming a test file looks like deleted coverage** → Intended. The baseline update is explicit; the gate message names the missing node IDs so the reviewer sees a rename rather than a loss.
- **Change-scope mapping misses cross-cutting impact** (a shared fixture or a mapper used by many modules) → Fallback triggers on unmatched paths, and L2 runs the full suite. The gate speeds feedback; it never becomes the only verification.
- **Developers bypass the fast layer** → Bypasses require a commit-message marker with a reason, mirroring `[skip-plan]`, and L2 still evaluates everything. Friction is concentrated where it is visible.
- **Trivial tests inflate the ratchet** → The inventory fact is gameable in isolation, which is why the exercised-operation fact is ratcheted alongside it; a trivial test cannot make an unexercised operation appear exercised.
- **A new dependency breaks the offline CI solve** → `coverage>=7,<8` is a single addition with no transitive requirements of consequence, and `pytest-cov` is deliberately avoided so the addition stays at one package. The CI solve is verified by installing from `requirements.txt` in the same job.
- **Coverage instrumentation slows the suite further** → Measured at +15% (404.72 s vs 351.3 s). It runs only in L2, and L0/L1 budgets are unaffected.
- **A local coverage measurement is compared against a CI baseline** → The baseline records its environment and the gate refuses to compare across a mismatch, reporting the difference instead of failing or passing.
- **The consolidated workflow loses database-backed tests** → The service and `MARKET_ENVIRONMENT_TEST_DATABASE_URL` are preserved verbatim and the task list requires verifying that the previously configured database-backed tests still execute rather than skip.
- **Coverage measurement is non-deterministic between runs** → Comparison is on integer uncovered-statement counts, not floating-point ratios, so rounding cannot produce spurious drift. Two consecutive runs on one commit are required to produce an identical baseline during implementation.
- **The workflow's name no longer describes its contents** → Accepted for this change and recorded as an Open Question; renaming requires the repository owner to update GitHub required checks in the same window.
- **Developers bypass the fast layer** → Bypasses require a commit-message marker with a reason, mirroring `[skip-plan]`, and L2 still evaluates everything. Friction is concentrated where it is visible.
- **L0 grows over time until it is bypassed** → Budgets are reported per run and stated in the runbook; the decision to move a check between layers must cite the measured budget.
- **First-run friction on machines without Python** → One blocking commit per machine, resolved by installing Python or by an audited `SKIP_TEST_GATE=1`.
- **Hook-mounted state varies per clone** → `install-hooks.py` gains a verification mode that reports active/inactive, so a reviewer can tell whether a local pass means anything.

## Migration Plan

Rollout is ordered so the baseline is recorded only after the coverage gap is closed; recording it first would freeze the current deficit as the accepted floor.

1. **Mount and verify** hooks (`install-hooks.py`, plus an active/inactive verification mode). No behavior gate yet.
2. **Close the measured gap**: add runtime tests for the three unexercised operations.
3. **Add the coverage dependency** (`coverage>=7,<8`) and verify the offline CI solve still installs cleanly.
4. **Record the baseline** from a green authoritative run that supplies the test database, covering all three facts, then confirm `--mode=ci` passes against it on a second consecutive run. Confirm the recorded `environment` block reflects the database-configured run.
5. **Enable L0** in `.githooks/pre-commit`, then confirm a no-op commit stays inside 30 s.
6. **Enable L1** in `.githooks/pre-push`.
7. **Consolidate the workflow**: add the dashboard and ratchet steps to the existing job, delete the now-duplicate suite execution, and verify the database-backed tests still execute rather than skip.
8. **Prove the ratchet fails**: on a scratch branch, delete one test, remove one endpoint test, and lower one file's coverage; confirm each is caught, then revert the probes.
9. **Sync documentation**: `AGENTS.md` local-gate and escape-hatch sections, `docs/runbooks.md` hook and bypass procedure, `docs/repository-guide.md` mapping for the new script, and an active plan per hard rules 2 and 3.

Rollback: each layer is a single `exec` line in a hook, and the workflow change is a revert of steps within one file whose identity never changed. Disabling L0/L1 is a revert of those lines; the baseline artifact, the coverage dependency, and the added tests are independently valuable and stay.

## Open Questions

- Whether to adopt frontend line coverage, which needs `@vitest/coverage-v8`, its own baseline section, and its own comparison surface. Deferred to keep this change to one new dependency.
- Whether to rename the consolidated workflow and job to describe their broadened contents. Deferred because it requires the repository owner to update GitHub required status checks in the same window; the current names are preserved deliberately until then.
- Whether to tighten the new-file admission policy beyond prominent reporting and explicit reviewed baseline entries. No automatic baseline mutation is allowed in the initial implementation.