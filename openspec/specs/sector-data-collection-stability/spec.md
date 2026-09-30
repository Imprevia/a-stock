# Sector Data Collection Stability Specification

## Purpose

Define exact-date, fail-closed stability contracts for sector market data collection. The
primary source remains the Eastmoney `push2`/`push2delay` pair. A separately gated Fuyao
fallback may provide only the documented THS industry-index fields; it is not an equivalent
source for sector fund flow, breadth, or leader facts.

## Requirements

### Requirement: Sector endpoints use the unified transport without changing fallback order
The system SHALL send both Eastmoney sector endpoint requests through the unified transport while preserving primary-first ordering, bounded recovery, delayed fallback, and existing quality warnings.

#### Scenario: Primary sector host is cooling down
- **WHEN** the primary host is in transport cooldown
- **THEN** the collector skips repeated primary attempts for that request and proceeds to the existing delayed endpoint fallback with an auditable warning

#### Scenario: Delayed sector response is cached
- **WHEN** an identical delayed sector request is repeated within the request TTL
- **THEN** the cached response is used without changing the reported source or fallback quality status

### Requirement: Collection page uses the server market date
The system SHALL initialize the data-collection page from the Shanghai market date returned by the server, while preserving the settlement-oriented default date used by the research dashboard.

#### Scenario: Collection page opens before the dashboard cutoff
- **WHEN** the collection page opens before 15:00 Shanghai time without an explicitly selected date
- **THEN** the first status response selects the current Shanghai market date and latest-only datasets are not disabled merely because the research dashboard defaults to the previous date

#### Scenario: User selects a historical date
- **WHEN** the user explicitly selects a historical date
- **THEN** the page requests that exact date and continues to show the backend restriction for latest-only datasets

### Requirement: Eastmoney requests are serialized and recover transient failures
The system SHALL serialize all in-process Eastmoney HTTP requests across collection workers and SHALL apply a bounded retry policy to transient connection failures, read failures, HTTP 429, and HTTP 5xx responses.

#### Scenario: Two workers request Eastmoney data
- **WHEN** two collection workers attempt Eastmoney requests concurrently
- **THEN** only one Eastmoney HTTP request is in flight and the next request observes the configured minimum interval and jitter

#### Scenario: Transient disconnect recovers
- **WHEN** an Eastmoney request encounters a transient connection or read failure and a later attempt succeeds within the retry budget
- **THEN** the client returns the successful payload without recording the dataset as failed

#### Scenario: Eastmoney returns HTTP 403
- **WHEN** Eastmoney returns HTTP 403
- **THEN** the client performs no blind retry and exposes a non-retryable provider failure

### Requirement: Sector ranking falls back to the delayed endpoint
The system SHALL request the primary Eastmoney industry ranking endpoint first and SHALL fall back to the compatible delayed endpoint after the primary path exhausts its permitted recovery attempts.

#### Scenario: Primary sector endpoint disconnects
- **WHEN** the primary industry ranking endpoint remains unavailable after bounded transient retries and the delayed endpoint returns valid rows
- **THEN** the sector dataset is saved with those rows, a fallback quality status and source, and a warning containing the primary failure

#### Scenario: Both sector endpoints fail
- **WHEN** neither the primary nor delayed industry ranking endpoint returns a valid payload
- **THEN** collection reports failure and retains an existing successful snapshot only when it belongs to the same exact date

#### Scenario: Historical sector collection is requested
- **WHEN** a sector collection request targets a date other than the current Shanghai market date
- **THEN** the request is rejected and neither endpoint is called

### Requirement: Fuyao sector fallback uses the documented THS index contract
The system SHALL use the Fuyao trading-day calendar, THS industry-index catalog, and batched
THS index snapshot endpoints for an approved sector fallback. The base URL is
`https://fuyao.aicubes.cn`, with paths `/api/a-share/calendar/trading-days`,
`/api/a-share-index/catalog/ths-index-list?tag=industry`, and
`/api/a-share-index/prices/snapshot?thscodes=...`. The adapter MUST reject missing keys,
HTTP/business errors, incomplete catalog or snapshot coverage, duplicate identities, and
inconsistent timestamps without producing a successful result.

#### Scenario: Approved fallback receives a complete industry batch
- **WHEN** Eastmoney primary and delayed requests fail, the sectors switch is enabled, the
  capability report is `eligible` with a matching approved revision, the requested date is a
  Shanghai trading day, and all catalog identities have matching snapshot rows
- **THEN** the adapter returns stable rows sorted by change percentage descending and THS code
  ascending, and records the Fuyao source and approved revision

#### Scenario: Fuyao coverage is incomplete
- **WHEN** the catalog or any snapshot batch is incomplete, has duplicate identities, or has
  inconsistent timestamps
- **THEN** the fallback is `insufficient`/failed, no successful sector snapshot is written,
  and the collection layer retains the same-date snapshot or reports `failed-missing`

#### Scenario: Fuyao cannot prove the requested date
- **WHEN** the calendar does not contain the requested date, a snapshot timestamp is absent or
  belongs to another Shanghai date, or batches map to different Shanghai dates
- **THEN** the adapter rejects the result and never relabels a latest snapshot as historical data

### Requirement: Fuyao sector fallback exposes only supported fields
The system SHALL map Fuyao THS rows to the compatible `SectorRow` shape using code, name,
change percentage, and turnover. Main net flow, main net flow percentage, advancing/declining
counts, and leader name MUST remain `null` when the provider does not supply them, with a
structured field-availability warning and degraded/fallback quality.

#### Scenario: Supported THS fields are present
- **WHEN** a valid snapshot row contains a unique THS code, name, change percentage, and turnover
- **THEN** those four values are exposed without synthesizing unsupported fields

#### Scenario: Unsupported industry fields are absent
- **WHEN** Fuyao does not return fund-flow, breadth, or leader fields
- **THEN** the API leaves those fields `null`, reports the missing-field warning, and does not
  display a code as a leader name or fill a numeric field with zero

### Requirement: Fuyao sector capability is fail-closed and auditable
The system SHALL call the Fuyao sector fallback only when
`MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED=1`, a stored capability report is `eligible`, and
the approved revision exactly matches that report. Capability evidence MUST be redacted and
include endpoints, requested date, calendar proof, catalog/snapshot counts, field coverage,
permission, and rate-limit outcomes without an API key.

#### Scenario: Capability gate is not satisfied
- **WHEN** the switch is disabled, the report is missing/non-eligible, or the approved revision
  does not match
- **THEN** no Fuyao request is made and the existing Eastmoney failure-retention path is used

#### Scenario: Capability evidence is generated
- **WHEN** an authorized probe completes in an isolated after-hours environment
- **THEN** the report contains only redacted contract evidence and can be reviewed before an
  approved revision is configured; it does not write a formal sector snapshot

### Requirement: Sector leader fields match the provider contract
The system SHALL expose the industry leader as a security name derived from the provider's leader-name field and MUST NOT display the leader security code as the name.

#### Scenario: Provider returns leader name and code
- **WHEN** an industry row contains a leader name in `f128` and a leader code in `f140`
- **THEN** the API `leader` field contains the `f128` name value

#### Scenario: Provider omits the optional leader name
- **WHEN** an otherwise valid industry row does not contain a leader name
- **THEN** the row remains usable and its `leader` field is `null`

### Requirement: Sector failure remains auditable
The system SHALL preserve existing collection isolation and exact-date retention semantics when sector recovery and fallback are exhausted.

#### Scenario: Sector retry fails with a same-date snapshot
- **WHEN** sector collection fails after all recovery paths and a successful sector snapshot exists for the same date
- **THEN** the task is recorded as `failed-retained`, the snapshot remains available, and the latest failure warning is exposed

#### Scenario: Sector retry fails without a same-date snapshot
- **WHEN** sector collection fails after all recovery paths and no successful sector snapshot exists for that date
- **THEN** the task is recorded as `failed-missing` and no snapshot from another date is substituted
