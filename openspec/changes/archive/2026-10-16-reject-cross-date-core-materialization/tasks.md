## 1. Documentation-first Baseline

- [x] 1.1 Create and index an active execution plan with Stage, Status, Acceptance, Completion Evidence, Remaining Gaps, and Next Step before changing code; verify `python scripts/check-docs-contract.py --mode=fast` or the repository interpreter equivalent passes the plan gate.
- [x] 1.2 Update `docs/architecture.md`, `docs/product-specs/market-environment-dashboard.md`, `docs/repository-guide.md`, and `docs/runbooks.md` with the exact-date invariant, stable 503 contract, audit boundary, and separately authorized repair workflow; verify the documents contain no automatic provider, relabel, deletion, deployment, or production-write path.

## 2. Failing Exact-Date Contract Tests

- [x] 2.1 Add core source-adapter tests where the latest history bar equals the requested date and where it is one session earlier; verify the first returns a candidate and the second returns a structured date-mismatch failure whose actual date matches the history tail.
- [x] 2.2 Add core acquisition-plan tests for four exact indices plus one cross-date index, five cross-date indices without retained evidence, and five cross-date indices with valid same-date retained evidence; verify `partial`, `failed-missing`, and `failed-retained` outcomes respectively and verify no cross-date index enters a candidate.
- [x] 2.3 Add retained-index tests proving a historical malformed snapshot cannot supply a prior-date index to a new selected-date candidate; verify only independently valid same-date index evidence is eligible for retention.
- [x] 2.4 Add transaction tests for the core committer, current runtime compatibility snapshot store, and typed PostgreSQL snapshot repository; verify a mismatched write leaves no partial core-index, session, snapshot, checksum, or revision mutation.
- [x] 2.5 Add materialization tests for both runtime compatibility and typed PostgreSQL aggregate writers; verify key/payload/component date mismatch aborts replacement while a valid exact-date partial aggregate succeeds.
- [x] 2.6 Add v2 overview/resource and legacy aggregate/core tests for malformed stored evidence; verify HTTP 503 code `snapshot_integrity_error`, safe response text, zero provider calls, zero collection submission, zero background tasks, and zero PostgreSQL writes while a genuinely absent date keeps its existing 404 or missing semantics.
- [x] 2.7 Add dashboard tests for `snapshot_integrity_error`; verify the explicit integrity message is rendered without accepting legacy or cross-date data and all visible text remains at least 14px at desktop and 390px widths.

## 3. Core Acquisition and Retention

- [x] 3.1 Implement a shared pure core date-evidence validator for candidate identity, payload/quality dates, effective date, and each included index history tail; verify its unit-test matrix covers exact, missing, malformed, future, and prior-session dates.
- [x] 3.2 Reject prior-session history at each core source normalization boundary with structured date-mismatch evidence and derive `actual_as_of` from the validated history tail; verify every configured fallback source passes the adapter contract tests.
- [x] 3.3 Update core aggregation so only exact-date or same-date retained index results count as successes, mixed valid results produce a selected-date partial payload, and zero valid results produce no commit candidate; verify the acquisition-plan tests from 2.2 pass.
- [x] 3.4 Apply the same validator to retained-index loading and record requested/actual dates in safe warnings and provenance; verify malformed retained rows are excluded without relabeling or cross-date fallback.

## 4. Strict Snapshot and Materialized Writes

- [x] 4.1 Split legacy read recognition from write authorization and remove the legacy cross-date exception from new snapshot writes; verify exact-date legacy imports remain inspectable while normal runtime writes fail closed.
- [x] 4.2 Enforce the validator before the fenced core transaction commits success evidence in both compatibility and typed PostgreSQL paths; verify task failure preserves a prior same-date snapshot and successful sibling dataset results.
- [x] 4.3 Enforce aggregate key, public `asOf`, core snapshot identity, effective-date, and component-date agreement in both actual runtime and typed PostgreSQL replace/CAS paths; verify failed validation retains the prior valid aggregate and does not advance its revision.
- [x] 4.4 Confirm no schema migration is required and update schema/version tests accordingly; verify Alembic head and runtime schema version remain unchanged.

## 5. HTTP and Dashboard Behavior

- [x] 5.1 Map snapshot and materialized integrity exceptions before generic runtime errors in the shared HTTP boundary; verify v2 and legacy return HTTP 503 code `snapshot_integrity_error` without SQL, checksum, path, provider payload, or stack-trace disclosure.
- [x] 5.2 Preserve existing 404, 409, 422, `missing`, `insufficient`, and successful response contracts; verify focused OpenAPI, discovery drift, legacy characterization, and revision/cursor tests pass unchanged.
- [x] 5.3 Update the dashboard v2 error handling to surface the integrity failure instead of hiding it behind a second successful legacy/cross-date response; verify ordinary compatibility fallback still works for its documented non-integrity cases.

## 6. Audit, Repair Guidance, and Release Safety

- [x] 6.1 Add or document a provider-free read-only audit for snapshot and aggregate key/payload/quality/actual/effective dates that reports exact row identities and revision/checksum references without credentials or complete payloads; verify it performs zero writes against an isolated fixture database.
- [x] 6.2 Document the separately authorized production repair sequence: writer freeze, PostgreSQL backup, exact-target review, conflict checks, same-date forward recollection/rebuild, and rollback evidence; verify the runbook explicitly forbids automatic relabel, cross-date copy, direct payload/checksum editing, PVC deletion, and unapproved provider calls.
- [x] 6.3 Extend release smoke guidance beyond `/api/health` to one valid historical v2 overview plus effective-date v2 overview and legacy core reads; verify the smoke is read-only and distinguishes 200, 404/missing, and stable integrity 503 without triggering collection.

## 7. Verification and Completion

- [x] 7.1 Run focused core acquisition, committer, snapshot repository, aggregate, v2/legacy API, and dashboard tests; record exact commands and results in the active plan Completion Evidence.
- [x] 7.2 Run `.venv/bin/python -m pytest tests -q`, `npm run test`, and `npm run build` in the dashboard; record any skipped or unavailable check and do not claim completion if a relevant failure remains.
- [x] 7.3 Run `python -m src.trading_system.cli rules validate`, `rules coverage`, `docs sync-check`, `openspec validate reject-cross-date-core-materialization --strict`, `python scripts/check-docs-contract.py --mode=full`, and `git diff --check`; verify every gate passes with the available repository interpreter.
- [x] 7.4 Update the active plan Status, Completion Evidence, Remaining Gaps, and Next Step, explicitly separating offline implementation completion from unexecuted production deployment/data repair; verify no production write, provider smoke, deployment, Secret, PVC, or scheduling change is recorded as performed by this change.
