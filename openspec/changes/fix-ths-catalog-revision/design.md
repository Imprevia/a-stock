## Context

See `proposal.md` for the incident motivation. The implemented THS path currently passes `MARKET_ENVIRONMENT_FUYAO_THS_CATALOG_REVISION` through the capability gate and also uses it as `ThsCatalogRevision.revision_id`. During normalization it then removes any code whose six OHLC/volume/turnover fields are all null, removes its catalog relations, recomputes tag counts, and calculates the checksum from that daily-trimmed relation set. The PostgreSQL repository correctly rejects a second checksum under the same immutable revision ID.

The active `add-fuyao-ths-sector-datasets` change introduced the affected models and behavior but is not yet archived. This repair depends on that implementation and supersedes only its design decision that catalog identity can be keyed by provider/capability/checksum/fetch context. Its other decisions—four classifications, shared code facts, normalized PostgreSQL storage, exact-date snapshots, dependency ordering, provider-free GETs, and THS/Shenwan separation—remain in force.

PostgreSQL schema version 9 already has separate `revision_id` and `capability_revision` columns, `TEXT` foreign keys, nullable ranking `change_pct`, row quality/warnings, nullable bar fields, and a constraint that rejects an entirely null bar. Those structures support the data model, but `ths_catalog_revisions` also has a redundant `UNIQUE (provider, capability_revision, checksum, fetched_at)` constraint. Because that tuple omits the Shanghai trading date, two valid date-addressed observations can collide when a fixed clock or replay/import uses the same fetch timestamp. One narrow DDL migration is therefore required. Collection tasks have a nullable `warning TEXT` but no diagnostics JSON column, so typed attempt diagnostics remain compatibly encoded rather than adding a diagnostics column.

## Goals / Non-Goals

**Goals:**

- Make catalog observation identity deterministic and independent from daily rank/bar availability.
- Preserve exact-date lineage and idempotent same-day retries while removing only the redundant non-date uniqueness constraint.
- Retain every complete catalog/ranking relation while persisting bars only for proven OHLC/volume/turnover facts.
- Let compatible partial evidence proceed through the THS DAG with explicit coverage and row-level quality.
- Prevent implicit reads from merging multiple revisions for one date.
- Make task failures and dependency blocks understandable through stable, bounded diagnostics while keeping old records readable.

**Non-Goals:**

- No pure cross-date content-addressed catalog normalization or new catalog-observation table in this repair.
- No table rebuild, new data column, data rewrite, or broad schema redesign beyond dropping the redundant uniqueness constraint.
- No rewrite, deletion, renaming, or status alteration of existing catalog data or collection audit records.
- No relaxation of identity, duplicate, date, timestamp, or catalog-contract validation.
- No zero filling, fabricated bars, shorter Top-N presentation, historical breadth, or THS-to-Shenwan identity mapping.
- No real provider probe, capability promotion, production database write, deployment, recollection, or schedule mutation without a later explicit authorization.

## Decisions

### 1. Use a date-and-content-addressed catalog observation ID

Keep these identities separate:

- `capabilityRevision`: the fixed approved provider endpoint/schema/permission/budget contract, initially still `fuyao-ths-catalog-v1`.
- `catalogChecksum`: SHA-256 over canonical, sorted complete relations `(tag, thscode, normalized display name)` for all four tags.
- `catalogRevisionId`: an opaque deterministic value with versioned semantics, for example `fuyao:<capabilityRevision>:<YYYY-MM-DD>:sha256:<full-64-character-checksum>`.

Create one shared helper that validates its inputs and derives the ID. The Shanghai trading date and full checksum participate in identity; provider/fetch timestamps do not. Therefore same-day identical retries are idempotent, same-day content changes coexist, and identical content on another day still receives a distinct observation ID with correct daily lineage.

Pure `provider + capability + checksum` content addressing was rejected for this repair because the current revision envelope owns provider/fetch timestamps and ranking observations copy that lineage. Reusing one revision across dates would retain the first observation time and make “latest” semantics incorrect unless a new catalog-observation table or independent ranking timestamps were introduced. The fixed capability revision as primary key was rejected because it causes the production collision. Mutable/SCD replacement was rejected because it breaks immutable history and would require wider migration.

### 2. Normalize the complete catalog before examining daily values

The adapter sequence becomes:

1. Parse exactly the four catalog responses into revision-neutral normalized relations.
2. Validate tags, codes, names, duplicates, cross-tag name consistency, timestamps, and non-empty counts.
3. Calculate tag counts and checksum from all relations, derive `catalogRevisionId`, then stamp every relation with it.
4. Parse snapshot batches and validate that the response identity set exactly equals the unique catalog code set, with no duplicates or extra codes and with a provable exact Shanghai date.
5. Classify field availability without changing catalog membership.

The response row has two independent usability dimensions:

- `missingLiveCodes`: every OHLC/volume/turnover field is null, so no `ThsSectorBar` can be created. A non-null `changePct` may still make this row rankable.
- `missingRankingCodes`: `changePct` is null, so the row cannot participate in Top-N ranking. Valid bar fields, if present, remain usable.

A row with all seven values null belongs to both sets. Do not weaken `ThsSectorBar` or the existing database constraint to admit an all-null bar. Represent response observations separately from durable bars, and build a complete ranking row directly from the relation plus optional normalized values. Missing identity is not equivalent to a present row with null values and remains a hard rejection.

### 3. Carry row quality through the complete ranking

Extend `ThsRankingRow` with `quality` and `warnings`, defaulting to `ok` and empty for compatibility. The ranking builder accepts complete relations, all validated response observations, and the two declared gap sets. It emits one row per catalog relation:

- rows with a proven `changePct` sort first by `changePct DESC, thscode ASC`;
- rows with null `changePct` sort last by `thscode ASC`, have `quality=insufficient`, and retain nullable volume/turnover;
- a shared code creates a ranking row for each tag but at most one daily bar.

The existing `quality_status` and `warnings_json` ranking columns are used for round trips instead of the repository hard-coding `ok`/empty values. Dataset diagnostics report relation count, unique catalog code count, snapshot identity count, rankable count, bar count, `missingLiveCodes`, and `missingRankingCodes` separately.

### 4. Change atomic commit invariants without weakening integrity

Keep catalog, ranking, bar, and dataset snapshot writes in one unit of work. Replace the invalid assumption that every catalog code must have a bar with these checks:

- ranking keys exactly equal catalog relation keys;
- bar codes and `missingLiveCodes` are each unique subsets of catalog unique codes;
- bar codes and `missingLiveCodes` are disjoint and their union equals catalog unique codes;
- `missingRankingCodes` exactly match rows whose `changePct` is null;
- all rows and diagnostics use the requested date and same catalog observation revision;
- unknown, duplicate, contradictory, or undeclared gaps reject and roll back the entire commit.

The bar repository continues to use its current immutable source-revision key and rejects conflicting same-key values. No null placeholder bar or zero is inserted.

The catalog repository keeps `(revision_id, provider)` as its immutable identity and conflict boundary. Advance PostgreSQL to schema version 10 / Alembic `0007_ths_catalog_identity` and drop only `UNIQUE (provider, capability_revision, checksum, fetched_at)`. The revision ID remains within Alembic's default 32-character `version_num` column; widening that column was rejected because it would add unrelated DDL. That secondary tuple is not an observation identity because it omits the trading date. The migration performs no row update, delete, rename, or timestamp/checksum rewrite; legacy fixed revisions and all dependent facts remain intact. Downgrade is deliberately non-destructive and does not recreate a constraint that could reject rows valid under the new identity contract.

### 5. Resolve one exact catalog revision for every dependent read

The ranking dataset snapshot carries `catalogRevisionId`. A dependent task in the same run consumes that exact revision. A targeted retry may reuse a local prerequisite only when its exact date, accepted state, and revision are compatible.

Repository APIs gain an explicit revision filter and a deterministic “latest compatible revision for date” query. An implicit exact-date query selects a single revision ordered by `provider_timestamp DESC`, `fetched_at DESC`, then `revision_id DESC`; it never returns a union of every same-date revision. Explicit revision queries keep historical access. Turnover and breadth propagate the selected revision in quality/lineage and reject mismatches before calculation.

### 6. Treat declared live-value gaps as partial dependencies

The coordinator retains its existing task DAG. An accepted `industry-ranking` candidate with complete identity coverage and declared value gaps finishes as `partial`, which is already a successful prerequisite state. The dependent collectors then apply capability-specific predicates:

- turnover publishes proven bars and reports bar coverage and `missingLiveCodes` as partial;
- breadth filters out rows with null `changePct` or non-rankable quality before Top-N selection;
- breadth proceeds only if each tag has at least the configured Top-N valid candidates, otherwise it produces `insufficient` with per-tag counts;
- missing/duplicate/wrong-date identities, absence of an accepted prerequisite, and date/revision mismatches remain blocked or insufficient.

This avoids changing sibling-failure isolation. Treating every partial as blindly compatible was rejected because an identity/date failure is materially different from a declared nullable field gap.

### 7. Add typed diagnostics without a new diagnostics column

Accepted snapshots store typed coverage in their existing quality `extra`/warnings payloads. Collection task failures and blocks need persistence even though `collection_tasks` has only `warning TEXT`. Define a versioned canonical warning envelope:

```text
THS_DIAGNOSTIC_V1 {"reasonCode":"...","message":"...","failureStage":"...",...}
```

The envelope includes only bounded fields: reason code, safe message, exact date, capability/catalog revisions when known, expected/observed/rankable/bar counts, total missing counts, deterministic bounded code samples, retryability, and a bounded `blockedBy` summary. The status API detects and validates this prefix, returns `message` as the existing warning, and exposes a new optional typed diagnostics object. Legacy text remains unchanged with diagnostics absent. Malformed envelopes fall back to ordinary text. No raw payload, credential, signed URL, or sensitive header enters the envelope.

Stable initial codes are:

- `THS_LIVE_VALUES_MISSING`
- `THS_DAILY_SNAPSHOT_INSUFFICIENT`
- `THS_CATALOG_REVISION_COLLISION`
- `THS_DEPENDENCY_INSUFFICIENT`
- `THS_DEPENDENCY_REVISION_MISMATCH`

A new JSONB task column remains rejected because the required catalog-identity migration does not justify expanding the task schema. Free-form-only strings were rejected because clients cannot reliably distinguish failure classes.

### 8. Preserve old evidence and avoid a capability re-certification dependency

Do not update or rename the legacy `fuyao-ths-catalog-v1` catalog row, its relations, 2026-10-13 facts, or the 2026-10-14 failed/blocked attempts. New collection creates a new observation revision and attempt. Existing fixed-revision reads remain supported when explicitly requested.

The repair keeps the approved capability revision because endpoint, permission, schema, and request budget do not change. A later separately authorized probe may promote a new capability revision whose evidence distinguishes raw catalog relations, snapshot identity coverage, rankable coverage, bar coverage, and both missing sets, but production recovery does not depend on that promotion.

### 9. Present partial evidence explicitly in API and UI

Add optional THS diagnostics and row quality fields to Python/OpenAPI/TypeScript models. Keep catalog revision an opaque string and use one consistent public field name. The data-collection page displays usable/expected counts, bounded missing codes, reason code, and upstream dependency details. The sector page labels incomplete results as “部分排名” or “当日行情缺失”, keeps unavailable numbers null, and prevents unrankable rows from being offered as breadth Top-N inputs.

All added response fields are optional so old persisted attempts and clients remain valid. Visible text stays at least 14px, details can expand, and the 390px layout must not gain page-level horizontal overflow.

### 10. Freeze writers and bind the production image through dedicated controls

The production rollout must not reuse a generic Helm mutation to disable manual collection. Add a dedicated same-image, hook-free `--disable-manual-refresh` entry that accepts one reviewed full values packet and proves its exact diff from the stored release changes only `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` from literal `"1"` to `"0"`. It requires both application CronJobs absent and every retained namespace Job to have a terminal `Complete=True` or `Failed=True` condition, so completed/failed audit Jobs remain while queued, pending, retrying, or active Jobs fail closed. It preserves the image, stored Helm hooks, PVC/Secret identities and every other resource field, rejects terminating managed resources, and compares all managed live resources in the full packet—including PostgreSQL StatefulSet and PVC—before the write so database drift cannot be silently reconciled. It performs no image build/import or migration hook and verifies the replacement Ready Pod is still on the frozen image with manual refresh disabled. A postcondition failure leaves the safe manual-off state under investigation; it must not automatically restore writes.

Generic `all` and `service` deployments used for the candidate must fail before any target access unless the worktree is clean and a full `REVIEWED_GIT_HEAD` equals local HEAD. After import they resolve and freeze the exact containerd manifest digest, verify it again immediately before Helm writes, and after rollout prove the Deployment→ReplicaSet→Ready Pod chain references the same repository/tag and runtime image digest. Archive checksum, reviewed HEAD and manifest digest become rollout evidence; a tag-only match is insufficient.

## Risks / Trade-offs

- [A daily observation repeats roughly 846 catalog relations] → Accept roughly 200,000 additional relation rows per trading year; this is small enough for the current PostgreSQL design and preserves correct time lineage without a risky migration.
- [A provider changes catalog content twice on one date] → Preserve both immutable revisions and deterministically select one latest observation; never merge their relations.
- [Dropping a legacy uniqueness constraint changes the database contract] → Remove only the tuple that omits trading date, retain `(revision_id, provider)` uniqueness, add migration/schema/runtime regression coverage, and prove legacy rows remain unchanged in an isolated database before production rollout.
- [A warning envelope is malformed or produced by an older binary] → Parse defensively and fall back to the original warning text with diagnostics absent.
- [A code has `changePct` but no bar fields, or the inverse] → Track ranking and bar gaps independently and test all field-availability combinations.
- [Partial is mistaken for complete] → Persist row/dataset quality, `complete=false` semantics, counts, missing sets, and UI labels; Top-N selection filters on rankability.
- [Rollback binary still contains the fixed-revision bug] → Keep collection writes and scheduling disabled after application rollback until the repaired binary is restored; retain additive database evidence.
- [Parallel OpenSpec changes overlap] → Archive/apply this change only with `add-fuyao-ths-sector-datasets` context present, and let this design supersede only its catalog-identity decision rather than duplicating or rewriting the rest of that capability.

## Migration Plan

1. Before code changes, update the active execution plan and affected architecture, product, runbook, repository-guide, and status facts to record the repair scope, no-DDL decision, acceptance criteria, and separately authorized production work.
2. Implement the domain/adapter/repository/collector/API/UI changes against fixed fixtures. Add Alembic `0007_ths_catalog_identity`, keep its revision ID within the default 32-character version column, advance the runtime minimum to schema version 10, and remove only the redundant `UNIQUE (provider, capability_revision, checksum, fetched_at)` definition from fresh-schema DDL.
3. Run focused domain, adapter, PostgreSQL, committer, DAG, materialization, API, and UI tests; then run the full backend suite, frontend tests/build, strict OpenSpec validation, and full docs-contract gate.
4. Under separate production authorization, freeze a read-only baseline; use the controlled deployment workflow to suspend/disable the exact scheduled collector and the dedicated same-image/hook-free entry to disable manual collection; record release/image, PVC/Secret, schema, capability, legacy revision, relation, ranking, and failed-attempt evidence.
5. Create an immutable PostgreSQL backup, record size/checksum/PVC identity, restore it into isolated PostgreSQL 16, apply `0007`, and prove schema version 10, absence of only the redundant constraint, cross-date observation coexistence, and unchanged legacy evidence.
6. From a clean worktree bound to a reviewed full Git SHA, deploy one immutable image with scheduling and manual collection off. Freeze and verify the imported containerd manifest digest before the Helm write and through the Ready runtime Pod. Verify health, provider-free GETs, schema version, PVC/Secret identity, capability reports, legacy counts, and old success/failure audit records before allowing any provider call.
7. After the Shanghai settlement boundary and with separate provider-write authorization, run one targeted dependency-aware collection for `industry-ranking`, `sector-turnover`, and `sector-breadth`. Verify the new observation ID differs from the capability revision, complete relation/ranking counts reconcile, bars plus `missingLiveCodes` reconcile, no zero placeholders exist, and neither downstream task is generically blocked by a declared value gap.
8. Restore the reviewed schedule only through the controlled runbook and explicit authorization. Observe at least two completed Shanghai trading dates to prove same-day retry idempotency and cross-date lineage before closing the production phase.

Rollback first disables scheduled and manual writes, then redeploys the recorded previous application image through the normal release path. It does not delete new revisions or restore the database by default because the new evidence is additive and auditable. Database restore is reserved for proven structural corruption after all writers stop; it is not a cleanup mechanism for a failed collection.
