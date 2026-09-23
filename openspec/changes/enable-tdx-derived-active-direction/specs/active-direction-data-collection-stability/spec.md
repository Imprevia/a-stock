## MODIFIED Requirements

### Requirement: Active direction uses a validated endpoint fallback chain
The system SHALL request the primary Eastmoney turnover-ranked stock endpoint first and SHALL request the compatible delayed endpoint only after the primary path exhausts its permitted recovery attempts or returns an invalid payload. When both Eastmoney paths fail, the system MAY request the TDX daily package only when the derived fallback is explicitly enabled; the TDX package MUST belong to the selected market date and MUST pass the derived-source contract before use.

#### Scenario: Primary active-direction endpoint succeeds
- **WHEN** the primary endpoint returns a valid turnover-ranked Top-N payload
- **THEN** the system uses the primary rows, records source `eastmoney-clist`, and does not call the delayed endpoint or TDX package

#### Scenario: Primary active-direction endpoint remains unavailable
- **WHEN** the primary endpoint remains unavailable after bounded recovery and the delayed endpoint returns a valid payload
- **THEN** the system uses the delayed rows, records source `eastmoney-clist-delay`, and does not call the TDX package

#### Scenario: Both Eastmoney endpoints fail and derived fallback succeeds
- **WHEN** neither Eastmoney endpoint returns a valid payload, the derived fallback is enabled, and the TDX package proves the selected date and passes all derived-source validation
- **THEN** the system uses the locally ranked TDX result, records source `tdx-daily-package-derived`, and records quality status `fallback-derived` with warnings for both failed Eastmoney paths

#### Scenario: Both Eastmoney endpoints fail and derived fallback is disabled
- **WHEN** neither Eastmoney endpoint returns a valid payload and the derived fallback is disabled
- **THEN** the active-direction collection reports failure and does not request the TDX package

#### Scenario: Both active-direction endpoints fail
- **WHEN** neither Eastmoney endpoint returns a valid payload and the TDX derived fallback is disabled or unavailable
- **THEN** the active-direction collection reports failure with warnings that identify both failed Eastmoney paths and any final TDX result

#### Scenario: Every active-direction path fails
- **WHEN** the primary endpoint, delayed endpoint, and any enabled TDX candidate all fail validation or transport
- **THEN** the active-direction collection reports failure with warnings identifying every attempted path and does not write a pseudo-success snapshot

### Requirement: Every active-direction source satisfies the same Top-N contract
The system MUST validate every primary, delayed, or TDX candidate payload before deriving or storing active-direction evidence. Eastmoney candidates MUST already be in non-increasing turnover order. A TDX candidate MAY be locally ranked, but MUST provide at least 30 valid rows for the selected date with a security code, trusted security name, numeric turnover amount, and close price before ranking; local ranking MUST NOT be represented as provider-ranked evidence.

#### Scenario: Delayed endpoint returns enough valid sorted rows
- **WHEN** the delayed endpoint returns at least 30 object rows with a security code, security name, numeric turnover amount, and non-increasing turnover order
- **THEN** the system may derive the Top-30 industry cluster and Top-10 display rows from that payload

#### Scenario: TDX package returns enough valid rows
- **WHEN** the TDX package belongs to the selected date and at least 30 rows contain valid code, trusted name, close, and turnover amount
- **THEN** the system sorts the valid rows by turnover descending with a deterministic security-identity tie-breaker and uses the resulting Top-30/Top-10 as derived evidence

#### Scenario: TDX package contains unsorted source rows
- **WHEN** the TDX package rows are not in turnover-descending order
- **THEN** the system MAY locally sort them only under the derived fallback path, and MUST label the result `fallback-derived` rather than `fallback`, `partial`, or provider-ranked `ok`

#### Scenario: TDX package has insufficient rows or facts
- **WHEN** fewer than 30 TDX rows have valid code, trusted name, close, and turnover amount, or the package date does not equal the selected date
- **THEN** the TDX candidate is rejected and no successful active-direction snapshot is written from it

#### Scenario: Delayed endpoint returns too few valid rows
- **WHEN** fewer than 30 delayed rows contain all required code, name, and turnover fields
- **THEN** the delayed payload is rejected and no successful snapshot is written from it

#### Scenario: Delayed endpoint returns unsorted rows
- **WHEN** any later valid delayed row has a greater turnover amount than the preceding valid row
- **THEN** the delayed payload is rejected rather than locally reordered and represented as a provider-ranked result

#### Scenario: Candidate source lacks names
- **WHEN** a candidate row has no trusted security name in the package and the bounded name-resolution path cannot resolve it without replacing TDX price, amount, or date facts
- **THEN** the candidate is rejected and the unresolved code is included in the quality warning

#### Scenario: Provider returns a keyed diff object
- **WHEN** an Eastmoney endpoint returns `data.diff` as an object keyed by row index instead of an array
- **THEN** the system normalizes its values and applies the same field, sample, date, and ordering validation

### Requirement: Active-direction fallback quality is auditable
The system SHALL expose the actual active-direction source, quality status, observations, ranking method, and recovery warnings through the existing quality contract. Derived TDX results MUST include the pinned package revision and, when industry aggregation is attempted, the industry-mapping revision and coverage.

#### Scenario: Delayed endpoint supplies the result
- **WHEN** the delayed endpoint supplies a valid active-direction result after primary failure
- **THEN** quality source is `eastmoney-clist-delay`, quality status is `fallback`, observations reflect the validated Top-30 sample, and warnings retain the primary failure and fallback explanation

#### Scenario: TDX package supplies the result
- **WHEN** the TDX package supplies a valid result after both Eastmoney paths fail
- **THEN** quality source is `tdx-daily-package-derived`, quality status is `fallback-derived`, ranking method identifies local turnover sorting, observations reflect the validated Top-30 sample, and warnings retain all preceding failures

#### Scenario: TDX industry mapping is incomplete
- **WHEN** the TDX Top-30 rows do not have complete coverage from a versioned code-to-industry mapping
- **THEN** the system may expose the mapped industries on individual stock rows, but MUST mark the industry-cluster state `insufficient` or `unverified` and MUST expose mapping revision and coverage rather than inferring a direction

#### Scenario: Primary endpoint supplies the result
- **WHEN** the primary endpoint supplies a valid active-direction result
- **THEN** quality source remains `eastmoney-clist`, quality status remains `partial`, and no fallback warning is added

#### Scenario: Consumer ignores quality metadata
- **WHEN** an existing consumer reads only the active-direction state, summary, and Top-10 stock fields
- **THEN** those fields remain compatible and require no API or frontend migration

### Requirement: Active-direction failure preserves exact-date data semantics
The system SHALL preserve successful active-direction snapshots separately from failed collection attempts and MUST NOT substitute a snapshot from another date. A validated `fallback-derived` result is a successful exact-date snapshot, but remains visibly derived and degraded in quality metadata.

#### Scenario: Derived fallback fails with a same-date snapshot
- **WHEN** both Eastmoney endpoints and the enabled TDX fallback fail and a successful snapshot exists for the same selected date
- **THEN** the task is recorded as `failed-retained`, the same-date snapshot remains available, and the latest failure warning is exposed

#### Scenario: Fallback chain fails with a same-date snapshot
- **WHEN** both active-direction endpoints and any enabled TDX fallback fail and a successful snapshot exists for the same selected date
- **THEN** the task is recorded as `failed-retained`, the same-date snapshot remains available, and the latest failure warning is exposed

#### Scenario: Derived fallback succeeds with no prior snapshot
- **WHEN** both Eastmoney endpoints fail and the enabled TDX fallback passes exact-date and derived validation
- **THEN** the system stores the TDX result for that exact date, exposes it as `fallback-derived`, and does not require a prior provider-ranked snapshot

#### Scenario: Fallback chain fails without a same-date snapshot
- **WHEN** both active-direction endpoints and the enabled TDX fallback fail and no successful snapshot exists for the selected date
- **THEN** the task is recorded as `failed-missing` and active-direction evidence remains `insufficient`

#### Scenario: Historical active-direction collection is requested
- **WHEN** the selected date is not the current Shanghai market date and the collection path is a latest-only active-direction request
- **THEN** the request is rejected before any provider is called and no current or derived data is written under the historical date
