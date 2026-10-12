## Context

See `proposal.md` for motivation and `specs/` for behavior. The current runtime has a legacy `sectors` dataset whose Fuyao adapter reads only `tag=industry`, validates a complete catalog/snapshot batch, then projects only Top 10 rows into the old `SectorRow` contract. The full catalog is not persisted, the compatible projection discards `volume`, historical THS bars are not a dataset, and a sector-only success can leave Chapter 01 unmaterialized.

The working tree also contains the independent `add-sector-continuity-metrics` implementation. That capability owns canonical Shenwan Level 1 point-in-time membership and `QTS-01-05-*` inputs. This change must compose with its `sectorAnalysis` output without changing its industry identities, backfill, rules, or evidence.

Fuyao documents four catalog tags and separate snapshot, one-code historical K-line, full-market daily dump, recent incremental dump, and adjustment-factor dump contracts. The official dynamic discovery index is `https://fuyao.aicubes.cn/llms-full.txt`; endpoint schemas adopted by code are frozen through local typed ports, fixtures, capability revisions, and checksums rather than by vendoring that remote document.

## Goals / Non-Goals

**Goals:**

- Give the four THS classifications durable, searchable identities and complete current-day rankings.
- Preserve daily OHLC, raw volume, and turnover without conflating field semantics.
- Make history acquisition bounded, resumable, idempotent, and isolated per code/window.
- Compute complete current-day breadth for stable Top 10 and user-selected codes from verified member facts.
- Make every normal read local and keep provider/import operations explicit, authorized, and auditable.
- Replace the legacy public contract end to end while preserving its stored audit evidence.

**Non-Goals:**

- No real provider probe, production migration, first production backfill, deployment, schedule activation, or production data write in the default implementation scope.
- No historical breadth from current constituents and no historical THS constituent reconstruction.
- No automatic THS-to-Shenwan mapping and no change to existing trading-rule IDs or thresholds.
- No persistence of API keys, presigned URLs, raw provider responses, or the remote Fuyao documentation corpus.

## Decisions

### 1. Treat catalog relations and code market facts as different aggregates

Persist a catalog revision envelope keyed by provider, capability revision, canonical catalog checksum, and fetched time. Persist catalog relations by `(catalog_revision_id, tag, thscode)` and a provider-scoped code identity by `thscode`. A code can have multiple tag relations but its daily bar is stored once by `(thscode, trading_date, source_revision)`.

This avoids duplicating market facts when a code appears under multiple tags while preserving the exact classification revision used by every ranking. Storing four unrelated code lists was rejected because it makes cross-tag reuse and revision reconciliation ambiguous.

### 2. Use normalized repositories for durable facts and dataset snapshots for daily presentation

Add normalized PostgreSQL repositories for catalog revisions/relations, current constituent revisions, sector daily bars, member daily facts, backfill runs/checkpoints, and breadth evidence. The three daily collection tasks still commit typed dataset snapshots so they participate in leases, failure retention, status, and Chapter 01 materialization.

The normalized tables are the source for catalog/K-line/progress GETs; daily snapshots are the source for exact-date dashboard projections. Reusing the legacy JSON snapshot as the only store was rejected because it cannot support revision search, one-code pagination, checkpoint recovery, or uniqueness constraints.

### 3. Use additive migration and preserve legacy rows verbatim

Create the next additive Alembic revision after the in-flight sector-continuity migration. It adds new tables and indexes only. Existing `market_dataset_snapshots`, task history, capability reports, and materialized aggregates containing `dataset='sectors'` are neither updated nor deleted.

The public enum and new writes reject `sectors`, while administrative repository reads can still inspect old rows. A data migration that relabels old payloads was rejected because legacy Top 10 compatibility rows cannot prove four catalogs, OHLCV history, or breadth.

### 4. Split provider contracts by operation and capability revision

Define typed provider ports for catalog+snapshot, current constituents, one-code historical bars, and dump metadata/content. Each operation resolves an exact eligible capability report before constructing a network client. The existing Fuyao HTTP transport and parsers may be reused, but approval for the old `fuyao/sectors/fuyao-market-v2` contract does not authorize constituents, history, or dumps.

Capability evidence records endpoint identities, tag coverage, constituent identity/date semantics, schema/field units, exact-date samples, permissions, rate limits, request budget, and redacted download behavior. One broad provider switch was rejected because catalog, constituents, history, and presigned dumps have different permissions, budgets, and failure modes.

### 5. Make ranking and daily turnover share one complete snapshot normalization

`industry-ranking` synchronizes all four catalogs and obtains the complete batched current snapshot. It validates unique code coverage, provider timestamps, trading date, required fields, and classification revision, then persists all ranks.

The normalized current snapshot also supplies same-day sector bars to `sector-turnover`; the dependent task commits its own snapshot only after all accepted codes are stored with field-level quality. Sharing the normalized input avoids a duplicate provider call while keeping task states independent. A Top 10-only projection was rejected because it hides directory completeness and prevents later code selection.

### 6. Separate volume, turnover, and adjusted price semantics

Sector bars retain provider `volume` and `turnover` in separate columns and never substitute one for the other. Member facts retain original same-day volume/turnover separately from adjusted close history. Adjustment factors apply only to price-derived calculations.

Missing field semantics are `null` plus a reason. This follows the repository invariant that missing data is not zero and prevents the existing core historical projection, which discards volume, from being reused as the sector history use case.

### 7. Backfill by deterministic code/window checkpoints

Create a parent backfill run with immutable requested codes, date range, capability revision, and request budget. Normalize unique codes in ascending order and split date work into provider-supported windows. Checkpoints are keyed by `(run_id, thscode, window_start, window_end)` and transition independently through pending/running/success/partial/failed/conflict.

The default admission limit is 60 codes and five years. On resume, successful compatible checkpoints are verified and skipped; only unresolved checkpoints consume budget. Rows with the same key/checksum are idempotent, while checksum/revision differences are retained as conflicts. Running all codes concurrently or restarting the whole batch after one failure was rejected because it exceeds present provider budgets and loses progress.

### 8. Import member facts through a staged file boundary

Dump import receives an operator-selected local file or a transient downloader result, expected checksum, schema identity, capability revision, and date scope. The importer streams Parquet batches, validates canonical security/date keys, rejects duplicates or schema drift, and writes facts transactionally by bounded batch. Presigned URLs are accepted only by the explicit downloader and are redacted before logging or persistence.

Fuyao is the preferred lineage. The existing TDX exact-date facts can fill same-day original facts field by field, never adjusted history, and every mixed result records its source map. Importing dump content directly during a GET or daily dashboard read was rejected because it introduces network and large-file work into the read path.

### 9. Compute breadth as a pure current-day projection

Resolve each tag's Top 10 by `(changePct desc, thscode asc)`, union valid bounded user selections, and calculate each code once. The calculator consumes current membership, same-day member facts, up to 20 adjusted closes, and optional same-day limits facts. It emits numerator/denominator counts and field lineage for every formula in the spec.

Top turnover and Top gain lists use value descending then canonical security ID ascending; medians use the conventional midpoint for even counts. `diffusionRate` is the complement of maximum single-member turnover contribution, so both concentration and spread are explainable from the same denominator. No role labels such as leader/core/follower are inferred.

### 10. Encode task dependencies without coupling failure transactions

The collection registry exposes seven supported public datasets. A run planner creates a DAG where turnover depends on a compatible ranking result and breadth depends on compatible ranking/turnover plus local member facts. Each node keeps its own lease, transaction, status, warnings, and snapshot commit. Blocked dependents are explicit task outcomes; unrelated nodes continue.

This preserves sibling failure isolation while preventing breadth from silently consuming another revision or date. A single three-stage database transaction was rejected because one late failure would roll back valid ranking or turnover facts.

### 11. Make Chapter 01 projection explicit and independently typed

The API model exposes `industryRanking`, `sectorTurnover`, `sectorBreadth`, and `sectorAnalysis`. The projector reads compatible exact-date local snapshots, validates each field independently, and performs CAS replacement after any successful daily dataset commit. New materialization never reads legacy `sectors` as a substitute.

`sectorAnalysis` remains owned by the Shenwan continuity implementation. Keeping it separate in Python and TypeScript types makes accidental THS/QTS mixing a type and test failure rather than a documentation convention.

### 12. Use provider-free GETs and explicit write routes/CLI

Add local queries for catalog search, one-code bars, and operation progress. Add explicit commands/routes for catalog synchronization, turnover backfill, and member-fact import, protected by the existing manual-write switch plus dataset capability, settlement, permission, and budget checks. POST returns an asynchronous run ID; progress GETs only read PostgreSQL.

Suggested HTTP surface:

- `GET /api/market-environment/ths/catalog`
- `GET /api/market-environment/ths/sectors/{thscode}/bars`
- `GET /api/market-environment/ths/operations/{run_id}`
- `POST /api/market-environment/ths/catalog/sync`
- `POST /api/market-environment/ths/turnover/backfills`
- `POST /api/market-environment/ths/member-facts/imports`

Equivalent CLI commands provide local operator workflows. Error responses never echo secrets or raw provider payloads.

### 13. Present four task-focused views on page 05

Use a compact tab control for ranking, breadth, K-line, and Shenwan continuity. Ranking supports tag and code/name search; breadth shows formula evidence and member Top lists; K-line uses one unframed ECharts candlestick view with aligned volume and turnover panels and an explicit backfill action when local coverage is short; continuity renders the existing `sectorAnalysis` view unchanged in meaning.

The data-management page shows three independent task rows/cards and separate operation progress. All visible text remains at least 14px; stable grid dimensions and local horizontal scrolling for genuine tables preserve 390px layouts without page-level overflow.

## Risks / Trade-offs

- [Four catalogs or dump schemas drift] -> Bind parsing to capability revisions, reject unknown required fields/tags, and keep synthetic drift fixtures.
- [Request budget cannot cover all codes] -> Default to at most 60 sorted codes, checkpoint every code/window, and resume only unresolved work.
- [A code changes classifications across revisions] -> Preserve immutable catalog relations and require queries/analysis to declare a revision.
- [Current membership is mistaken for historical membership] -> Reject historical breadth and keep membership `asOf` in every current result.
- [Volume units are not proven] -> Keep volume `null` and downgrade field quality; never derive it from turnover.
- [Mixed Fuyao/TDX facts obscure provenance] -> Store field-level lineage and keep result quality `partial`/`degraded` when fallback contributes.
- [Breaking `sectors` surprises older clients] -> Return a stable unsupported error with three migration targets and synchronize OpenAPI/TypeScript tests.
- [In-flight continuity work is overwritten] -> Add rather than replace its model, repository, page section, and migration; verify both features together.
- [A successful sector-only run still fails materialization] -> Invoke and test the aggregate projector after every successful new-dataset commit.

## Migration Plan

1. Land OpenSpec and fact documentation, then implement typed models, fixtures, and capability policies with no provider or production writes.
2. Add and test the additive PostgreSQL migration after the current migration head; exercise upgrade, rollback, migrate-again, legacy-row retention, and new uniqueness constraints in an isolated database.
3. Add repositories, provider-neutral adapters, calculators, commands, and local queries; keep every new provider switch disabled.
4. Add the three dataset IDs, DAG planning, committers/projectors, Chapter 01 fields, HTTP/CLI contracts, and explicit legacy rejection.
5. Update the data-management and page-05 UIs; run desktop and 390px browser checks against fixture-backed local APIs.
6. Run focused and full offline tests, frontend tests/build, rules gates, OpenSpec strict, and docs-contract full. Record real-operation gaps in the active plan.
7. Under separate authorization and after settlement: run isolated capability probes, review/promote exact revisions, migrate the production database, synchronize a small catalog sample, backfill a small code/date batch, import verified dumps, expand gradually, and deploy with scheduling still disabled/suspended.

Rollback disables new provider switches and public write actions, returns the UI to unavailable/insufficient states, and keeps additive tables plus legacy/new evidence. It does not delete rows, PVCs, capability reports, tasks, or snapshots and does not re-enable the legacy public `sectors` collector.
