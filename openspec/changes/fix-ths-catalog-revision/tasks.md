## 1. Plan and Fact Documentation

- [x] 1.1 Create `docs/exec-plans/active/fix-ths-catalog-revision.md` with Stage, Status, Acceptance, Completion Evidence, Remaining Gaps, and Next Step; add it to the active-plan index and verify `python scripts/check-docs-contract.py --mode=fast` passes before changing code
- [x] 1.2 Update `docs/architecture.md`, `docs/product-specs/market-environment-dashboard.md`, `docs/runbooks.md`, `docs/repository-guide.md`, `docs/status.md`, and the existing THS active-plan cross-reference with the date-and-content observation identity, narrow `0007` constraint-removal decision, partial-data semantics, diagnostic compatibility, and separately authorized rollout; verify every affected code-to-doc mapping is covered

## 2. Catalog Identity and Provider Normalization

- [x] 2.1 Add provider-neutral snapshot-observation availability, row quality/warnings, `missingLiveCodes`, and `missingRankingCodes` contracts without allowing an all-null `ThsSectorBar`; verify `tests/test_market_environment_ths_sector_domain.py` covers all-null, changePct-only, bar-without-changePct, and shared-code cases
- [x] 2.2 Add one deterministic helper for the complete-relation checksum and `provider + capabilityRevision + Shanghai date + full checksum` catalog observation ID; verify row order and timestamp drift do not affect the ID, same-day catalog changes do, and identical cross-date content produces different IDs
- [x] 2.3 Rename adapter/bootstrap inputs so the configured value is explicitly a capability revision, then normalize and validate all four complete catalogs before snapshot-value classification; verify `tests/test_market_environment_fuyao_ths_sector.py` retains every sparse relation and derives counts/checksum before value reconciliation
- [x] 2.4 Keep response identity, duplicate, cross-tag name, timestamp, and exact-date checks fail-closed before publication; verify missing/extra/duplicate/wrong-date fixture tests fail while a present all-null row becomes accepted partial evidence

## 3. Persistence and Atomic Commit

- [x] 3.1 Persist and load ranking row quality/warnings instead of hard-coding `ok`, add explicit-revision and deterministic latest-compatible-revision repository queries, and verify same-date revisions never merge in `tests/test_market_environment_postgres_ths_sector.py`
- [x] 3.2 Carry both gap sets and coverage counts through ranking candidate serialization/decoding, create bars only for proven OHLC/volume/turnover rows, and enforce complete-ranking plus `barCodes ∪ missingLiveCodes = catalogCodes` atomic invariants; verify valid partial commits and every unknown/duplicate/contradictory gap rejection in `tests/test_market_environment_ths_datasets.py`
- [x] 3.3 Make explicit THS catalog-sync operations reuse the same revision derivation, complete-catalog, ranking, and no-null-bar logic as daily collection; verify `tests/test_market_environment_ths_sector_operations.py` cannot reintroduce the fixed-revision path
- [x] 3.4 Add Alembic `0007_ths_catalog_identity` with a revision ID no longer than the default 32-character version column to remove only `UNIQUE (provider, capability_revision, checksum, fetched_at)`, advance runtime/fresh-schema version to 10, and add real-version-table plus repository/transaction regression coverage proving two dates with identical content and fetched timestamp coexist while legacy fixed revisions, old rankings/bars, and failed/blocked attempts remain unchanged

## 4. Downstream Compatibility and Materialization

- [x] 4.1 Update `sector-turnover` to consume one exact compatible revision, publish only proven bars, and report expected/bar/missing coverage as partial; verify a declared live-value gap does not block turnover and no missing numeric value becomes zero
- [x] 4.2 Filter null or insufficient ranking rows before breadth Top-N selection and return per-tag `insufficient` evidence when valid candidates are below the configured count; verify sufficient partial inputs execute and insufficient classifications never present a shorter list as complete in domain/dataset tests
- [x] 4.3 Enforce same-date/same-revision prerequisite predicates and propagate partial outcomes through the existing DAG while retaining hard blocks for absent, invalid-date, and revision-mismatched evidence; verify `tests/test_market_environment_ths_collection_dag.py` covers partial execution, true blocks, targeted retry reuse, and unrelated sibling isolation
- [x] 4.4 Preserve catalog revision, row quality, nullable values, coverage counts, and warnings through dataset snapshots and Chapter 01 materialization; verify provider-free round trips and retained partial evidence in `tests/test_market_environment_sector_materialization.py`

## 5. Diagnostics API and Dashboard

- [x] 5.1 Implement the bounded `THS_DIAGNOSTIC_V1` warning codec/parser and stable THS reason codes with safe fallback to legacy or malformed text; verify round-trip, sample bounds, retryability, blockedBy, and secret/raw-payload exclusion tests
- [x] 5.2 Add optional typed THS diagnostics and one consistent opaque catalog-revision field to HTTP/OpenAPI models and collection/Chapter responses without breaking legacy payloads; verify `tests/test_market_environment_api.py`, `tests/test_market_environment_ths_http.py`, and provider-call counters prove status/GET reads remain local
- [x] 5.3 Update frontend collection types/view models and `/data-collection` rendering to show usable/expected counts, bounded missing codes, reason code, and upstream dependency details instead of generic failure/block text; verify component tests cover partial, failed, blocked, and legacy-warning records
- [x] 5.4 Update the sector page to display partial ranking and row-level unavailable states, retain null values, and prevent unrankable rows from being Top-N breadth inputs; verify `Document05SectorsPage.test.ts` covers all-null and missing-changePct rows
- [x] 5.5 Verify all new visible text is at least 14px and the data-collection and sector views remain usable at desktop and 390px widths without page-level horizontal overflow or overlap

## 6. Offline Verification and Completion Evidence

- [x] 6.1 Run the focused THS provider/domain/repository/operations/dataset/DAG/materialization/API test files and record the exact passing commands and counts in the active plan
- [x] 6.2 Run `python -m pytest tests -q` and record any skipped or environment-blocked checks explicitly; the implementation phase is not complete while an unexplained failure remains
- [x] 6.3 Run `npm run test` and `npm run build` in `apps/market-environment-dashboard/` and record both outcomes in the active plan
- [x] 6.4 Run `openspec validate fix-ths-catalog-revision --strict` and `python scripts/check-docs-contract.py --mode=full`, then update Status, Completion Evidence, Remaining Gaps, and Next Step in the active plan and `docs/status.md`
- [x] 6.5 Add and test a controlled `--disable-manual-refresh` deployment entry that uses one reviewed full same-image packet, permits only literal manual refresh `1 -> 0`, runs hook-free with scheduling absent and every retained Job proven terminal `Complete=True` or `Failed=True`, preserves stored hooks plus PVC/Secret/image identity, rejects terminating resources, compares all managed live resources including PostgreSQL StatefulSet/PVC before writing, and verifies the Ready runtime Pod remains on the frozen image with manual collection off
- [x] 6.6 Make generic `all`/`service` production candidates require a clean worktree and matching full `REVIEWED_GIT_HEAD`, freeze the imported containerd manifest digest, recheck it before Helm writes, and verify Deployment/ReplicaSet/Ready-Pod runtime identity after rollout; cover every pre-write drift with zero target writes
- [x] 6.7 Make `--disable-schedule` capture the complete namespace terminal-Job set by name/UID/terminal condition, reject any non-terminal Job, run the scheduling Helm write hook-free, delete the retained CronJob with orphan propagation, and fail closed if deletion fails or the Job set, identity, or terminal condition changes; record the already garbage-collected production Job as an irreversible gap without recreating it

## 7. Separately Authorized Production Rollout

- [ ] 7.1 After explicit production authorization, capture the read-only release/image, PVC/Secret, PostgreSQL schema, capability, legacy catalog/ranking, and 2026-10-14 failed/blocked baseline; disable the exact scheduled collector and manual collection through their dedicated controlled entries, verify no active writer remains, and explicitly record without reconstruction any accepted irreversible Kubernetes audit gap
- [ ] 7.2 Create an immutable PostgreSQL custom-format backup, record its bytes/SHA-256/PVC identity, restore it into isolated PostgreSQL 16, apply `0007`, and verify schema version 10, the targeted constraint removal, cross-date observation coexistence, plus legacy successful and failed audit evidence before deployment
- [ ] 7.3 Deploy one clean-HEAD-bound immutable image with scheduling/manual collection off, freeze and verify its imported/runtime manifest digest, and verify health, provider-free GETs, unchanged schema/PVC/Secret/capability/history, and zero provider calls before enabling any write
- [ ] 7.4 After the Shanghai settlement boundary and separate provider-write authorization, run only the dependency-aware THS trio and verify the new observation ID, complete relation/ranking counts, bars plus declared gaps, absence of zero placeholders, precise diagnostics, and non-generic downstream outcomes
- [ ] 7.5 Restore the reviewed schedule only through explicit authorization, observe at least two completed Shanghai trading dates for retry idempotency and cross-date lineage, and close or explicitly record any remaining production gap without deleting additive evidence
