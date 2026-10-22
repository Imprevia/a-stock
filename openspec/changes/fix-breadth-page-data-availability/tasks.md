## 1. Plan and Fact-Source Baseline

- [x] 1.1 Create `docs/exec-plans/active/fix-breadth-page-data-availability.md`, register it in `docs/exec-plans/active/_index.md`, include Stage/Status/Acceptance/Completion Evidence/Remaining Gaps/Next Step, and verify `python scripts/check-docs-contract.py --mode=fast` recognizes the plan before code edits.
- [x] 1.2 Update the pre-implementation contracts in `docs/architecture.md`, `docs/product-specs/market-environment-dashboard.md`, `docs/runbooks.md`, and `docs/repository-guide.md` to describe V2 history query safety, summary/history isolation, 60/250 coverage semantics, and the non-authorized production-backfill boundary; verify the documented code-to-doc mapping covers every intended source path.

## 2. PostgreSQL V2 History Reliability

- [x] 2.1 Refactor the PostgreSQL breadth/limits history queries to append only fixed predicates whose values are present and bind date values with explicit types; verify generated/executed queries contain no nullable untyped optional bind and preserve ascending exact-date ordering plus `limit + 1` pagination.
- [x] 2.2 Add real PostgreSQL adapter tests for breadth and limits history with no filters, only `start_date`, only `end_date`, both bounds, empty results, and a continuation key; verify every page is bounded, ordered, duplicate-free, and never returns an ambiguous-parameter error.
- [x] 2.3 Add V2 HTTP contract tests for breadth/limits history first and continuation pages, including revision/cursor validation and provider/write counters; verify valid local requests return 200 or documented missing/not-found results rather than 500, with zero provider calls and zero PostgreSQL mutations.
- [x] 2.4 Preserve integrity-error handling and resource quality when the history repository encounters invalid stored evidence; verify `snapshot_integrity_error` remains fail closed and no legacy or cross-date evidence is serialized as success.

## 3. Breadth Frontend Isolation and History Semantics

- [x] 3.1 Split the breadth V2 store flow into summary and history commit points with a dedicated history phase/error state; verify a summary 200 followed by history 500 keeps the current counts, median, label, quality, and other V2 resources visible without setting the global V2 flag to false.
- [x] 3.2 Implement revision-pinned breadth group restart so a history 409 refreshes overview and re-reads both summary and history before committing the new revision; verify tests never observe an old summary merged with new history.
- [x] 3.3 Normalize breadth history metadata to actual unique observations, `requiredObservations=60`, `windowDays=250`, bounded coverage, and the last five presentation points; verify fewer than 60 rows remain `insufficient` while a valid current summary remains available and the browser does not recompute market facts or percentiles.
- [x] 3.4 Update the 第 02 页 history panel to show separate loading/error/insufficient states and a history-only retry while preserving the existing visual tokens, minimum 14px text, and summary quality badge; verify desktop and 390px tests have no page-level overflow, overlap, or truncation.
- [x] 3.5 Extend frontend store/page tests for summary success plus history failure, empty/partial/over-60 history, last-five rendering, history retry, integrity failure, and 409 group restart; verify `npm run test` and `npm run build` pass in `apps/market-environment-dashboard/`.

## 4. Bounded Exact-Date Breadth History Repair

- [x] 4.1 Define a bounded breadth-history maintenance request/result contract that accepts explicit dates or a closed trading-session range, enforces a documented maximum, defaults to dry-run, and reports eligible/succeeded/retained/unavailable/failed dates; verify invalid ranges, excessive budgets, non-sessions, and apply-without-explicit-authorization inputs are rejected before provider I/O.
- [x] 4.2 Implement the CLI maintenance entry point using the existing breadth acquisition plan, TDX exact-date/package validation, ordinary-A-share universe policy, coordinator, lease/fencing, typed committer, and task/run audit; verify it contains no direct snapshot SQL and normal GET/default deployment paths cannot invoke it.
- [x] 4.3 Make each requested date independent and protect same-date successes: unavailable, mismatched, or insufficient packages must record failure without cross-date substitution or overwriting retained success; verify deterministic fixture tests cover mixed success/failure dates and exact-date negative cases.
- [x] 4.4 Rebuild only stored materialized aggregate dates whose breadth analysis window can depend on newly committed history, in chronological bounded batches, and verify affected percentile/quality fields plus public revisions change coherently while unrelated dates remain unchanged.
- [x] 4.5 Add a zero-write dry-run/capability probe and document the separate authorization required for real provider access, production snapshot writes, deployment, and backfill execution; verify offline tests perform no network or formal database writes.

## 5. Integration Verification and Handoff

- [x] 5.1 Run targeted backend tests for the PostgreSQL V2 adapter/router, breadth analysis, collection coordinator, CLI maintenance path, exact-date guards, and provider-free GET boundary; record commands and results in the active plan.
- [x] 5.2 Run `python -m pytest tests -q`, `python scripts/check_market_environment_architecture.py`, the relevant trading-rule validation commands, frontend `npm run test`/`npm run build`, `openspec validate fix-breadth-page-data-availability --strict`, and `python scripts/check-docs-contract.py --mode=full`; record any unavailable check as an explicit Remaining Gap rather than claiming completion.
- [x] 5.3 Perform a local/read-only API smoke against seeded PostgreSQL for overview, breadth summary, breadth history first/next pages, limits history, and legacy compatibility; verify no valid request returns 500 and no GET triggers provider calls, tasks, leases, or writes.
- [x] 5.4 Update `docs/status.md` and the active plan Status/Completion Evidence/Remaining Gaps/Next Step with the delivered behavior, test evidence, and the explicit fact that production deploy/provider probe/backfill remain unperformed unless separately authorized; verify the full docs-contract gate passes.
