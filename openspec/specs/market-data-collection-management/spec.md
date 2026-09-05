# market-data-collection-management Specification

## Purpose
Provide exact-date visibility and controlled manual collection for the five market-environment datasets while preserving independent task results, local snapshot integrity, and provider-free status reads.

## Requirements

### Requirement: Collection management status
The system SHALL provide a data-collection status view for an exact selected date covering `core`, `breadth`, `limits`, `sectors`, and `activeDirection`, without calling an external provider while reading the status.

#### Scenario: Status view distinguishes availability from the latest attempt
- **WHEN** a dataset has a successful exact-date snapshot but its latest collection attempt failed
- **THEN** the status reports the data as available from the retained snapshot and separately reports the latest attempt as failed with its warning

#### Scenario: Status view works when market providers are unavailable
- **WHEN** every external market provider is unavailable
- **THEN** the collection management page still loads stored status, task history, and retry controls from local state

### Requirement: Independent dataset collection tasks
The system SHALL execute `core`, `breadth`, `limits`, `sectors`, and `activeDirection` as independent collection tasks within a parent collection run, and a task failure MUST NOT stop, roll back, or invalidate successful sibling tasks.

#### Scenario: One dataset fails in a full collection run
- **WHEN** a full collection run succeeds for four datasets and fails for `sectors`
- **THEN** the four successful snapshots are committed, the `sectors` failure is recorded, and the parent run finishes as `partial`

#### Scenario: Every dataset fails
- **WHEN** all five dataset tasks fail without producing a successful result
- **THEN** the parent run finishes as `failed` and no previously successful snapshot is removed

#### Scenario: Every dataset succeeds
- **WHEN** all five dataset tasks complete successfully
- **THEN** the parent run finishes as `success` and reports the result of every dataset task

### Requirement: Single-dataset and full collection actions
The system SHALL provide a retry action for each dataset and one full collection action that targets all five datasets for the selected date.

#### Scenario: Retry one failed dataset
- **WHEN** a user invokes the retry action for `breadth`
- **THEN** the system creates or reuses a collection run containing only the `breadth` task and does not recollect unrelated datasets

#### Scenario: Collect all datasets
- **WHEN** a user invokes the full collection action
- **THEN** the system creates tasks for `core`, `breadth`, `limits`, `sectors`, and `activeDirection` and continues processing after any individual task failure

#### Scenario: Duplicate collection request
- **WHEN** a collection task already holds the lease for the same dataset and exact date and another matching request arrives
- **THEN** the system returns or references the active task as `busy` or in progress and issues no duplicate provider call

### Requirement: Successful snapshot retention
The system SHALL store successful exact-date snapshots separately from collection-attempt results, and a failed attempt MUST NOT overwrite the last successful snapshot for the same dataset and date.

#### Scenario: Failed refresh retains same-date data
- **WHEN** a dataset refresh fails and a successful snapshot already exists for the same date
- **THEN** the system retains the prior values, records the new failure and warning, and exposes the attempt state as `failed-retained`

#### Scenario: Failed refresh has no retained data
- **WHEN** a dataset refresh fails and no successful snapshot exists for that date
- **THEN** the system reports `failed-missing` and preserves the existing missing or insufficient value semantics

#### Scenario: Cross-date fallback is rejected
- **WHEN** collection fails for a selected date but a successful snapshot exists for another date
- **THEN** the system does not use the other date as retained data for the selected date

### Requirement: Core index failure isolation
The system SHALL collect and report the five configured core indices as independently evaluated sub-results within the `core` dataset.

#### Scenario: One core index fails
- **WHEN** four configured indices collect successfully and one index fails
- **THEN** the `core` task finishes as `partial`, preserves the four successful index results, and exposes the failed index and warning

#### Scenario: Failed index retains an exact-date value
- **WHEN** one index fails but the same date has a prior successful result for that index
- **THEN** the new core snapshot retains that index value with `failed-retained` metadata rather than removing it

#### Scenario: No core index is available
- **WHEN** all five indices fail and no same-date index result can be retained
- **THEN** the `core` task finishes as `failed` and no invalid core aggregate is published

### Requirement: Materialized market-environment aggregate
The system SHALL rebuild and validate the selected date's materialized market-environment response after each successful dataset commit, using the latest successful exact-date result for every dataset.

#### Scenario: Successful dataset updates the aggregate
- **WHEN** a dataset task commits a new successful exact-date snapshot
- **THEN** the system rebuilds the aggregate, validates it against the API response contract, and atomically replaces the previous materialized aggregate

#### Scenario: Aggregate contains incomplete evidence
- **WHEN** one or more datasets have no successful exact-date snapshot
- **THEN** the aggregate remains available when core data is usable, marks coverage as partial or degraded, and keeps unavailable evidence missing or insufficient

#### Scenario: Failed task does not remove aggregate evidence
- **WHEN** a task fails while the materialized aggregate already references a same-date successful snapshot for that dataset
- **THEN** the aggregate continues serving the retained evidence and exposes the latest refresh warning

### Requirement: Asynchronous collection API
The system SHALL expose asynchronous collection-run APIs that return without waiting for provider collection and allow clients to read run and task progress.

#### Scenario: Start a collection run
- **WHEN** an enabled client submits a valid collection request
- **THEN** the API returns HTTP 202 with a run identifier, selected date, requested datasets, and initial status before provider collection completes

#### Scenario: Poll collection progress
- **WHEN** a client requests an existing collection run by identifier
- **THEN** the API returns the parent status and each task's status, source, observations, duration, timestamps, and warning without calling a provider

#### Scenario: Service restarts during collection
- **WHEN** the service restarts while a task is recorded as collecting
- **THEN** the task becomes retryable after its lease expires and is not reported as permanently active

### Requirement: Collection page interaction
The system SHALL provide a dedicated `/data-collection` management page with a selected-date control, status refresh action, full collection action, and one retry action per dataset.

#### Scenario: Collection remains visible while work runs
- **WHEN** one or more collection tasks are running
- **THEN** the page retains the existing status table, shows progress and affected-row loading states, and does not replace the page with a blocking full-screen loader

#### Scenario: Partial run completes
- **WHEN** a full collection run finishes as `partial`
- **THEN** the page shows which datasets succeeded, which failed or retained old data, and enables retry for the failed datasets

#### Scenario: Core details are inspected
- **WHEN** the user expands the core dataset row
- **THEN** the page shows the individual state, source, duration, and warning for each of the five configured indices

#### Scenario: Mobile collection management
- **WHEN** the page is displayed at a 390-pixel viewport width
- **THEN** all dataset statuses and actions remain readable and usable without page-level horizontal overflow or overlapping controls

### Requirement: Date-capability enforcement
The system SHALL validate collection requests against each provider's date capability and MUST NOT label a latest-only market snapshot as data for an unverified historical date.

#### Scenario: Historical supported dataset is collected
- **WHEN** a historical date is selected and the user retries `core` or `limits`
- **THEN** the system permits the request when the underlying providers support and validate that date

#### Scenario: Historical latest-only dataset is rejected
- **WHEN** a historical date is selected and `breadth`, `sectors`, or `activeDirection` cannot prove that their latest snapshot belongs to that date
- **THEN** the action is disabled in the page and the API rejects the request with an explanatory validation response

#### Scenario: Intraday collection is provisional
- **WHEN** the current market date is collected before the configured settlement boundary
- **THEN** successful results are marked provisional rather than settled

### Requirement: Manual collection access boundary
The system SHALL keep manual collection write operations enabled by default for local development and SHALL allow operators to disable them with an explicit server-side configuration switch. A deployment without application-level authentication MUST NOT expose enabled collection write operations through an anonymously reachable network endpoint. Such a deployment MAY enable manual collection only when the application endpoint is reachable exclusively through an independently authenticated and authorized operator channel.

#### Scenario: Manual collection is enabled by default
- **WHEN** `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` is not configured and the request passes date validation
- **THEN** the client can start collection runs and the server accepts the controlled POST request

#### Scenario: Manual collection is explicitly disabled
- **WHEN** `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` is set to a disabled value
- **THEN** the page hides or disables collection actions and the API rejects collection POST requests without starting provider work

#### Scenario: Manual collection is explicitly enabled
- **WHEN** the configuration switch is enabled and the request passes date validation
- **THEN** the client can start collection runs and the server permits the required controlled POST request

#### Scenario: Protected operator channel enables manual collection
- **WHEN** the deployment has no application-level authentication, the configuration switch is enabled, and the application Service is reachable only through an authenticated operator channel bound to the operator's loopback interface
- **THEN** an authorized operator can start a date-valid collection run without exposing the write endpoint to anonymous LAN clients

#### Scenario: Anonymous NodePort remains prohibited
- **WHEN** the application has no application-level authentication and a NodePort or equivalent anonymous network endpoint is reachable
- **THEN** manual collection remains explicitly disabled regardless of CORS configuration or whether the client displays collection buttons

#### Scenario: Operator tunnel closes
- **WHEN** the authenticated port-forward or SSH tunnel ends
- **THEN** the operator endpoint is no longer listening and no persistent anonymous write path remains

### Requirement: Manual collection deployment preserves data and runtime invariants
Enabling or disabling manual collection in an existing deployment SHALL preserve the configured snapshot PVC, SQLite path, single-replica boundary, provider controls, date-capability validation, and failure-retention behavior.

#### Scenario: Helm configuration is rendered before deployment
- **WHEN** an operator prepares the environment values that enable protected manual collection
- **THEN** the rendered resources contain one explicit manual-refresh environment variable, a ClusterIP Service without a nodePort, the existing PVC claim and snapshot path, one Dashboard replica, and no unintended Ingress or scheduled collection resource

#### Scenario: Existing PVC is reused
- **WHEN** the Helm release is upgraded to enable protected manual collection
- **THEN** the existing claim remains mounted at the same path and historical snapshots and collection records remain readable without a schema migration

#### Scenario: A provider fails during a manual run
- **WHEN** one or more provider calls fail, are rate limited, or return insufficient evidence
- **THEN** each dataset retains its independent terminal state, an existing successful same-date snapshot is not overwritten, and missing evidence remains degraded or insufficient rather than being replaced with zero

#### Scenario: A duplicate dataset/date request is made
- **WHEN** an authorized operator repeats a collection request for a dataset and date that already has an active lease
- **THEN** the existing lease and provider serialization rules prevent an uncontrolled duplicate provider call

### Requirement: Manual collection deployment is reversible
The deployment SHALL provide a configuration-first rollback that blocks new collection writes before any anonymous network exposure is restored, and rollback MUST NOT delete the snapshot PVC.

#### Scenario: Manual collection is disabled during rollback
- **WHEN** an operator sets `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` to a disabled value and rolls out the configuration
- **THEN** collection POST returns 403 without starting provider work while health and local snapshot reads remain available

#### Scenario: Previous service exposure is restored
- **WHEN** an operator needs to restore the previous NodePort release
- **THEN** the manual collection switch is verified disabled before NodePort reachability is restored

#### Scenario: Helm release is rolled back
- **WHEN** the operator rolls back to the recorded previous revision
- **THEN** the Deployment and Service return to the reviewed revision while the existing PVC, snapshots, and collection history are retained

### Requirement: Read-path isolation and compatibility
The system SHALL preserve existing market-environment query paths and existing response fields while ensuring normal dashboard reads do not start collection tasks.

#### Scenario: Dashboard reads during collection
- **WHEN** a collection run is active and the dashboard requests the selected date
- **THEN** the dashboard receives the latest locally materialized response without waiting for the active provider tasks

#### Scenario: Warm local dashboard read
- **WHEN** the selected date has a materialized aggregate or required snapshots
- **THEN** the query performs zero external provider calls and completes within 500 milliseconds in the local verification environment

#### Scenario: Existing consumer ignores collection metadata
- **WHEN** a consumer uses only the response fields available before this change
- **THEN** the existing market-environment response remains valid without requiring that consumer to use collection-management APIs
