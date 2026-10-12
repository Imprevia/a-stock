## MODIFIED Requirements

### Requirement: Collection management status
The system SHALL provide a provider-free data-collection status view for an exact selected date covering `core`, `breadth`, `limits`, `industry-ranking`, `sector-turnover`, `sector-breadth`, and `activeDirection`, while exposing backfill/import progress separately from daily collection tasks.

#### Scenario: Status view distinguishes availability from the latest attempt
- **WHEN** a dataset has a successful exact-date snapshot but its latest collection attempt failed
- **THEN** the status reports the data as available from the retained snapshot and separately reports the latest attempt as failed with its warning

#### Scenario: Status view works when market providers are unavailable
- **WHEN** every external market provider is unavailable
- **THEN** the collection management page still loads stored status, task history, backfill/import progress, and retry controls from local state

### Requirement: Independent dataset collection tasks
The system SHALL execute `core`, `breadth`, `limits`, `industry-ranking`, `sector-turnover`, `sector-breadth`, and `activeDirection` as independently committed tasks within a parent collection run. `sector-turnover` SHALL run after a successful compatible `industry-ranking`, and `sector-breadth` SHALL run after compatible ranking and turnover inputs are available; a task failure MUST NOT roll back or invalidate successful sibling tasks.

#### Scenario: One dataset fails in a full collection run
- **WHEN** at least one requested dataset succeeds and another fails
- **THEN** successful snapshots remain committed, every failure is recorded independently, and the parent run finishes as `partial`

#### Scenario: An upstream sector task fails
- **WHEN** `industry-ranking` cannot publish a compatible revision
- **THEN** dependent sector tasks are recorded as blocked or insufficient without running incompatible provider work, and unrelated datasets continue

#### Scenario: Every dataset fails
- **WHEN** all seven dataset tasks fail without producing or retaining a valid exact-date result
- **THEN** the parent run finishes as `failed` and no previously successful snapshot is removed

#### Scenario: Every dataset succeeds
- **WHEN** all seven dataset tasks complete successfully in dependency order
- **THEN** the parent run finishes as `success` and reports every dataset task result

### Requirement: Single-dataset and full collection actions
The system SHALL provide a retry action for every supported daily dataset and one full collection action that targets all seven datasets for the selected date. A targeted dependent-sector retry SHALL either reuse compatible local prerequisites or include the required prerequisite tasks in dependency order.

#### Scenario: Retry one independent dataset
- **WHEN** a user retries `breadth`
- **THEN** the system creates or reuses a run containing only `breadth` and does not recollect unrelated datasets

#### Scenario: Retry one failed dataset
- **WHEN** a user invokes the retry action for any failed supported dataset
- **THEN** the system creates or reuses the smallest valid dependency-aware run and does not recollect unrelated datasets

#### Scenario: Retry sector breadth with compatible prerequisites
- **WHEN** compatible same-date ranking, turnover, and member facts already exist
- **THEN** the system runs only `sector-breadth` and performs no catalog or history provider request

#### Scenario: Collect all datasets
- **WHEN** a user invokes the full collection action
- **THEN** the system schedules all seven tasks, respects the sector dependency order, and continues unrelated work after any individual failure

#### Scenario: Duplicate collection request
- **WHEN** a task already holds the lease for the same dataset and exact date and another matching request arrives
- **THEN** the system returns or references the active task as `busy` or in progress and issues no duplicate provider call

### Requirement: Materialized market-environment aggregate
The system SHALL rebuild and validate the selected date's materialized market-environment response after each successful dataset commit, using the latest compatible successful exact-date results and exposing `industryRanking`, `sectorTurnover`, `sectorBreadth`, and independent `sectorAnalysis` fields. A successful new sector task MUST trigger Chapter 01 materialization even when the run contains no other dataset.

#### Scenario: Successful sector dataset updates the aggregate
- **WHEN** any new sector dataset commits a successful exact-date snapshot
- **THEN** the system rebuilds, validates, and atomically replaces the Chapter 01 aggregate with all compatible local sector fields

#### Scenario: Successful dataset updates the aggregate
- **WHEN** any supported dataset task commits a new successful exact-date snapshot
- **THEN** the system rebuilds the aggregate, validates it against the API response contract, and atomically replaces the previous materialized aggregate

#### Scenario: Aggregate contains incomplete evidence
- **WHEN** one or more datasets have no compatible exact-date result
- **THEN** the aggregate remains available when core data is usable, marks coverage as partial or degraded, and keeps unavailable evidence missing or insufficient

#### Scenario: Failed task does not remove aggregate evidence
- **WHEN** a task fails while the aggregate already references a compatible same-date successful result
- **THEN** the aggregate continues serving retained evidence and exposes the latest refresh warning

### Requirement: Collection page interaction
The system SHALL provide a dedicated `/data-collection` management page with a selected-date control, status refresh, full collection, three separate THS sector task cards, and one retry action per supported dataset. History backfill and member imports SHALL be explicit operations with independent progress and SHALL NOT masquerade as ordinary daily retries.

#### Scenario: Collection remains visible while work runs
- **WHEN** one or more tasks are running
- **THEN** the page retains the status view, shows progress and affected loading states, and does not replace the page with a blocking full-screen loader

#### Scenario: Partial run completes
- **WHEN** a full run finishes as `partial`
- **THEN** the page shows which datasets succeeded, failed, were blocked, or retained old data and enables only valid retry actions

#### Scenario: Core details are inspected
- **WHEN** the user expands the core dataset row
- **THEN** the page shows the individual state, source, duration, and warning for each configured core index

#### Scenario: Mobile collection management
- **WHEN** the page is displayed at a 390-pixel viewport width
- **THEN** all statuses, progress, and actions remain readable and usable without page-level horizontal overflow or overlapping controls

### Requirement: Date-capability enforcement
The system SHALL validate collection requests against every dataset's exact-date capability. `industry-ranking`, `sector-turnover`, and `sector-breadth` daily collection SHALL accept only the current completed Shanghai trading date; historical sector turnover SHALL use the explicit one-code backfill workflow, and historical sector breadth SHALL remain unsupported.

#### Scenario: Historical supported dataset is collected
- **WHEN** a historical date is selected and the user retries `core` or `limits`
- **THEN** the system permits the request when the underlying providers support and validate that exact date

#### Scenario: Historical latest-only dataset is rejected
- **WHEN** a historical date is selected for `breadth`, `industry-ranking`, `sector-turnover`, `sector-breadth`, or `activeDirection` through the daily collection API
- **THEN** the API rejects the request with an explanatory response and does not relabel a latest snapshot; historical turnover acquisition remains available only through explicit backfill

#### Scenario: Historical daily sector task is requested
- **WHEN** a client requests one of the three daily sector datasets for an older date
- **THEN** the daily action is rejected with guidance to the supported local query or explicit turnover backfill workflow and no latest snapshot is relabeled

#### Scenario: Intraday collection is provisional
- **WHEN** an eligible non-sector dataset is collected before its configured settlement boundary
- **THEN** successful results remain provisional, while the three provider-backed sector daily tasks are rejected before provider I/O until their completed-session boundary

#### Scenario: Intraday collection is requested
- **WHEN** the current market date has not passed the configured settlement boundary
- **THEN** provider-backed sector operations are rejected before provider I/O rather than published as settled

## ADDED Requirements

### Requirement: Legacy sectors identifier is unsupported
The public collection API, scheduler, CLI daily-dataset selector, OpenAPI schema, and frontend types MUST NOT list `sectors` as a supported dataset. An explicit `sectors` request SHALL return a stable unsupported-dataset error and MUST NOT invoke the historical collector.

#### Scenario: A legacy client submits sectors
- **WHEN** a client requests dataset `sectors`
- **THEN** the server rejects it with the migration targets `industry-ranking`, `sector-turnover`, and `sector-breadth`, performs zero provider I/O, and leaves historical evidence unchanged

### Requirement: Historical sectors evidence is retained
Existing `sectors` snapshots, collection tasks, warnings, checksums, and capability reports SHALL remain readable through administrative audit paths and migrations MUST NOT relabel, delete, or copy them into a new dataset identity.

#### Scenario: New datasets are first collected
- **WHEN** the first successful new sector task is committed
- **THEN** existing `sectors` rows remain unchanged and are not used as authoritative new-dataset rows
