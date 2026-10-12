## ADDED Requirements

### Requirement: Sector analysis readiness is visible through provider-free reads
The system SHALL expose the selected date's exact-date sector observation, when one was proven and stored for that date, and point-in-time continuity analysis separately in the selected date's `sectors` status and materialized response. A latest-only current-day observation MUST appear as unsupported or missing for a different historical selected date. Stored analysis metadata SHALL include required and available history, missing sessions, identity and constituent coverage, data version, classification version, calculation version, evidence references, quality, latest attempt, and warnings. Reading these values MUST NOT call a provider, start collection, or substitute another date.

#### Scenario: Observation and analysis are available
- **WHEN** a selected date has a valid ranking and complete compatible analysis
- **THEN** provider-free reads expose both states with distinct lineage, versions, coverage, and warnings

#### Scenario: Ranking is available but analysis has gaps
- **WHEN** ranking succeeds but analysis lacks history, membership, benchmark, or compatible versions
- **THEN** ranking remains available and analysis is degraded or `insufficient` without zero-filled metrics

#### Scenario: Providers are unavailable during a status read
- **WHEN** all relevant providers are unavailable
- **THEN** locally stored observation, analysis readiness, backfill progress, and warnings remain readable without provider I/O

#### Scenario: Historical date has only today's latest observation
- **WHEN** a historical selected date lacks an exact-date observation but a latest-only ranking exists for the current date
- **THEN** the historical response reports the observation as unsupported or missing and does not display today's ranking under the historical date

### Requirement: Historical sector backfill is explicit, bounded, resumable, and auditable
The system SHALL provide an explicit operator-triggered historical backfill for point-in-time industry facts and analysis. A request SHALL identify a bounded trading-session range and approved source, data, classification, and calculation revisions; it SHALL process exact dates idempotently, persist progress and per-date outcomes, and retry unresolved dates without rewriting compatible successes. Dashboard GETs, status reads, the existing full five-dataset collection, startup, and default-disabled scheduling MUST NOT start the backfill.

#### Scenario: Operator starts an approved backfill
- **WHEN** an authorized operator requests a bounded session range with approved revisions
- **THEN** the system records the request and exposes per-date progress, coverage, outcome, and warnings

#### Scenario: Interrupted backfill is resumed
- **WHEN** a backfill stops after completing part of its range
- **THEN** compatible successful dates are reused and incomplete dates resume without duplicate work

#### Scenario: Backfill is repeated with a new version
- **WHEN** processed dates are requested under a newer data, classification, or calculation version
- **THEN** the new results retain lineage to prior evidence and do not silently mutate it

#### Scenario: Ordinary collection or read is performed
- **WHEN** a user loads the dashboard, reads status, requests an aggregate, or invokes the existing full collection action
- **THEN** no historical backfill begins and the five current datasets retain their date-capability behavior

### Requirement: Sector backfill failures preserve independent results
The system SHALL isolate every backfill date and stage so one failure does not stop successful dates, hide current observations, or overwrite a compatible successful same-date analysis. Summaries SHALL distinguish success, partial, failed-retained, failed-missing, and insufficient outcomes and SHALL expose retry eligibility through provider-free reads.

#### Scenario: One date fails in a multi-date backfill
- **WHEN** some dates succeed and another fails or is insufficient
- **THEN** successful dates remain committed and the parent operation finishes as partial with classified failures

#### Scenario: Failed date has a compatible retained result
- **WHEN** an attempt fails for a date with an existing compatible success
- **THEN** the success remains readable and the attempt is reported as failed-retained

#### Scenario: Failed date has no compatible retained result
- **WHEN** an attempt fails without a compatible exact-date success
- **THEN** the date is failed-missing or insufficient, remains retryable, and receives no cross-date substitute

### Requirement: Collection management presents analysis readiness without changing normal collection scope
The data-management page SHALL display sector-analysis required and available history, missing sessions, coverage, versions, latest attempt, warnings, and retry eligibility separately from the five normal collection datasets. It SHALL provide no backfill start or retry action unless a separately authorized operator workflow is enabled. Existing per-dataset retry and “collect all” actions MUST continue to target only `core`, `breadth`, `limits`, `sectors`, and `activeDirection`.

All visible collection-management text and controls SHALL be at least 14 pixels, and a 390-pixel viewport MUST remain usable without page-level horizontal overflow, overlap, or truncation.

#### Scenario: Analysis history is incomplete
- **WHEN** the selected date has an exact-date sector observation but fewer than the required analysis sessions
- **THEN** the page keeps the `sectors` observation status and separately displays missing analysis sessions, coverage, warnings, and retry eligibility

#### Scenario: User invokes collect all
- **WHEN** a user invokes the existing full collection action
- **THEN** exactly the five normal dataset tasks are requested and no sector backfill run is created

#### Scenario: Backfill operation is not authorized
- **WHEN** the separately authorized operator workflow is disabled
- **THEN** the page exposes readiness as read-only and presents no control that can start historical provider work

#### Scenario: Collection management is viewed on a narrow screen
- **WHEN** the page is rendered at 390 pixels wide
- **THEN** readiness, warnings, and normal collection controls remain readable and usable without page-level overflow or text smaller than 14 pixels
