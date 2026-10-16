## Context

See [proposal.md](proposal.md) for motivation. The current runtime already separates HTTP, application query, domain and persistence layers, and ordinary GETs are required to remain provider-free and exact-date. However, `GetChapter01Query` validates `section` and then returns the complete materialized Chapter 01, while `Chapter01Response` requires every sibling field. Stored aggregate samples are roughly 174–185 KB; index histories contribute about 64 KB and limits about 78–85 KB. Limits security rows and THS operation checkpoints are returned as whole lists, while only THS catalog and sector bars currently have server-side pagination.

The production store is PostgreSQL, existing exact-date snapshots and materialized aggregates are authoritative, and the repository has no application authentication for ordinary reads. Existing API consumers and the dashboard must remain compatible. Repository rules also require facts and architecture documents to be updated before implementation code and prohibit GET-triggered provider activity.

## Goals / Non-Goals

**Goals:**

- Provide an additive, versioned read surface optimized for incremental AI tool use.
- Make response shape and list bounds enforceable by dedicated DTOs rather than full-schema placeholders.
- Let one client session detect or prevent mixing different same-date materialization revisions.
- Reuse exact-date local repositories and existing quality semantics without creating another market-data truth source.
- Keep discovery documents mechanically aligned with OpenAPI.

**Non-Goals:**

- Removing or changing existing unversioned endpoints in this change.
- Adding provider calls, collection triggers, write tools, authentication, arbitrary field projection, GraphQL, or SQL access.
- Expanding the local trading-knowledge MCP into a market-data service.
- Changing provider priority, acquisition plans, database facts, scheduling, deployment topology, or production state.
- Returning bulk historical dumps; existing explicitly bounded THS bar reads remain the large-series path.

## Decisions

### 1. Add a versioned resource tree and keep legacy routes unchanged

The new root will be `/api/v2/market-environment`. Exact market date remains explicit in data paths:

| Resource | Path |
|---|---|
| Overview | `/{as_of}/overview` |
| Index summaries | `/{as_of}/indices` |
| One index | `/{as_of}/indices/{code}` |
| One index history | `/{as_of}/indices/{code}/history` |
| Breadth summary/history | `/{as_of}/breadth`, `/{as_of}/breadth/history` |
| Limits summary/pools/history/evidence | `/{as_of}/limits`, `/{as_of}/limits/pools/{pool_type}`, `/{as_of}/limits/history`, `/{as_of}/limits/evidence` |
| Sector observations and analysis | `/{as_of}/sectors/rankings`, `/{as_of}/sectors/turnover`, `/{as_of}/sectors/breadth`, `/{as_of}/sectors/analysis` |
| Other conclusions | `/{as_of}/active-direction`, `/{as_of}/events`, `/{as_of}/assessment` |
| Operation summary/checkpoints | `/operations/{run_id}`, `/operations/{run_id}/checkpoints` |

Existing THS catalog and single-code bars remain available at their current paths and are linked from overview/sector resources rather than duplicated immediately. Existing unversioned routes remain registered and can be marked deprecated only in OpenAPI metadata.

Alternative considered: change `/chapter-01?section=` in place. Rejected because the existing response DTO and frontend merging behavior depend on a complete cumulative Chapter 01 object, so an in-place sparse response would be breaking.

### 2. Use dedicated resource DTOs and a common typed envelope

Each endpoint gets a resource-specific `data` model. The common envelope contains:

- `asOf`
- `generatedAt`
- `snapshotRevision`
- `quality`
- `data`
- `links`
- `pagination` for collections only

Index summary DTOs omit `history`; an index history point DTO is used only by the history route. Limits summary omits `securityDetails.rows` and historical points. Operation summary omits checkpoints. Sector routes expose only their named observation or analysis.

Alternative considered: reuse `MarketEnvironmentResponse`/`Chapter01Response` with `response_model_exclude`. Rejected because those models require the full nested shape, defaults can reintroduce placeholders, OpenAPI would still advertise the wrong contract, and accidental sibling leakage would remain easy.

### 3. Introduce a resource-oriented application read port

A versioned query facade will depend on typed local read ports rather than on HTTP models or providers. The port will expose overview projection, index summary/detail/history, breadth summary/history, limits summary/pools/history/evidence, sector resources, active direction, events, assessment and operation summary/checkpoints.

Implementations will use the smallest existing local fact source:

- core snapshot for index data;
- breadth snapshot/history repository for breadth;
- limits fact/detail/history repositories for pool and evidence reads;
- normalized THS and sector-continuity repositories for sector resources;
- operation repository for summary/checkpoint reads;
- materialized aggregate projection only for cross-dataset conclusions that are not available as an independent fact.

PostgreSQL list queries must apply bounds and stable ordering before materializing rows. Compatibility/test adapters may project in memory from fixtures, but production must not load an unbounded list and slice it afterward. No new persistence schema is expected; if implementation proves a schema/index change necessary, the proposal and tasks must be revised before adding it.

Alternative considered: load the entire materialized JSON for every route and remove fields at serialization. This would reduce network payload but preserve unnecessary database deserialization and make list pagination artificial, so it is allowed only as a temporary test adapter, not the production list implementation.

### 4. Bind all resources to an opaque materialization revision

The existing materialization component revision is the consistency authority. The public `snapshotRevision` will be an opaque stable digest of the exact-date component revision vector; private component details remain hidden. Resource queries verify that their selected local candidate still matches the vector before returning.

Overview returns the current revision. Follow-up endpoints accept an optional revision precondition. A mismatch returns HTTP 409 with a stable error code and the current revision. The same value is emitted as an ETag; `If-None-Match` can return 304. This prevents a multi-call AI workflow from silently combining pre- and post-rebuild evidence.

Alternative considered: expose `_componentRevision` directly. Rejected because it is currently private storage metadata and would permanently couple clients to internal dataset/checksum structure.

### 5. Use opaque cursor pagination with endpoint-specific hard limits

New variable-length collections use `limit` plus an opaque `cursor`. The cursor encodes the resource identity, exact date or run id, snapshot revision, active filters, and last stable sort key. It is validated before repository access. Cursors are not authorization tokens and contain no credentials.

Initial boundaries:

| Collection | Default | Maximum |
|---|---:|---:|
| Limits security pool | 20 | 100 |
| Sector rankings/observations | 20 | 100 |
| Active direction | 20 | 100 |
| Index/breadth/limits history | 60 | 250 |
| Operation checkpoints | 50 | 200 |

Sorting uses domain keys plus an identity tie-breaker: history by date, pools by documented pool order then security identity, rankings by rank/change ordering then `thscode`, and checkpoints by code/window. Existing THS page/page_size endpoints keep their current contract.

Alternative considered: add generic `fields`/`include` and offset pagination. Rejected because arbitrary projections enlarge the test/security surface, while offset pages can drift when the same-date materialization changes.

### 6. Preserve HTTP and missing-data semantics

Invalid dates, future dates and closed-selector violations return 422. An entirely unknown local date returns 404 with a stable code. A known exact date whose selected dataset is missing returns a successful typed envelope with `quality.status=missing|insufficient` and null or empty bounded data, preserving the project's evidence semantics. Revision mismatch returns 409. No path searches another date.

### 7. Generate discovery output from the canonical contract without runtime writes

`/openapi.json` remains the structural machine contract. A pure renderer combines tagged OpenAPI operations with curated semantic guidance from the repository product/runbook documentation to produce `/llms.txt` and `/llms-full.txt` in memory. It does not write generated files at runtime. Contract tests verify documented operation ids, paths, parameters and models against OpenAPI and assert that discovery output contains no secret-like values or live response rows.

Alternative considered: maintain independent hand-written public text files. Rejected because route and parameter drift would create a second API truth source.

### 8. Migrate dashboard consumers incrementally

The dashboard store gains versioned API helpers and migrates page by page. Each page requests only its required resource; limits tables use server-side pool pagination rather than downloading every row. The existing legacy calls remain as a rollback path during migration. The existing THS sector-bars client must request at most the server's documented `page_size=1000` instead of 1500.

## Risks / Trade-offs

- [Many endpoints increase public surface area] → Keep a closed resource set, shared envelope/errors, generated OpenAPI checks and one router namespace.
- [Same-date rebuild occurs between calls] → Require opaque revision/ETag on every response and support revision preconditions and revision-bound cursors.
- [Some conclusions currently exist only inside the full aggregate] → Add narrow projection methods and verify component revisions; do not duplicate calculation logic in the HTTP layer.
- [Legacy and v2 results diverge] → Build both from the same local facts and add parity tests for overlapping scalar values and quality metadata.
- [Pagination changes dashboard behavior] → Migrate one page at a time, retain legacy routes, and test empty/partial/multi-page states.
- [Discovery documentation drifts] → Render from OpenAPI plus curated semantic sections and make drift a deterministic test failure.
- [Response-size regression returns] → Add shape tests that forbid sibling fields and assert hard row bounds rather than relying only on sample byte sizes.

## Migration Plan

1. Create/update the active execution plan and amend product, architecture, repository and runbook facts before code changes.
2. Add characterization tests for current legacy routes and measured large-response shapes; these protect compatibility rather than canonizing the over-fetching behavior for v2.
3. Add the resource read port, revision model, pagination cursor, dedicated DTOs and versioned router behind additive route registration.
4. Implement overview and index resources first, followed by breadth, limits, sectors/analysis, other conclusions and operation checkpoint pagination.
5. Add discovery rendering and OpenAPI drift/security checks.
6. Migrate dashboard pages incrementally and correct the THS bars page-size mismatch.
7. Run focused backend/frontend tests, full offline suites, OpenSpec validation and docs-contract full before declaring the plan complete.

Rollback removes the v2 router and discovery route registration or returns the dashboard to legacy callers. Because this design adds no database migration and does not mutate existing facts, rollback leaves PostgreSQL, snapshots, aggregates, collection state and legacy API behavior intact.
