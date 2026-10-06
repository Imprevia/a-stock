## 1. Contract and fixture foundation

- [x] 1.1 Define the additive sector enrichment quality metadata, source lineage, requested fields, date evidence, mapping revision, and row/field coverage; verify the Pydantic/API contract accepts enriched, base-only, and failed-enrichment payloads without changing existing `SectorRow` fields.
- [x] 1.2 Add redacted offline fixtures for complete dataapi rows, partial 128-row coverage, malformed values, ambiguous percentage scale, duplicate names, and missing leader names; verify fixtures contain no token, cookie, or private response headers.
- [x] 1.3 Implement the versioned THS-to-Eastmoney identity policy and normalized-name matcher with collision detection; verify exact matches, unmatched rows, duplicate candidates, taxonomy conflicts, and mapping coverage with deterministic tests.

## 2. Eastmoney supplemental provider

- [x] 2.1 Register `data.eastmoney.com` with the existing host transport policy and cache/single-flight controls; verify bounded retry, 429/5xx handling, cooldown, and date-isolated cache keys with focused transport tests.
- [x] 2.2 Implement the fixed dataapi request using `f3,f6,f62,f104,f105,f128,f184` and `code=m:90+s:4`; verify the adapter rejects malformed envelopes, missing rows, invalid numeric values, and unsupported response shapes.
- [x] 2.3 Enforce current Shanghai latest-only eligibility before any dataapi request; verify historical requests, pre-settlement requests, and responses without acceptable current-date evidence make zero supplemental calls.
- [x] 2.4 Normalize Eastmoney percentage and amount/count fields and perform fill-only merging into accepted Fuyao rows; verify Fuyao code/name/change/amount remain authoritative and ambiguous scale is rejected rather than silently persisted.
- [x] 2.5 Preserve base Fuyao data when supplemental collection fails or only partially matches; verify unmatched fields remain `null`, quality stays `fallback`/`partial`, and warnings identify source, date, and coverage limitations.

## 3. Collection, snapshot, and API integration

- [x] 3.1 Integrate enrichment into the existing sectors task after Fuyao acceptance and within the existing `(dataset, as_of)` lease; verify sibling dataset tasks continue when enrichment fails and a valid Fuyao base snapshot is committed.
- [x] 3.2 Persist supplemental lineage and coverage in the sector snapshot without adding a database table; verify a later total failure produces `failed-retained` or `failed-missing` according to same-date retention and never uses another date.
- [x] 3.3 Expose stored enrichment metadata through collection task, collection-run, status, materialized aggregate, and `chapter-01` responses; verify provider-free reads make zero Eastmoney, Fuyao, and Tushare calls.
- [x] 3.4 Add API/contract tests for base-only Fuyao, partially enriched Fuyao, complete matched fields, dataapi failure, date rejection, and mapping conflicts; verify old consumers can ignore the additive metadata.

## 4. Dashboard and documentation

- [x] 4.1 Update the industry page and collection-status presentation to show supplemental source/coverage warnings without labeling same-vendor enrichment as an independent provider; verify empty, base-only, and partial-enrichment states in Vitest.
- [x] 4.2 Update `docs/architecture.md`, `docs/runbooks.md`, `docs/product-specs/market-environment-dashboard.md`, the sector active plan, and `docs/status.md` with endpoint fields, latest-only/date limits, mapping policy, rollback, and the current Tushare permission result; verify docs references and no credential material are introduced.
- [x] 4.3 Keep deployment defaults and secrets unchanged; verify Helm render leaves enrichment disabled or explicitly controlled and never renders the Tushare token or Eastmoney response data.

## 5. Verification and controlled rollout

- [x] 5.1 Run focused backend provider/collection/API/snapshot tests and verify all new field, scale, identity, date, and retention scenarios pass.
- [x] 5.2 Run frontend tests/build, `python -m src.trading_system.cli docs sync-check`, `python scripts/check-docs-contract.py --mode=full`, and `openspec validate enrich-fuyao-sector-fields-from-eastmoney-dataapi --strict`; record outputs in the active plan.
- [ ] 5.3 In an explicitly authorized after-hours isolated environment, run a read-only dataapi/Fuyao coverage probe and verify response stability, percentage scale, match coverage, current-date evidence, and redacted output without writing a formal sector snapshot.
- [ ] 5.4 Perform one controlled current-date collection only after review of the probe and mapping revision; verify task lineage, partial quality, same-date behavior, provider-free reads, and rollback by disabling enrichment without deleting snapshots or PVCs.
