## 1. Facts, execution plan, and compatibility baseline

- [x] 1.1 Create `docs/exec-plans/active/add-ai-market-data-api.md`, register it in the active-plan index, record the 174–185 KB aggregate / 64 KB indices / 78–85 KB limits baseline, and verify all required plan fields are present with `python scripts/check-docs-contract.py --mode=fast`.
- [x] 1.2 Update `docs/product-specs/market-environment-dashboard.md`, `docs/architecture.md`, `docs/repository-guide.md`, and `docs/runbooks.md` before code to define the v2 resource tree, provider-free boundary, revision/cursor semantics, discovery documents, legacy compatibility, and rollback; verify each affected code area has a documented mapping.
- [x] 1.3 Add legacy API characterization tests for the unversioned aggregate, core, Chapter 01, next-session and THS paths, including the current cumulative Chapter 01 shape, and verify the tests pass before registering v2 routes.
- [x] 1.4 Add failing v2 contract tests for resource isolation, missing/future dates, closed selectors, list maxima, revision conflicts and zero provider/write calls, and verify they fail only because the new capability is not yet implemented.

## 2. Shared v2 contracts and local read boundary

- [x] 2.1 Define dedicated v2 quality, link, pagination, error and resource-envelope DTOs without reusing `MarketEnvironmentResponse` or `Chapter01Response`, and verify generated OpenAPI contains the typed shared fields and no complete Chapter 01 schema on v2 operations.
- [x] 2.2 Implement the opaque `snapshotRevision` digest, ETag handling, revision precondition and stable 409 response over the existing exact-date component revision, and verify unit tests cover stable hashes, private-metadata exclusion, matching revisions, mismatches and HTTP 304.
- [x] 2.3 Implement opaque cursor encoding/decoding bound to resource, filters, sort key and revision, enforce endpoint default/maximum limits, and verify unit tests reject malformed, cross-resource, changed-filter and stale-revision cursors.
- [x] 2.4 Add typed application read ports/query facade for overview, indices, breadth, limits, sectors, conclusions and operation checkpoints, and verify architecture tests prove the query layer imports neither providers nor HTTP/infrastructure implementations.
- [x] 2.5 Implement PostgreSQL and compatibility/test read adapters that apply filters, stable order and limits before materializing variable-length rows, and verify repository tests prove list queries never perform unbounded fetch-then-slice behavior.
- [x] 2.6 Register an additive `/api/v2/market-environment` router through the existing composition root without mutable module singletons, and verify import/bootstrap/OpenAPI tests pass while all legacy paths remain registered.

## 3. Overview and index resources

- [x] 3.1 Implement `GET /api/v2/market-environment/{as_of}/overview` with compact conclusions, resource availability/quality and links, and verify tests forbid index histories, security rows, sector rows, checkpoints and full Chapter 01 siblings in the response.
- [x] 3.2 Implement exact-date index summary and single-index detail endpoints that omit history arrays, and verify scalar values and quality metadata match the same-revision legacy core evidence.
- [x] 3.3 Implement bounded single-index history with date filters, deterministic date order and revision-bound cursor continuation, and verify multi-page tests return every point once and reject unknown codes and excessive limits.

## 4. Breadth and limits resources

- [x] 4.1 Implement breadth summary and bounded breadth-history endpoints from local exact-date snapshots/history, and verify missing history remains insufficient/null and no provider is invoked.
- [x] 4.2 Implement the limits summary endpoint without security rows or history points and the independent limits rule/risk evidence endpoint, and verify overlapping counts, quality and warnings match the same-revision legacy aggregate.
- [x] 4.3 Implement one limits-pool endpoint for the closed pool-type set with default 20, maximum 100, stable security identity tie-breaking and cursor pagination, and verify repository/API tests cover empty, partial, retained and multi-page pools.
- [x] 4.4 Implement bounded limits history with default 60, maximum 250 and exact-date quality semantics, and verify it never substitutes natural days or older snapshots for missing trading sessions.

## 5. Sector, conclusion, and operation resources

- [x] 5.1 Implement isolated sector ranking, turnover, breadth and continuity-analysis endpoints using normalized THS/canonical repositories and bounded ranking/observation rows, and verify each response excludes all unrelated sector and Chapter 01 siblings.
- [x] 5.2 Implement isolated active-direction, events and assessment endpoints with typed DTOs and documented list bounds, and verify missing/unverified data stays null or insufficient rather than becoming an empty success.
- [x] 5.3 Split v2 operation polling into summary and checkpoint endpoints, paginate checkpoints with default 50 and maximum 200, and verify summary responses never contain checkpoint rows while progress counts remain unchanged.
- [x] 5.4 Link existing THS catalog and sector-bars resources from the v2 sector responses without duplicating their contracts, and verify links retain exact revision/code/date context where applicable.

## 6. AI discovery documents

- [x] 6.1 Implement a pure in-memory renderer for `/llms.txt` and `/llms-full.txt` from tagged OpenAPI operations plus curated product/runbook semantics, and verify rendering performs no filesystem write, database query or provider call.
- [x] 6.2 Expose both documents as UTF-8 `text/plain`, include overview-first examples, exact-date/quality/pagination guidance and OpenAPI links, and verify secret-pattern tests reject credentials, provider headers, presigned URLs and embedded live market rows.
- [x] 6.3 Add deterministic discovery/OpenAPI drift tests for operation ids, paths, parameters, response models and documented limits, and verify a deliberately altered fixture produces a failing contract check.

## 7. Dashboard migration and client bounds

- [x] 7.1 Add typed frontend v2 envelope, revision, cursor and error handling plus API helpers, and verify Vitest covers 304, 404, 409 restart and multi-page continuation behavior.
- [x] 7.2 Migrate the index/overview and breadth pages to the corresponding v2 resources while retaining the legacy fallback path, and verify route-loading tests show no unrelated chapter request or history payload.
- [x] 7.3 Migrate limits pages to summary/evidence plus server-side pool pagination, and verify page navigation/search does not preload all four security pools.
- [x] 7.4 Migrate sector, active-direction, events and assessment pages incrementally, and verify direct navigation to pages 07 and 09 no longer depends on previously visiting a summary page.
- [x] 7.5 Reduce the THS sector-bars request page size from 1500 to the server maximum of 1000 and implement continuation when needed, and verify the request no longer receives 422 and all bars render once.
- [x] 7.6 Run desktop and 390px browser checks for migrated loading, pagination, error and empty states, and verify visible text remains at least 14px with no page-level horizontal overflow.

## 8. Integration verification and handoff

- [x] 8.1 Run focused backend tests for v2 queries, repositories, schemas, routes, OpenAPI, discovery and legacy compatibility; record the exact command and passing counts in the active plan.
- [x] 8.2 Run `python -m pytest tests -q`, frontend `npm run test` and `npm run build`; record failures or passing evidence without invoking real providers, production endpoints or deployment writes.
- [x] 8.3 Run `python -m src.trading_system.cli rules validate`, `rules coverage`, `docs sync-check`, `openspec validate add-ai-market-data-api --strict`, `python scripts/check-docs-contract.py --mode=full`, and `git diff --check`, and record every result.
- [x] 8.4 Update the active plan `Status`, `Completion Evidence`, `Remaining Gaps` and `Next Step`, including any intentionally retained legacy payload or deferred MCP/authentication work, and verify the plan remains indexed and the full docs contract passes.
