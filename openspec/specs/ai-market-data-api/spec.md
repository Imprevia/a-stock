# ai-market-data-api Specification

## Purpose

为 AI Agent 和自动化研究客户端提供可发现、精确日期、只读且有界的市场环境 API，使客户端能够先读取紧凑概览，再按需获取单一资源，同时完整保留来源、质量和版本一致性语义。

## Requirements

### Requirement: AI-readable API discovery
The system SHALL expose UTF-8 plain-text `/llms.txt` and `/llms-full.txt` discovery documents that describe the supported read-only market-data resources, parameters, response envelopes, quality states, pagination, examples, and links to the canonical OpenAPI document.

#### Scenario: Agent discovers available resources
- **WHEN** an AI client requests `/llms.txt`
- **THEN** it receives a compact index of the versioned market-environment read resources and a link to `/llms-full.txt` and `/openapi.json`

#### Scenario: Agent reads the full integration guide
- **WHEN** an AI client requests `/llms-full.txt`
- **THEN** it receives endpoint contracts and examples without embedded live market rows, credentials, provider headers, presigned URLs, or private runtime values

#### Scenario: Discovery contract drifts from OpenAPI
- **WHEN** a documented route, parameter, or response model no longer matches the generated OpenAPI contract
- **THEN** the deterministic documentation contract check fails instead of publishing silently stale guidance

### Requirement: Compact exact-date overview
The system SHALL expose `GET /api/v2/market-environment/{as_of}/overview` as the first data call for AI clients. The response MUST contain the exact date, generation time, opaque snapshot revision, compact market conclusions, per-resource availability and quality summaries, and links to available detail resources, and MUST NOT embed index histories, security-pool rows, sector ranking rows, operation checkpoints, or the complete Chapter 01 aggregate. A stored row that exists but fails checksum or exact-date integrity validation MUST be distinguished from an absent resource and MUST NOT be serialized as a successful overview.

#### Scenario: Exact-date overview is available
- **WHEN** the requested trading date has locally materialized market evidence that passes integrity validation
- **THEN** the overview returns only compact summaries and links for that exact date with zero external provider calls

#### Scenario: Some resources are unavailable
- **WHEN** core evidence exists but one or more sibling datasets are missing or insufficient
- **THEN** the overview remains available, identifies each affected resource as `missing` or `insufficient`, and does not fabricate counts, links, or zero-valued evidence

#### Scenario: Date has no local evidence
- **WHEN** no local snapshot, aggregate, or supported resource exists for the requested exact date
- **THEN** the endpoint returns a stable not-found error and does not substitute another date or trigger collection

#### Scenario: Stored overview fails integrity validation
- **WHEN** a row exists for the requested date but its checksum, payload date, or effective-date evidence conflicts with its storage key
- **THEN** the endpoint returns HTTP 503 with stable code `snapshot_integrity_error`, reveals no internal database or provider values, and neither substitutes another date nor triggers collection

### Requirement: Resource-level market data endpoints
The system SHALL expose separate exact-date resources for index summaries, one index, one index history, breadth summary, breadth history, limits summary, one limits pool, limits history, limits rule/risk evidence, sector rankings, sector turnover observations, sector breadth, sector continuity analysis, active direction, events, and assessment. A resource response MUST contain only its declared resource and shared envelope fields.

#### Scenario: Client requests index summaries
- **WHEN** a client requests the indices collection for an exact date
- **THEN** it receives the configured index summaries without any index `history` arrays

#### Scenario: Client requests one index history
- **WHEN** a client requests history for one normalized index code and a bounded date window
- **THEN** it receives only that index's ordered history points and related quality metadata

#### Scenario: Client requests limits summary
- **WHEN** a client requests the limits resource without a pool or history subresource
- **THEN** it receives aggregate counts, ratios, ladder/stratification summaries and quality but no security-detail rows or historical points

#### Scenario: Client requests one sector resource
- **WHEN** a client requests rankings, turnover, breadth, or continuity analysis
- **THEN** it receives only that named sector resource and does not receive unrelated Chapter 01 siblings

#### Scenario: Unsupported resource selector is supplied
- **WHEN** a client supplies an unknown index code, pool type, sector tag, sort field, or other closed selector
- **THEN** the API returns a stable validation or not-found error before reading unrelated data

### Requirement: Bounded and stable collections
Every variable-length collection exposed by the versioned API SHALL have a server-enforced default size, hard maximum, deterministic sort order, and opaque continuation cursor bound to the snapshot revision. Fixed-size index summary collections MAY remain unpaginated.

#### Scenario: Client omits a collection limit
- **WHEN** a client requests a securities pool, ranking, active-direction list, history series, or operation checkpoints without a limit
- **THEN** the server applies the documented default and returns continuation metadata when more rows exist

#### Scenario: Client exceeds the maximum limit
- **WHEN** a requested limit is zero, negative, or greater than the endpoint maximum
- **THEN** the request is rejected with a stable validation error and no unbounded query is executed

#### Scenario: Client continues a page
- **WHEN** a client submits a valid continuation cursor
- **THEN** the server resumes after the last stable sort key under the same snapshot revision without duplicating earlier rows

#### Scenario: Cursor revision is stale
- **WHEN** the cursor revision no longer matches the current exact-date snapshot revision
- **THEN** the API rejects the cursor with a stable revision-conflict response and identifies the current revision so the client can restart

### Requirement: Consistent response envelope and revision pinning
Every versioned market-data response SHALL include `asOf`, `generatedAt`, an opaque `snapshotRevision`, `quality`, `data`, and resource links; paginated responses SHALL also include pagination metadata. Clients MUST be able to pin follow-up requests to the revision obtained from overview, and responses SHALL expose the same revision as an HTTP ETag.

#### Scenario: Multi-resource read uses one revision
- **WHEN** a client passes the overview revision to several follow-up resource requests and that revision is still current
- **THEN** every response is derived from the same exact-date component revision and returns that revision

#### Scenario: Pinned revision changed
- **WHEN** a follow-up request pins a revision that was replaced by a newer materialization
- **THEN** the API returns a revision-conflict response rather than mixing evidence from different revisions

#### Scenario: Conditional request is unchanged
- **WHEN** a client sends `If-None-Match` with the current resource ETag
- **THEN** the API returns HTTP 304 without serializing the resource body or invoking a provider

### Requirement: Exact-date and quality semantics
The versioned API SHALL preserve the stored actual date, source, provider, observation count, cache/freshness state, quality status, warnings, and relevant revision/checksum evidence. Missing values MUST remain `null`, `missing`, `insufficient`, `degraded`, `failed-retained`, or `failed-missing` as appropriate and MUST NOT be replaced by zero or evidence from another date. Evidence that fails stored integrity validation MUST be reported as unavailable through the stable integrity error contract rather than treated as missing or successful data.

#### Scenario: Exact-date dataset is missing
- **WHEN** the requested date is valid but the selected dataset has no exact-date evidence
- **THEN** the resource returns explicit missing or insufficient quality with null or empty bounded data and no cross-date fallback

#### Scenario: Same-date refresh previously failed
- **WHEN** the stored exact-date evidence was retained after a failed refresh
- **THEN** the resource returns the retained values with the real freshness state and refresh warning rather than presenting them as a new success

#### Scenario: Historical provider data is unavailable
- **WHEN** a resource cannot prove historical-date capability
- **THEN** the API reports insufficient evidence and does not call a latest-only provider or relabel current data

#### Scenario: Stored cross-date evidence is encountered
- **WHEN** a versioned resource read detects that locally stored evidence belongs to another date
- **THEN** the API returns the stable integrity-unavailable response, returns no values from that row, performs zero provider calls, and performs zero PostgreSQL writes

### Requirement: Provider-free and read-only boundary
All versioned GET and discovery endpoints SHALL read only local application repositories or materialized evidence and MUST NOT construct a provider client, start or join collection work, mutate PostgreSQL, create background tasks, download dumps, or expose credentials and raw provider responses.

#### Scenario: Providers are unavailable
- **WHEN** every external provider is unavailable but local exact-date evidence exists
- **THEN** all corresponding versioned reads and discovery documents remain available from local state

#### Scenario: Local evidence is absent
- **WHEN** a versioned read has no local evidence
- **THEN** it returns the documented missing/not-found result with provider call count and write count both equal to zero

#### Scenario: Client attempts arbitrary projection
- **WHEN** a client supplies an unsupported `fields`, `include`, SQL-like filter, or arbitrary nested expansion
- **THEN** the API rejects or ignores it according to the closed OpenAPI contract and never evaluates it as a query expression

### Requirement: Operation progress is separated from checkpoints
The versioned API SHALL expose an operation summary independently from its variable-length checkpoint collection, and checkpoint reads SHALL use the same bounded pagination and revision rules as other collections.

#### Scenario: Client polls operation progress
- **WHEN** a client requests an operation by run identifier
- **THEN** it receives status, counts, timestamps, request budget and warnings without the checkpoint rows

#### Scenario: Client inspects operation checkpoints
- **WHEN** a client requests the checkpoint subresource
- **THEN** it receives a bounded, deterministically ordered page of checkpoints and continuation metadata

### Requirement: Legacy API compatibility and gradual migration
The system SHALL preserve the paths, successful response fields, and observable behavior of the existing unversioned market-environment, core, Chapter 01, next-session, collection, and THS read endpoints while the new versioned API is introduced. Existing full responses MAY be marked deprecated in OpenAPI but MUST NOT be removed by this change. Integrity failures MAY use the shared stable error contract but MUST remain fail closed and MUST NOT expose cross-date evidence as a successful legacy response.

#### Scenario: Existing dashboard uses legacy endpoints
- **WHEN** an existing client continues calling the current unversioned endpoints with valid exact-date evidence
- **THEN** its successful responses remain schema-compatible without requiring the client to adopt the versioned envelope

#### Scenario: New client avoids the legacy aggregate
- **WHEN** an AI client follows `/llms.txt` or the overview links
- **THEN** it is directed to versioned bounded resources rather than the complete legacy aggregate

#### Scenario: Frontend migrates one resource at a time
- **WHEN** the dashboard switches one page to a versioned resource while other pages still use legacy endpoints
- **THEN** both paths can operate concurrently against the same exact-date local evidence

#### Scenario: Frontend receives an integrity error
- **WHEN** a dashboard v2 request returns `snapshot_integrity_error`
- **THEN** the dashboard presents an explicit data-integrity failure and does not replace it with evidence from a legacy response or another date

### Requirement: Limits pools preserve valid membership independently of enrichment

The versioned `limit_up`, `limit_down`, and `failed_limit_up` pool resources SHALL return exact-date members with valid security identity even when optional board, ST, listing-window, or limit-regime attributes are unavailable or a stored exclusion reason applies only to legacy promotion eligibility. They MUST exclude malformed or conflicting identities, missing or conflicting actual dates, invalid duplicates, and conflicting pool memberships. Membership visibility MUST NOT imply that a row has valid consecutive-board data or complete advanced classification attributes.

#### Scenario: Advanced attributes are missing
- **WHEN** a stored exact-date pool member has valid identity but is excluded from legacy promotion eligibility because board or listing-window evidence is missing
- **THEN** the corresponding pool returns that member with its stored nullable attributes, source, row quality and exclusion warning preserved

#### Scenario: Failed and down members are outside legacy promotion scope
- **WHEN** a valid exact-date failed-limit-up or limit-down member has a legacy exclusion reason indicating that it is outside the promotion pool
- **THEN** the member remains visible in its own pool without being presented as a promoted security

#### Scenario: Identity or date evidence is invalid
- **WHEN** a stored row has missing identity, identity conflicts, missing or mismatched actual date, an invalid duplicate marker, or conflicting pool membership
- **THEN** that row is excluded from pool results and its exclusion is not concealed by upgrading the stored dataset quality

#### Scenario: Consecutive-board evidence is unavailable
- **WHEN** a valid limit-up member has no valid consecutive-board count
- **THEN** the pool returns the member with the original missing value and does not invent a first-board or higher-tier assignment

### Requirement: Promoted pool agrees with the validated adjacent-session aggregate

The versioned `promoted` pool SHALL represent the same identity intersection as the stored validated basic promotion aggregate: valid closing-limit-up members from the requested session and its proven immediately preceding trading session. Both dated memberships MUST be complete, use the supported promotion rule version, and be bound to their matching aggregate checksums. Legacy enrichment eligibility MUST NOT be an additional inclusion requirement. Missing or invalid prerequisites MUST NOT produce a successful promoted collection; stored integrity failures MUST retain the established integrity error contract.

#### Scenario: Basic promotion is valid despite incomplete enrichment
- **WHEN** both complete adjacent-session limit-up memberships and their aggregate bindings are valid, and shared members lack optional enrichment attributes
- **THEN** the promoted pool contains those shared valid members and its full paginated count agrees with the promotion numerator for the same revision

#### Scenario: Previous membership contains invalid rows
- **WHEN** a current valid closing-limit-up member matches a previous row whose identity or actual date is invalid
- **THEN** the previous row cannot establish promotion and the response retains the applicable incomplete-evidence status

#### Scenario: Adjacent-session prerequisites are unavailable
- **WHEN** the immediately previous trading session is unproven, either dated membership is incomplete, or its rule version is unsupported
- **THEN** the promoted resource returns explicit missing or insufficient evidence without a successful member list, without searching older sessions, and without collecting data

#### Scenario: Stored promotion binding is corrupt
- **WHEN** the stored membership checksum does not match its bound limits aggregate
- **THEN** the resource returns the existing stable integrity-unavailable response and performs no writes or external provider calls

#### Scenario: Previous complete membership is empty
- **WHEN** the preceding trading session has a proven complete but empty limit-up membership
- **THEN** the promoted collection is empty, the promotion ratio remains null with zero-denominator insufficient quality, and no empty result is reinterpreted as missing collection

### Requirement: Restored limits membership preserves bounded read and quality contracts

Limits pool reads SHALL retain deterministic identity ordering, server-enforced limits, revision-bound cursors, exact-date metadata, source, observation semantics and refresh warnings. Pool filtering MUST occur before page boundaries are applied, so invalid stored rows cannot hide valid rows on later pages. Dataset observation counts MUST remain distinct from the current page's returned count; observations alone MUST NOT be represented as verified tier membership. All restored reads MUST remain provider-free and write-free.

#### Scenario: Valid and invalid stored rows span multiple pages
- **WHEN** a client reads all pages under one revision from a pool containing both valid members and excluded rows
- **THEN** it receives each valid member once in stable order without invalid rows, skipped valid members, or premature pagination termination

#### Scenario: Same-date evidence was retained after refresh failure
- **WHEN** restored members are read from a same-date retained snapshot following a failed refresh
- **THEN** the response keeps the stored retained or degraded quality and refresh warning rather than presenting a new collection success

#### Scenario: Pool is proven empty
- **WHEN** the requested date has an explicitly complete pool with zero valid members
- **THEN** the collection returns a true empty result with its stored quality, without substituting another date or creating members

#### Scenario: Revision changes while reading restored members
- **WHEN** a pool continuation or pinned follow-up request uses a replaced snapshot revision
- **THEN** the API returns the existing revision-conflict response rather than mixing member sets
