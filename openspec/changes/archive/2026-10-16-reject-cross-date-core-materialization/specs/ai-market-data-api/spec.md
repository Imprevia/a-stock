## MODIFIED Requirements

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
