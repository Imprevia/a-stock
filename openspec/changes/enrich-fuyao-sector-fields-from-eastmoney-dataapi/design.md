## Context

The existing sector collection keeps Eastmoney `push2`/`push2delay` as the formal source and uses the approved Fuyao THS catalog/snapshot contract only after both Eastmoney ranking endpoints fail. Fuyao has passed a capability probe for 320 industry rows and four fields (`code`, `name`, `changePct`, `amount`), while `mainNet`, `mainNetPct`, `upCount`, `downCount`, and `leader` remain unavailable.

The proposed Eastmoney endpoint is `https://data.eastmoney.com/dataapi/bkzj/getbkzj` with `code=m:90+s:4`. With an explicit key list it returned 128 rows containing the missing field families, but the response is latest-only, has no reliable business-date field in the payload, uses Eastmoney `BK` identities, and has a different percentage representation from the current `push2` contract. The current Tushare token cannot access the relevant industry money-flow or THS/DC index interfaces, so Tushare is not a runtime dependency for this design.

## Goals / Non-Goals

**Goals:**

- Enrich an accepted Fuyao sector result with validated same-day fields when an exact or approved identity match exists.
- Keep Fuyao's THS code, name, change percentage, and turnover as the canonical base values.
- Make source lineage, mapping coverage, field coverage, date restrictions, and warnings observable in snapshots, collection tasks, and provider-free reads.
- Reuse the existing request gate, retry budget, single-flight/cache behavior, lease, snapshot retention, and degraded quality semantics.
- Make the enrichment fully testable offline and keep real network verification to an explicitly authorized after-hours probe.

**Non-Goals:**

- Do not make `dataapi` a standalone sector fallback when Fuyao fails.
- Do not treat `data.eastmoney.com` as an independent provider or change the formal Eastmoney -> Fuyao fallback order.
- Do not use the undated dataapi response for historical dates or cross-date snapshot repair.
- Do not equate Eastmoney `BK` codes with Fuyao THS codes or infer matches from partial names, substrings, or sector ordering.
- Do not derive missing fields from 320 constituent requests, change the public `SectorRow` shape, add a database table, or add Tushare permissions as part of this change.

## Decisions

### 1. Enrich only after an accepted Fuyao base result

The collector first follows the existing Eastmoney primary/delayed path. If that path fails and the capability-gated Fuyao result passes its current date, coverage, and field checks, the collector may issue one supplemental dataapi request. A dataapi failure leaves the four-field Fuyao result valid and records an enrichment warning.

**Alternative considered:** Make dataapi a third fallback before Fuyao. Rejected because its response has no independently provable business date, covers only 128 observed rows versus the 320-row Fuyao catalog, and remains the same vendor as the failed Eastmoney path.

### 2. Request a fixed, auditable field set

The enrichment request uses the documented endpoint with a fixed `key` query parameter:

```text
key=f3,f6,f62,f104,f105,f128,f184
```

`f62`, `f184`, `f104`, `f105`, and `f128` are the target missing fields. `f3` and `f6` are requested for row sanity checks and do not replace the Fuyao canonical change/amount values. Unknown or extra fields are ignored.

**Alternative considered:** Request only `f62` because it was the supplied URL. Rejected because a single request can return all currently missing field families and a fixed list is easier to audit and test.

### 3. Keep Fuyao identity canonical and join conservatively

Each Fuyao row remains keyed by its THS identity. A versioned mapping table may map THS code to an Eastmoney BK code when independently reviewed. Without an explicit mapping, the only permitted fallback is an exact normalized-name match that produces one candidate and passes a change/amount sanity check. Name collisions, taxonomy conflicts, and unmatched rows remain unfilled.

The quality metadata records `mappingRevision`, `matchMethod`, `matchedRows`, `unmatchedRows`, and `identityCoverage`. The Eastmoney BK code is retained only as supplemental provenance, never exposed as the canonical sector code.

**Alternative considered:** Join by row rank or fuzzy name similarity. Rejected because the providers expose different industry taxonomies and sort orders; such joins can silently assign one industry's money flow to another.

### 4. Normalize before merging

The adapter validates required identity and numeric values before merging. It normalizes Eastmoney's integerized percentage representation into the canonical floating-point percentage only after the scale is confirmed by fixture and contract tests. `f62` remains an amount, `f104`/`f105` remain non-negative counts, and `f128` is accepted only as a non-empty security name. Invalid or ambiguous values remain `null` and contribute to a warning.

The merge is fill-only: it writes a supplemental value only when the Fuyao field is `null`; it never overwrites Fuyao `code`, `name`, `changePct`, or `amount` with Eastmoney values.

### 5. Enforce latest-only date semantics

Because the dataapi endpoint has no request-date parameter or trustworthy business-date field, the enrichment is allowed only when the collection coordinator has already established that the request is for the current Shanghai market date and within the accepted latest-only/settlement boundary. The effective collection date, request time, and date-evidence reason are recorded. Historical requests skip the dataapi call entirely.

**Alternative considered:** Use the HTTP `Date` header or undocumented response metadata as an exact market date. Rejected because transport time is not a trading-session proof and could label an intraday/latest response as a settled historical observation.

### 6. Preserve degraded quality and lineage

The result quality remains `fallback` or `partial`; enrichment never upgrades it to `ok`. The quality payload gains additive metadata for supplemental source, requested fields, field coverage, match coverage, mapping revision, date evidence, and warnings. A successful dataapi call is described as same-vendor supplemental evidence, not independent provider confirmation.

Collection status, collection-run responses, materialized aggregates, and snapshot reads use the stored payload only. They do not re-request either provider to calculate or display enrichment metadata.

### 7. Apply shared transport and caching controls

`data.eastmoney.com` is registered with the existing Eastmoney host policy. Requests share the provider serialization gate, bounded retry rules, 429/5xx handling, request budget, and single-flight cache. The cache key includes the complete endpoint parameters and the effective current market date, even though the upstream request itself is undated, preventing a response from being reused across market dates.

### 8. Keep Tushare out of the implementation path

The current token returned no permission for `moneyflow_ind_ths`, `moneyflow_ind_dc`, `ths_index`, `ths_daily`, `dc_index`, `dc_member`, `index_member`, or `index_dailybasic`. `index_daily` was available but lacks the required industry money-flow/breadth/leader fields. The design therefore records Tushare as an investigated but unavailable alternative; a future permission upgrade requires a separate capability probe and change.

## Risks / Trade-offs

- [The same vendor may fail through both endpoint families] -> Keep Fuyao as the accepted base fallback, record the dataapi source separately, and do not claim independent-provider resilience.
- [Only a subset of Fuyao rows can be matched] -> Expose row and field coverage, keep unmatched fields `null`, and keep quality degraded.
- [Industry taxonomy or name changes cause false joins] -> Use an explicit mapping revision, exact normalized-name matching only, collision detection, and change/amount sanity checks.
- [Percentage scale is misinterpreted] -> Block ambiguous values, add fixtures for both source representations, and validate normalization against known responses.
- [Latest-only data is mistaken for historical evidence] -> Gate on current-date eligibility, record date evidence, and skip dataapi for every historical request.
- [Supplemental requests add latency or rate pressure] -> One bounded request per sector task, shared host gate, short current-date cache, and no request when the Fuyao row already has all fields.

## Migration Plan

1. Add offline dataapi fixtures and normalization/mapping tests without changing production switches.
2. Implement the supplemental adapter and additive quality metadata behind a disabled or local-only control, then run provider, collection, API, and snapshot-retention focused tests.
3. Run an authorized after-hours read-only probe to measure response stability, percentage scale, 128-row coverage, name overlap, and current-date behavior; do not write a formal snapshot from the probe.
4. Review the mapping revision and coverage threshold. Keep enrichment disabled if coverage or date evidence is insufficient.
5. Enable the reviewed control only in a controlled current-date collection, observe task lineage and warnings, and keep Fuyao's four-field result as the rollback-safe base.
6. Roll back by disabling enrichment. Existing Fuyao fallback, same-date retention, provider-free reads, and public response compatibility remain unchanged.

## Open Questions

- The minimum acceptable identity coverage threshold for treating the enrichment as useful is a product decision; the implementation can report coverage without changing the base fallback behavior while that threshold is reviewed.
