## Context

See `proposal.md` for motivation. The runtime path currently derives the public core payload date from the latest effective date found in index histories, but can independently stamp the normalized candidate actual date as the requested date. The PostgreSQL snapshot repository has a legacy core exception that accepts this disagreement, while materialized aggregate and v2 readers enforce stricter key-to-payload equality. This split permits an invalid row to be committed and detected only after the dashboard reads it.

The fix crosses provider normalization, typed collection outcomes, snapshot persistence, aggregate materialization, HTTP error mapping, dashboard fallback behavior, tests, and operational guidance. Ordinary GET must remain provider-free and read-only; production data correction, collection, deployment, PostgreSQL writes, and PVC operations remain outside implementation authorization.

## Goals / Non-Goals

**Goals:**

- Establish one exact-date invariant from per-index evidence through public API responses.
- Preserve valid partial core results and same-date failure retention without admitting another date.
- Reject invalid writes before any snapshot revision or materialized aggregate is advanced.
- Convert stored integrity failures into stable, non-sensitive HTTP behavior distinct from normal absence.
- Provide a safe audit and separately authorized repair procedure for existing mismatched rows.

**Non-Goals:**

- Automatically relabel, migrate, delete, or overwrite existing production records.
- Trigger provider collection, deployment, or database repair from a GET request.
- Change provider priority, market-date selection, scheduling, database schema, or public successful-response fields.
- Require every historical point in an index series to equal the selected date; only the latest effective observation used as current evidence is constrained.

## Decisions

### 1. Validate each core index before constructing the dataset candidate

Each normalized index result will expose a latest effective observation date derived from its validated history. A result counts as a current success only when that date equals the requested dataset date. Earlier results become structured date-mismatch failures carrying requested and actual dates; they are excluded unless an independently validated snapshot for the same selected date can be retained.

If at least one exact-date index remains, the existing partial-core contract applies. If none remains, acquisition returns `failed-retained` only when a valid same-date core snapshot exists; otherwise it returns `failed-missing` with no candidate to commit.

Alternative considered: keep the candidate and mark it `insufficient`. Rejected because status metadata cannot make a cross-date payload safe to persist under an exact-date key.

### 2. Make normalized date evidence internally consistent

For an accepted core candidate, identity date, candidate actual date, payload `asOf`, quality `asOf`, quality `effectiveAsOf`, and every included index's latest observation date will agree. The effective date will no longer be computed as the minimum of mixed current and prior-date results after those results have already been accepted.

Alternative considered: change the candidate identity to the provider's earlier date. Rejected because the request and task belong to the selected date, and silently redirecting their write would violate task identity, lease, idempotency, and audit semantics.

### 3. Enforce strict write validation at every durable boundary

The snapshot write path will use a shared exact-date validator and will not apply the legacy core effective-date exception to new writes. The core committer will validate the candidate before any fenced transaction records successful snapshot evidence. Both the current runtime compatibility `SnapshotStore` and the typed PostgreSQL snapshot repository must enforce the same rule. The actual runtime compatibility aggregate writer and the typed PostgreSQL materialized-aggregate replace/CAS path will validate their key, public `asOf`, source core snapshot identity, core effective-date evidence, and included component actual dates before atomic replacement.

Read compatibility for legacy rows will be separated from write authorization. Normal reads may identify a legacy mismatch for diagnostics but will not serve it as evidence. Raw inspection needed by an operator audit stays behind an explicit maintenance path rather than weakening repositories used by ordinary queries.

Alternative considered: rely only on the aggregate repository's current read-time check. Rejected because it detects corruption after a successful task has already published invalid durable state.

### 4. Preserve same-date evidence atomically on failure

A date-mismatch attempt follows existing failure-retention rules. A valid snapshot and aggregate for the same dataset/date remain unchanged and the task records `failed-retained`; evidence from any other date does not qualify and produces `failed-missing`. Successful sibling datasets and their materializations remain independent.

For a partial core write, only exact-date or same-date retained index results enter the candidate. Missing indices remain explicit and do not lower the payload date.

Alternative considered: delete an invalid or stale row during collection. Rejected because collection failure must not perform implicit destructive repair or erase audit evidence.

### 5. Map repository integrity failures to a stable 503 contract

The shared HTTP error mapper will recognize snapshot/materialization integrity exceptions and return HTTP 503 with code `snapshot_integrity_error` and a safe message tied only to the requested resource/date. It will not expose SQL, checksums, filesystem paths, provider payloads, or stack traces. A truly absent date continues to use existing 404 or missing/insufficient semantics.

The dashboard will preserve legacy fallback for ordinary v2 absence or compatibility failures, but an explicit v2 integrity error will be surfaced as a data-integrity failure instead of being hidden behind a second read of the same invalid aggregate.

Alternative considered: map the error to 404. Rejected because a corrupt local row is operationally different from no evidence and needs an actionable repair signal.

### 6. Audit first; repair existing rows only through a separately authorized operation

The runbook will define a provider-free, read-only audit that compares snapshot/aggregate key dates with payload, quality, actual-date, and effective-date evidence. It will bind findings to exact table keys, checksums/revisions, application image, and a PostgreSQL backup reference without printing credentials or complete market payloads.

Any production repair requires a separate active plan and explicit authorization. It must freeze writers, back up PostgreSQL, resolve exact targets, avoid overwriting an existing successful destination date, and choose either removal/quarantine followed by a valid same-date recollection or an already-supported audited relabel flow only when the source evidence truly belongs to the target. This change does not execute either option.

## Risks / Trade-offs

- [Upstream providers remain one session behind after settlement] -> The selected date remains `failed-missing` or `failed-retained`; this is preferable to publishing false evidence, and diagnostics retain requested/actual dates.
- [Stricter writes expose previously tolerated fixtures or migration inputs] -> Separate legacy import/audit compatibility from normal runtime writes and update fixtures to declare real date evidence.
- [Partial core payloads exercise assumptions that five indices always exist] -> Add end-to-end partial-core contract tests across composition, schema validation, v2 summaries, and dashboard rendering.
- [503 responses increase visible errors until stored corruption is repaired] -> Provide a stable code, preserve prior valid same-date evidence, and document an audited repair path; never auto-heal through GET.
- [Duplicated validation drifts across layers] -> Centralize pure date-invariant evaluation and test acquisition, snapshot write, aggregate replacement, and read mapping against a shared scenario matrix.

## Migration Plan

1. Add failing deterministic tests for prior-session provider evidence, mixed partial results, same-date retention, strict snapshot writes, aggregate replacement, and v2/legacy error mapping.
2. Implement the normalized exact-date policy and strict write/materialization guards without a database schema migration.
3. Update dashboard handling, architecture/product/runbook/repository documentation, and the active execution plan; run backend/frontend and docs gates.
4. Build and deploy only through a separately approved release plan. Post-deploy smoke must check `/api/health`, one valid historical overview, and the effective-date overview/core behavior without triggering providers.
5. Run the documented read-only integrity audit. If invalid production rows remain, stop and obtain separate authorization for backup, writer freeze, exact-target repair, and optional recollection.

Rollback uses a reviewed immutable application image and preserves PostgreSQL, run/task history, snapshots, aggregates, Secrets, and PVCs. Rolling back to code that admits cross-date writes is not a data repair; collection writers must remain disabled or otherwise guarded until a safe version is restored.
