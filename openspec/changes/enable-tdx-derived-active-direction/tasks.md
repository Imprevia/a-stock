## 1. Configuration and TDX-derived provider path

- [x] 1.1 Add `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED` with strict boolean parsing and a fail-closed default of `0`; verify default, accepted values, and invalid-value tests pass.
- [x] 1.2 Wire the new active-direction-only flag through the provider construction path and Helm Deployment/CronJob templates without changing the existing breadth fallback flag; verify Helm render shows the new variable as disabled by default and existing values validation passes.
- [x] 1.3 Extend the active-direction fallback chain so Eastmoney primary and delayed paths are exhausted before the TDX path is attempted, and verify provider-success tests prove no TDX request occurs when either Eastmoney path succeeds.
- [x] 1.4 Implement deterministic TDX-derived ranking using turnover descending and normalized security identity ascending as the tie-breaker; verify unsorted fixture rows produce stable Top-30/Top-10 output across repeated runs.
- [x] 1.5 Add `tdx-daily-package-derived` / `fallback-derived` quality metadata, including `derived`, ranking method, pinned TDX revision, and retained upstream warnings; verify the serialized payload preserves existing Top-10 fields and exposes the new audit fields.
- [x] 1.6 Add bounded missing-name resolution for only the candidate Top-N rows and reject unresolved or code-as-name rows without replacing TDX price, amount, or date facts; verify success and failure fixtures cover both paths.

## 2. Industry mapping and active-direction semantics

- [x] 2.1 Add a versioned industry-mapping boundary that returns mapped industries and coverage without committing an unreviewed full-market data snapshot; verify a complete mapping enables cluster derivation and an incomplete mapping returns `insufficient`/`unverified` with coverage metadata.
- [x] 2.2 Keep TDX-derived activeDirection latest-only and exact-date guarded; verify historical requests are rejected before provider calls and package date mismatches cannot be written under another date.
- [x] 2.3 Preserve Eastmoney provider-ranked validation and reject its unsorted rows while permitting local sorting only for the explicitly derived TDX path; verify both source-specific ordering contracts in provider tests.

## 3. Collection, snapshot, and API quality handling

- [x] 3.1 Extend the accepted quality-status set so `fallback-derived` can be persisted as a valid exact-date snapshot while remaining distinguishable from `ok` and ordinary `fallback`; verify snapshot writes and normal reads retain the source and quality metadata.
- [x] 3.2 Map a committed `fallback-derived` result to collection task `partial` and parent run `partial`, without deleting or replacing same-date snapshots on later failure; verify collection integration tests cover derived success, failed-retained, and failed-missing.
- [x] 3.3 Verify data-collection status and ordinary market GET paths remain provider-free and expose the derived source, ranking method, mapping coverage, and latest warning from local state only.

## 4. Dashboard and documentation

- [x] 4.1 Add localized quality labels and fallback styling for `fallback-derived`, and display the derived source/ranking warning in the active-direction and collection views without changing existing Top-10 rendering; verify Vitest component and composable tests pass at desktop and mobile widths.
- [x] 4.2 Update `docs/architecture.md`, `docs/runbooks.md`, the relevant product documentation, and a new active execution plan with the flag, source/quality semantics, probe procedure, and rollback path; verify `python scripts/check-docs-contract.py --mode=full` passes.
- [x] 4.3 Record the pinned `a-stock-data` revision, Apache-2.0 attribution, no-runtime-GitHub dependency boundary, and prohibition on real data snapshots or cross-date backfill; verify the documentation and repository checks contain no credential or runtime artifact.

## 5. Verification and controlled rollout

- [x] 5.1 Add deterministic fixtures and provider tests for Eastmoney success, both Eastmoney failures, unsorted TDX rows, equal-amount ties, insufficient rows, missing names, date conflicts, mapping coverage, and all-path failure; verify the focused pytest suite passes without real network access.
- [x] 5.2 Add an explicit redacted TDX-derived real-probe/report path that records requested/source date, market counts, valid rows, name coverage, ranking method, mapping coverage, source revision, and final quality without writing snapshots; verify the probe requires explicit authorization and never prints credentials.
- [x] 5.3 Run backend, frontend, rules/docs, and Helm offline verification selected for the touched files, including `python -m pytest tests -q`, dashboard `npm run test`, dashboard `npm run build`, `python scripts/check-docs-contract.py --mode=full`, and Helm render/lint; record any unavailable environment checks in the active plan.
- [ ] 5.4 Deploy only after the offline gates and redacted real probe pass, enabling the new flag independently from breadth; verify one post-settlement scheduled collection reports the expected `fallback-derived` quality or a precise retained failure, then document rollback by disabling only the new flag.
