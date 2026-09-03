## 1. Planning And Documentation

- [x] 1.1 Create and index an active exec plan with required acceptance, evidence, gaps, and next-step fields before application code changes.
- [x] 1.2 Update the market-environment product specification, architecture, and runbook for server-derived collection dates, serialized Eastmoney recovery, sector fallback, and leader-field semantics.

## 2. Eastmoney Request Stability

- [x] 2.1 Implement a shared serialized Eastmoney request boundary that covers rate-limit waiting and the complete HTTP request across collection workers.
- [x] 2.2 Add bounded retries for transient connection/read failures, HTTP 429, and HTTP 5xx while preserving immediate non-retryable HTTP 403 behavior.
- [x] 2.3 Add deterministic tests for concurrent serialization, retry recovery, retry exhaustion, and no retry on HTTP 403.

## 3. Sector Provider Recovery And Contract

- [x] 3.1 Add primary `push2` to `push2delay` sector-ranking fallback with payload validation, auditable source, and primary-failure warnings.
- [x] 3.2 Request the real leader field group and map the API `leader` value from `f128`, leaving it null when the optional name is absent.
- [x] 3.3 Add provider and collection tests for primary success, delayed fallback, both endpoints failing, same-date retention, cross-date isolation, and realistic leader fields.

## 4. Collection Page Date Initialization

- [x] 4.1 Allow the collection status client to omit `as_of` on first load, initialize the selected date from the server response, and preserve explicit dates after user changes.
- [x] 4.2 Add frontend tests proving the collection page uses the server market date while the research dashboard keeps its existing settlement-oriented cutoff behavior.

## 5. Verification And Evidence

- [x] 5.1 Run focused and full Python tests, frontend tests, and the production frontend build.
- [x] 5.2 Run an explicit current-market-date sector smoke test, OpenSpec strict validation, and the full docs-contract gate.
- [x] 5.3 Update the active plan completion evidence, remaining gaps, next step, and `docs/status.md`; archive the exec plan only after all acceptance criteria pass.
