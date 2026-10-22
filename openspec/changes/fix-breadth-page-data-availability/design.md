## Context

See `proposal.md` for motivation. The production read path currently exposes three distinct facts that the implementation conflates:

- The exact-date breadth snapshot and V2 summary can be valid and complete.
- The V2 breadth/limits history PostgreSQL queries can fail before returning their first page because optional `NULL` date/cursor parameters are bound in `IS NULL OR ...` predicates.
- Breadth percentile confidence legitimately remains `insufficient` until at least 60 exact-date snapshots exist; the current V2 client manufactures `requiredObservations`, `windowDays`, and `coverage` from the returned row count.

Normal GET requests must remain provider-free and write-free. PostgreSQL is the only production store, historical dates must be exact, and production provider calls, snapshot writes, deployment, or data repair require separate authorization. Existing `market-breadth-page` behavior also requires a five-day presentation window while percentile calculation may inspect up to 250 local observations.

## Goals / Non-Goals

**Goals:**

- Make breadth and limits history pages reliable on real PostgreSQL with omitted filters, partial filters, and continuation cursors.
- Preserve a successful breadth summary when its optional history request fails, while keeping revision pinning and integrity errors fail closed.
- Report the true 60-observation minimum and 250-session analysis window, while rendering only the latest five verified points.
- Provide a bounded maintenance path that can close historical breadth gaps only when exact-date TDX evidence is available.
- Add tests that exercise the PostgreSQL adapter and frontend failure sequence that escaped the compatibility fixtures.

**Non-Goals:**

- Lowering the 60-observation threshold, fabricating percentiles, filling missing values with zero, or relabeling current data as historical.
- Triggering collection from a GET, page load, deployment, default automation, or scheduled workload.
- Adding a new market-data provider, changing trading-rule IDs/weights, changing PostgreSQL schema, or authorizing a production backfill/deployment.
- Treating the historical-gap repair as proof that TDX retains every requested archive date; unavailable dates remain explicit failures.

## Decisions

### 1. Build history predicates from a closed set and bind only present values

The PostgreSQL adapter will start with the mandatory dataset/as-of predicates, then append fixed `start_date`, `end_date`, and cursor predicates only when the corresponding value is present. Date bind parameters will use an explicit SQLAlchemy/PostgreSQL date type. The same helper/pattern will be used by breadth and limits history so the two endpoints cannot drift back to nullable untyped binds.

This follows the already-safe limits-pool cursor pattern and avoids asking PostgreSQL to infer the type of `NULL`. Keeping the fragments fixed prevents selectors from becoming arbitrary SQL.

Alternative considered: keep `:value IS NULL OR column >= :value` and add casts. Explicit casts can work, but they continue to execute avoidable OR branches and make it easier for a later optional cursor field to reintroduce an ambiguous bind. Conditional fixed predicates are simpler to test and index-friendly.

### 2. Treat breadth summary and history as a revision-pinned resource group with separate commit points

The frontend store will split breadth loading into a summary step and a history step:

1. Read the breadth summary under the overview revision.
2. Validate and commit the summary immediately, including its real quality metadata.
3. Fetch history under the same revision and commit only the history state when it succeeds.
4. If history returns a transient/network/5xx error, keep the committed summary, mark a dedicated history state as error, and allow a history-only retry. Do not set the global V2 feature flag to false.
5. If revision pinning returns 409, restart the breadth group from overview and re-read both summary and history before committing the new revision, preventing a mixed old-summary/new-history view.
6. If the summary returns `snapshot_integrity_error`, fail closed for the summary and do not use legacy evidence. A history integrity error affects only history unless the summary itself is invalid.

Alternative considered: continue falling back the whole page to the legacy Chapter 01 endpoint. That hides the V2 defect, discards a valid summary, and can mix different generation times, so it is rejected.

### 3. Normalize history metadata once, without recomputing market facts in the browser

The history loader will retain at most 250 ordered exact-date points for coverage accounting and derive presentation points as the last five valid rows. Client metadata will use:

- `validObservations = all returned unique exact-date points`
- `requiredObservations = 60`
- `windowDays = 250`
- `coverage = min(validObservations / 250, 1)`
- history quality `insufficient` below 60, otherwise the endpoint quality subject to warnings

The browser will not recompute breadth counts, median returns, percentiles, or labels. Percentile fields continue to come from the materialized breadth summary and remain `null` until the backend has sufficient local history. This separates “today is known” from “the rolling distribution is mature.”

Alternative considered: lower the threshold to the currently stored 26 days or calculate temporary percentiles in TypeScript. Both would change the quantitative contract and create results that are inconsistent with backend/trading-rule evidence, so they are rejected.

### 4. Historical gap repair uses the existing collection pipeline through a bounded CLI maintenance operation

Implementation will add a provider-maintenance entry point that accepts an explicit start/end or explicit date set, resolves only known trading sessions, caps the run to a documented maximum, and defaults to a no-write plan/probe. Apply mode must use the existing breadth acquisition plan, TDX exact-date validation, ordinary-A-share universe policy, lease/fencing, committer, task/run audit, and materialized aggregate builder; it must not write snapshot rows directly.

Each date is independent. A failed or unavailable package records a failed result and does not roll back successful sibling dates or replace an existing same-date success. After successful writes, existing materialized aggregate dates whose breadth analysis depends on the new history window are rebuilt in chronological order so percentile fields and the public revision change coherently. The operation reports eligible, succeeded, retained, unavailable, and failed dates.

The code and offline tests may be implemented without production authorization. Running a real provider probe, applying a production backfill, or deploying remains a separate explicit operation recorded in an active plan.

Alternative considered: wait for 34 additional natural sessions. This is operationally safe but leaves the page without mature percentiles for weeks. Direct SQL insertion is rejected because it bypasses exact-date validation, checksum, task audit, lease/fencing, and aggregate revision updates.

### 5. Test against real PostgreSQL behavior, not only compatibility adapters

Backend coverage will execute the real PostgreSQL read adapter against the repository's PostgreSQL test harness for:

- no optional filters;
- each single date boundary and both boundaries;
- first and continuation pages;
- empty history and exact-date rows;
- breadth and limits history;
- provider-call/write counters remaining zero.

HTTP tests will assert no valid history request returns 500 and cursor pages do not duplicate dates. Frontend tests will model “summary 200, history 500” and “summary 200, history 409 then group restart,” verify the summary remains visible, and check 60/250 metadata plus five-row rendering. Page tests retain desktop and 390px overflow/font checks.

## Risks / Trade-offs

- [History backfill packages may no longer be published] → Probe each date before apply, report unavailable dates, and keep quality `insufficient`; do not broaden to a latest-only provider.
- [A large repair could consume provider budget or hold leases too long] → Enforce a small documented maximum, sequential acquisition, per-date commits, and resumable audit output.
- [Rebuilding dependent aggregates can be more expensive than writing snapshots] → Rebuild only stored aggregate dates whose 250-session window can include a newly added date, in chronological bounded batches, and record timings.
- [A history error can be less visually prominent once the summary stays visible] → Give the history panel an explicit error/insufficient state and retry affordance while keeping warnings separate from summary quality.
- [Revision changes during a two-request breadth load] → Restart the entire breadth resource group on 409 and never merge data from different revisions.
- [Shared query refactoring could affect limits history] → Add parity tests for both datasets and preserve existing ordering, limits, quality, and cursor identities.

## Migration Plan

1. Create/update the required active exec plan and fact documents before code edits.
2. Land PostgreSQL history query and real-adapter regression tests first; verify breadth and limits history return bounded pages without provider calls or writes.
3. Land the frontend split-state loader and metadata normalization; verify summary retention, group restart on 409, history-only error/retry, and five-row rendering.
4. Add the bounded breadth history maintenance CLI and offline fixtures/probes. Keep apply mode unused in normal tests and deployments.
5. Run targeted backend/frontend tests, full relevant pytest/Vitest/build suites, architecture checks, OpenSpec validation, and the full docs-contract gate.
6. Deploy/read-smoke only under a separate authorization. Roll back the application image if GET regressions appear; no data rollback is needed for the read-path changes.
7. If separately authorized, run dry-run/probe first, review exact eligible dates and budget, then execute a bounded production backfill and verify snapshots, aggregates, revisions, API responses, task audit, and preserved PVC/Secret identities. Stop on date-integrity or universe-policy failures without deleting retained evidence.
