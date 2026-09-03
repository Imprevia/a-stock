## ADDED Requirements

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
