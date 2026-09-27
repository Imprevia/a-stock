## 1. Scope Guard and Universe Policy

- [x] 1.1 Create or update the matching `docs/exec-plans/active/*.md` with the required Stage, Status, Acceptance, Completion Evidence, Remaining Gaps, and Next Step fields; verify `python scripts/check-docs-contract.py --mode=fast` recognizes the plan before code edits.
- [x] 1.2 Define the versioned TDX ordinary A-share policy for `sh`, `sz`, and `bj`, including the 2025-10-09 Beijing `920` boundary, excluded instrument families, production stock-count thresholds, and a stable policy version; verify unit tests cover accepted, excluded, and unknown code/market combinations.
- [x] 1.3 Implement a pure TDX universe classifier that returns retained rows plus raw/retained/excluded/unclassified counts, per-market counts, and one reason per excluded row; verify mixed-security fixtures never classify an unknown row as a stock through name, price, or turnover.
- [x] 1.4 Separate raw package/file completeness thresholds from post-filter ordinary-stock sample thresholds; verify a structurally complete mixed package can pass parsing while a post-filter incomplete stock universe is rejected as `insufficient`/`failed`.

## 2. TDX Normalization and Provider Consumers

- [x] 2.1 Preserve raw TDX package counts while applying the shared universe classifier after date and structural validation in the provider package boundary; verify both current and exact preceding-session packages receive the same date-versioned filtering.
- [x] 2.2 Update TDX breadth derivation so returns, `advanceCount`, `declineCount`, `flatCount`, `validCount`, median, observations, and prior-session overlap use only retained ordinary A-share rows; verify a mixed fixture produces counts equal to retained valid stocks and never to total package rows.
- [x] 2.3 Add stock-universe audit metadata and warnings to successful and failed breadth results, including policy version, raw/retained/excluded/unclassified counts, per-market retained counts, and exclusion reasons; verify existing breadth field names remain unchanged and failure fields stay null rather than zero-filled.
- [x] 2.4 Update TDX-derived `activeDirection` to rank only the shared retained ordinary A-share rows, while preserving local turnover ordering, name-resolution boundaries, industry mapping, `tdx-daily-package-derived`, and `fallback-derived`; verify Top-30/Top-10 output excludes every mixed-package non-stock row.
- [x] 2.5 Preserve Eastmoney success and fallback behavior and ensure TDX is not requested when an Eastmoney candidate succeeds; verify provider call-order regressions for breadth and activeDirection pass with the new shared classifier.
- [x] 2.6 Make breadth and active-direction failure helpers retain TDX source/audit diagnostics when classification or post-filter completeness fails; verify warnings identify the failed universe gate without presenting a pseudo-success payload.

## 3. Snapshots, Collection, and Read Semantics

- [x] 3.1 Keep the optional universe metadata serializable through the existing quality and snapshot contracts, including `fallback-derived` activeDirection compatibility; verify snapshot writes and reads preserve source, status, observations, warnings, policy version, and checksum.
- [x] 3.2 Verify collection and refresh validation reject successful writes when the filtered universe is incomplete, while mapping a valid derived activeDirection result to task/parent `partial`; cover `failed-retained` and `failed-missing` with same-date fixtures.
- [x] 3.3 Add an exact-date repair test for a known bad snapshot: successful re-collection atomically replaces only the same date with a new checksum and filtered payload; failed re-collection keeps the old snapshot and records the latest warning.
- [x] 3.4 Verify ordinary market GET, collection status, and materialized aggregate reads remain provider-free and do not cross-date backfill or auto-repair an erroneous/missing TDX snapshot.

## 4. Deterministic Fixtures and Regression Coverage

- [x] 4.1 Extend TDX fixtures with valid ordinary stock codes, fund/bond/index/warrant/B-share/depositary-receipt examples, unknown identities, duplicate identities, and both sides of the Beijing `920` effective-date boundary; verify fixtures are offline and contain no credentials or live response payloads.
- [x] 4.2 Add classifier and parser tests for policy-version selection, exclusion-reason accounting, malformed identities, missing market fields, raw-vs-filtered counts, and threshold failures; verify repeated classification is deterministic.
- [x] 4.3 Add provider tests for mixed breadth packages, missing change facts with a filtered preceding package, insufficient retained samples, incomplete market coverage, unknown-row limits, and exact-date mismatch; verify all invalid candidates return explicit degraded/failed semantics.
- [x] 4.4 Add activeDirection tests for mixed-package filtering, deterministic turnover ties after filtering, missing-name handling, incomplete industry mapping, and derived quality metadata; verify existing Top-N client fields remain compatible.
- [x] 4.5 Add snapshot/collection/API regression tests for filtered observations, checksum replacement, failed retention, parent partial status, and provider-free reads; verify the dashboard's existing breadth rendering still consumes the unchanged public count fields.

## 5. Documentation and Operational Procedure

- [x] 5.1 Update `docs/architecture.md` with the shared TDX ordinary-A-share classification boundary, policy version, raw-vs-filtered quality metadata, activeDirection scope, and no-runtime-provider GET rule; verify the architecture references this change and the active plan.
- [x] 5.2 Update `docs/runbooks.md` with diagnostic interpretation for universe counts, explicit no-write real probe requirements, exact-date re-collection of 2026-09-23/2026-09-24, failure-retention behavior, rollback by disabling TDX flags, and prohibition on direct payload edits/cross-date backfill; verify examples contain no production write commands unless explicitly marked as separately authorized.
- [x] 5.3 Update `docs/status.md` and the active plan with implementation status, verification evidence, remaining provider/production gaps, and the next authorized step; verify all required plan fields remain present.

## 6. Offline Verification and Controlled Follow-Up

- [x] 6.1 Run the focused TDX/provider/snapshot/collection pytest modules with `.venv/bin/python` and verify mixed-universe, boundary-code, failure-retention, and provider-free tests pass without network access.
- [x] 6.2 Run the full offline gates selected for the touched areas: `.venv/bin/python -m pytest tests -q`, dashboard `npm run test`, dashboard `npm run build`, `.venv/bin/python -m src.trading_system.cli docs sync-check`, and `.venv/bin/python scripts/check-docs-contract.py --mode=full`; record unavailable checks in the active plan.
- [x] 6.3 Run an explicitly authorized, read-only TDX real probe for a settled date and verify the report contains requested/source date, policy version, raw/retained/excluded/unclassified counts, market coverage, observations, and final quality without writing snapshots or printing credentials. Probes for `2026-09-23` and `2026-09-24` reported retained `5560` / `5561` and unclassified `0`.
- [x] 6.4 After separate deployment and production-write authorization, re-collect `2026-09-23` and `2026-09-24` by exact date for `breadth` and `activeDirection`; verify checksums, filtered observations, aggregate responses, collection statuses, and retained-failure warnings, then record the evidence in the active plan. Both runs completed with expected `partial` parent status because TDX-derived `activeDirection` is a derived fallback.
