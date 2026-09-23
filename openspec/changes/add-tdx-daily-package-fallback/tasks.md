## 1. Scope, source boundary, and plan guard

- [x] 1.1 Create `docs/exec-plans/active/add-tdx-daily-package-fallback.md` with the required Stage, Status, Acceptance, Completion Evidence, Remaining Gaps, and Next Step fields, and add it to the active-plan index; verify the docs contract recognizes the plan before code edits.
- [x] 1.2 Record the pinned `a-stock-data` upstream revision, Apache-2.0 attribution, and the exact extracted/rewritten surface; verify no runtime path downloads code or data from GitHub.
- [x] 1.3 Define `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED` with a fail-closed default and verify configuration parsing does not expose credentials or alter `sectors`, `limits`, or `core` routing.

## 2. Daily package client and normalization

- [x] 2.1 Add an injectable daily-package client that requests one explicit trading date and returns source URL, requested date, source date, fetch timestamp, and raw package metadata; verify missing package, HTTP failure, and not-yet-published responses become typed provider failures.
- [x] 2.2 Implement bounded download and archive/record parsing for the upstream package format, including EOF/truncation, row shape, supported A-share market, duplicate identity, finite numeric values, and exact-date validation; verify fixtures reject every malformed case without leaking response bodies.
- [x] 2.3 Normalize package rows to internal `code`, `date`, `close`, `amount`, optional `previous_close`, optional `change_pct`, and optional `name` fields; verify normalized rows retain null/missing semantics and never use zero as a substitute.
- [x] 2.4 Add deterministic fixtures for valid package data, empty package, truncated package, duplicate code, date conflict, missing amount, invalid numeric value, and unsupported market; verify fixtures contain no secrets or live URLs requiring network access.

## 3. Breadth fallback

- [x] 3.1 Implement breadth derivation from package-provided change/previous-close fields and, when absent, from the exact immediately preceding trading-day package; verify advance, decline, flat, valid count, and median return against fixed fixtures.
- [x] 3.2 Reject breadth candidates when the preceding session package is unavailable, dates conflict, identity overlap is below the configured threshold, or the market sample is incomplete; verify the result is `insufficient` and does not use current or cross-date data.
- [x] 3.3 Add the package fallback after both Eastmoney paths in `fetch_chapter01_breadth`; verify Eastmoney success performs no package call, package success records `tdx-daily-package` and prior warnings, and package failure preserves `failed-missing`/`failed-retained` behavior.

## 4. Active-direction fallback

- [x] 4.1 Implement package-side turnover ordering validation without locally sorting arbitrary rows; verify at least 30 valid rows, non-increasing amounts, unique codes, exact date, and finite values are required.
- [x] 4.2 Implement name resolution from a valid package name or a batched Tencent quote lookup restricted to names; verify price, amount, and date facts continue to come only from the daily package and unresolved/ambiguous names reject the candidate.
- [x] 4.3 Add the package fallback after both Eastmoney paths in `fetch_chapter01_active_direction`; verify the call order, `tdx-daily-package` source, fallback/degraded quality, Top-30 observations, Top-10 compatibility, and preserved upstream warnings.
- [x] 4.4 Add provider tests for primary success, delayed success, package success, all-source failure, missing names, fewer than 30 rows, unsorted rows, keyed row containers, and historical-date rejection; verify no candidate is reordered or written when validation fails.

## 5. Collection, documentation, and operational evidence

- [x] 5.1 Add collection integration tests covering independent breadth/active-direction tasks, same-date snapshot retention, failed-missing, failed-retained, partial parent runs, and provider-free status reads; verify `sectors` and `limits` remain unchanged.
- [x] 5.2 Update `docs/architecture.md` with the three-stage provider chain, source boundary, date evidence, name-resolution boundary, and default-off rollout; verify the architecture documentation links to the active plan.
- [x] 5.3 Update `docs/runbooks.md` with explicit after-market probe, package-not-published handling, warning inspection, rollback by disabling the feature flag, and prohibition on cross-date backfill; verify examples contain no credentials or production write commands.
- [x] 5.4 Run an explicit isolated real probe for one recent settled trading date after market close; verify and record package date, row count, amount coverage, name coverage, elapsed time, source revision, and final quality without writing production snapshots.

## 6. Verification and completion gate

- [x] 6.1 Run targeted provider and collection tests for the new fallback and verify the existing Eastmoney-success regression tests still pass.
- [x] 6.2 Run `python -m pytest tests -q`, `python -m src.trading_system.cli docs sync-check`, `python scripts/check-docs-contract.py --mode=full`, and `openspec validate --change add-tdx-daily-package-fallback --strict`; record results in the active plan.
- [x] 6.3 Confirm the feature flag remains disabled unless the isolated probe is accepted, no production database/provider write occurred during PR verification, and update active-plan Status, Completion Evidence, Remaining Gaps, and Next Step before marking the change complete.
