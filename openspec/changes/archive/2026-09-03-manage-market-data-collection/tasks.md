## 1. Plan And Documentation Baseline

- [x] 1.1 Create and index an active exec plan with the required status, acceptance, evidence, gaps, and next-step fields before changing application code.
- [x] 1.2 Update the market-environment product specification for the data-collection management workflow, independent failure semantics, page navigation, and manual-refresh boundary.
- [x] 1.3 Update `docs/architecture.md` and `docs/runbooks.md` for collection runs/tasks, materialized aggregates, API paths, configuration, date rules, recovery, and local operation.

## 2. Persistent Collection State

- [x] 2.1 Add idempotent SQLite migrations for collection runs, collection tasks, core-index sub-results, and materialized market-environment aggregates while preserving existing snapshots.
- [x] 2.2 Add typed store models and operations for creating runs/tasks, transitioning task states, recording timings and warnings, and querying the latest attempt by dataset/date.
- [x] 2.3 Add storage operations that distinguish current exact-date snapshot availability from the latest collection-attempt result.
- [x] 2.4 Add store tests for schema migration, state transitions, exact-date isolation, retained successes, expired active tasks, and aggregate atomic replacement.

## 3. Collection Coordinator

- [x] 3.1 Define the supported collection datasets and shared status/result contracts for `core`, `breadth`, `limits`, `sectors`, and `activeDirection`.
- [x] 3.2 Implement a collection coordinator that creates parent runs, executes every requested task despite sibling failures, and derives `success`, `partial`, or `failed` parent status.
- [x] 3.3 Reuse dataset/date leases so duplicate single-item or full-run requests do not issue duplicate provider calls.
- [x] 3.4 Extend collection to `breadth`, `limits`, `sectors`, and `activeDirection` with independent validation, success commit, failure recording, and same-date retention.
- [x] 3.5 Implement `core` collection with five isolated index sub-results, same-date per-index retention, and `success`, `partial`, or `failed` core status.
- [x] 3.6 Enforce provider date capabilities, historical rejection for unverified latest-only datasets, and provisional versus settled lifecycle states.
- [x] 3.7 Add coordinator tests proving a failed dataset does not stop or roll back successful siblings and a failed core index does not remove other index results.

## 4. Aggregate And Read Path

- [x] 4.1 Extract aggregate construction so it can combine the latest successful same-date dataset snapshots without calling providers.
- [x] 4.2 Rebuild and response-model validate the materialized aggregate after each successful task, then replace it atomically.
- [x] 4.3 Preserve retained same-date evidence and explicit missing/insufficient values when rebuilding partial or degraded aggregates.
- [x] 4.4 Change existing market-environment query paths to prefer local aggregates or snapshots and never start provider collection from a normal GET request.
- [x] 4.5 Add compatibility and performance tests asserting existing fields remain valid, active collection does not block reads, provider calls are zero, and warm local reads complete within 500 milliseconds.

## 5. Collection Management API And CLI

- [x] 5.1 Add response/request schemas for collection status, parent runs, dataset tasks, core-index sub-results, and requested dataset validation.
- [x] 5.2 Implement the provider-free exact-date collection status endpoint with availability and latest-attempt states for all five datasets.
- [x] 5.3 Implement the asynchronous collection-run POST endpoint using a bounded in-process executor and return HTTP 202 before provider work completes.
- [x] 5.4 Implement collection-run progress lookup, duplicate active-task reuse, and expired-task recovery after a service restart.
- [x] 5.5 Add `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED`, reject disabled write operations, and permit only the required controlled development POST behavior.
- [x] 5.6 Refactor the existing snapshot CLI to reuse the collection coordinator while preserving explicit dataset selection and auditable output.
- [x] 5.7 Add API tests for disabled access, invalid dates, single-item collection, full partial collection, polling, busy tasks, restart recovery, and provider-free status reads.

## 6. Data Collection Page

- [x] 6.1 Add a kebab-case `/data-collection` application view and a separate “数据管理” sidebar entry without changing the 01-09 document hierarchy.
- [x] 6.2 Add frontend types and API helpers for collection status, starting single/full runs, and polling task progress with stale-response protection.
- [x] 6.3 Build the work-focused collection table showing availability, latest attempt, source, observations, last success, duration, warning, and per-row retry action.
- [x] 6.4 Add the selected-date controls, provider-free status refresh, and “全部重新采集” action with completed/total progress.
- [x] 6.5 Add expandable core-index details for the five configured indices and distinguish failed-retained from failed-missing states.
- [x] 6.6 Keep existing data visible during collection, refresh status after completion, and support targeted retry after a partial run.
- [x] 6.7 Hide or disable write actions when manual refresh is unavailable and explain date-capability restrictions without allowing an invalid request.
- [x] 6.8 Add responsive and accessibility styling so desktop and 390-pixel mobile layouts have readable states, stable controls, and no page-level horizontal overflow.

## 7. Verification And Completion

- [x] 7.1 Add frontend unit tests for status mapping, polling completion, duplicate response protection, row retry, full collection, disabled actions, and core expansion.
- [x] 7.2 Run focused backend tests, the full Python test suite, frontend tests, and the production frontend build.
- [x] 7.3 Perform browser QA for desktop and 390-pixel mobile views, including a forced partial run where one dataset fails and successful siblings remain available.
- [x] 7.4 Verify OpenSpec strict validation and `python scripts/check-docs-contract.py --mode=full`.
- [x] 7.5 Update the active plan completion evidence, remaining gaps, next step, and `docs/status.md`, then archive the completed exec plan when all acceptance criteria pass.
