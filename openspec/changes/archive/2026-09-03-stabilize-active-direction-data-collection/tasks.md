## 1. Planning And Facts

- [x] 1.1 Create `docs/exec-plans/active/stabilize-active-direction-data-collection.md` with all required plan fields and add it to `docs/exec-plans/active/_index.md` before application code changes.
- [x] 1.2 Update the market-environment product specification to require primary-to-delayed active-direction fallback, shared Top-N validation, auditable quality metadata, and exact-date failure retention.
- [x] 1.3 Update `docs/architecture.md`, `docs/runbooks.md`, and `docs/status.md` with the capacity-direction data flow, fallback source, failure interpretation, and verification path.

## 2. Provider Fallback Implementation

- [x] 2.1 Refactor active-direction acquisition into a URL-parameterized internal fetch path that reuses the existing request parameters and accepts array or keyed-object `data.diff` responses.
- [x] 2.2 Apply the existing required code/name/turnover fields, minimum 30-row sample, and non-increasing turnover-order validation identically to primary and delayed responses.
- [x] 2.3 Add a primary `push2` to delayed `push2delay` fallback chain that preserves both failure reasons when neither endpoint returns a valid payload.
- [x] 2.4 Parameterize active-direction result construction so primary success reports `eastmoney-clist` / `partial`, while delayed success reports `eastmoney-clist-delay` / `fallback` and retains the primary failure warning.
- [x] 2.5 Preserve the existing Top-30 industry clustering, Top-10 stock output, current-market-date restriction, null semantics, and public response fields without adding a storage or frontend special case.

## 3. Automated Tests

- [x] 3.1 Add provider tests proving primary success does not call the delayed endpoint and retains the primary quality metadata.
- [x] 3.2 Add provider tests proving primary failure followed by a valid delayed keyed response returns fallback metadata, the primary warning, and unchanged derived Top-30/Top-10 semantics.
- [x] 3.3 Add provider tests proving too-small, missing-field, and unsorted delayed responses are rejected and that double-endpoint failure exposes both errors.
- [x] 3.4 Add collection or snapshot tests proving a double-endpoint failure produces `failed-retained` with a same-date success, `failed-missing` without one, and never substitutes another date.
- [x] 3.5 Run the focused market-environment provider, collection, service, and snapshot-store tests and resolve all regressions.

## 4. Verification And Evidence

- [x] 4.1 Run the full Python test suite and confirm no existing market-environment, trading-rule, CLI, or deployment behavior regresses.
- [x] 4.2 Execute a current Shanghai market-date `activeDirection` collection smoke test and verify a primary disconnect can save 30 observations from `eastmoney-clist-delay` with `fallback` quality and an auditable warning.
- [x] 4.3 Run `openspec validate stabilize-active-direction-data-collection --strict`, the full docs-contract gate, and `git diff --check`.
- [x] 4.4 Update the active plan `Status`, `Completion Evidence`, `Remaining Gaps`, and `Next Step`, then move the completed plan according to the repository plan lifecycle.
