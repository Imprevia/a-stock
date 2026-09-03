## ADDED Requirements

### Requirement: Active direction uses a validated endpoint fallback chain
The system SHALL request the primary Eastmoney turnover-ranked stock endpoint first and SHALL request the compatible delayed endpoint only after the primary path exhausts its permitted recovery attempts or returns an invalid payload.

#### Scenario: Primary active-direction endpoint succeeds
- **WHEN** the primary endpoint returns a valid turnover-ranked Top-N payload
- **THEN** the system uses the primary rows, records source `eastmoney-clist`, and does not call the delayed endpoint

#### Scenario: Primary active-direction endpoint remains unavailable
- **WHEN** the primary endpoint remains unavailable after bounded recovery and the delayed endpoint returns a valid payload
- **THEN** the system uses the delayed rows and completes the active-direction dataset as a successful fallback

#### Scenario: Both active-direction endpoints fail
- **WHEN** neither the primary nor delayed endpoint returns a valid payload
- **THEN** the active-direction collection reports failure with warnings that identify both failed paths

### Requirement: Every active-direction source satisfies the same Top-N contract
The system MUST validate every primary or delayed candidate payload before deriving or storing active-direction evidence, and MUST NOT weaken validation for a fallback source.

#### Scenario: Delayed endpoint returns enough valid sorted rows
- **WHEN** the delayed endpoint returns at least 30 object rows with a security code, security name, numeric turnover amount, and non-increasing turnover order
- **THEN** the system may derive the Top-30 industry cluster and Top-10 display rows from that payload

#### Scenario: Delayed endpoint returns too few valid rows
- **WHEN** fewer than 30 delayed rows contain all required code, name, and turnover fields
- **THEN** the payload is rejected and no successful snapshot is written from it

#### Scenario: Delayed endpoint returns unsorted rows
- **WHEN** any later valid delayed row has a greater turnover amount than the preceding valid row
- **THEN** the payload is rejected rather than locally reordered and represented as a provider-ranked result

#### Scenario: Provider returns a keyed diff object
- **WHEN** either endpoint returns `data.diff` as an object keyed by row index instead of an array
- **THEN** the system normalizes its values and applies the same field, sample, and ordering validation

### Requirement: Active-direction fallback quality is auditable
The system SHALL expose the actual active-direction source, quality status, observations, and recovery warnings through the existing quality contract.

#### Scenario: Delayed endpoint supplies the result
- **WHEN** the delayed endpoint supplies a valid active-direction result after primary failure
- **THEN** quality source is `eastmoney-clist-delay`, quality status is `fallback`, observations reflect the validated Top-30 sample, and warnings retain the primary failure and fallback explanation

#### Scenario: Primary endpoint supplies the result
- **WHEN** the primary endpoint supplies a valid active-direction result
- **THEN** quality source remains `eastmoney-clist`, quality status remains `partial`, and no fallback warning is added

#### Scenario: Consumer ignores quality metadata
- **WHEN** an existing consumer reads only the active-direction state, summary, and Top-10 stock fields
- **THEN** those fields remain compatible and require no API or frontend migration

### Requirement: Active-direction failure preserves exact-date data semantics
The system SHALL preserve successful active-direction snapshots separately from failed collection attempts and MUST NOT substitute a snapshot from another date.

#### Scenario: Fallback chain fails with a same-date snapshot
- **WHEN** both active-direction endpoints fail and a successful snapshot exists for the same selected date
- **THEN** the task is recorded as `failed-retained`, the same-date snapshot remains available, and the latest failure warning is exposed

#### Scenario: Fallback chain fails without a same-date snapshot
- **WHEN** both active-direction endpoints fail and no successful snapshot exists for the selected date
- **THEN** the task is recorded as `failed-missing` and active-direction evidence remains `insufficient`

#### Scenario: Historical active-direction collection is requested
- **WHEN** the selected date is not the current Shanghai market date and the provider cannot prove the latest snapshot belongs to it
- **THEN** the request is rejected before either active-direction endpoint is called and no current data is written under the historical date
