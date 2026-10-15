## MODIFIED Requirements

### Requirement: Collection management status
The system SHALL provide a data-collection status view for an exact selected date covering `core`, `breadth`, `limits`, `industry-ranking`, `sector-turnover`, `sector-breadth`, and `activeDirection`, without calling an external provider while reading the status.

#### Scenario: Status view distinguishes availability from the latest attempt
- **WHEN** a dataset has a successful exact-date snapshot but its latest collection attempt failed
- **THEN** the status reports the data as available from the retained snapshot and separately reports the latest attempt as failed with its structured failure and warning

#### Scenario: Status view works when market providers are unavailable
- **WHEN** every external market provider is unavailable
- **THEN** the collection management page still loads stored status, task history, and retry controls from local state

### Requirement: Independent dataset collection tasks
The system SHALL execute `core`, `breadth`, `limits`, `industry-ranking`, `sector-turnover`, `sector-breadth`, and `activeDirection` as independent collection tasks within a parent collection run, SHALL preserve the dependency order `industry-ranking` to `sector-turnover` to `sector-breadth`, and a task failure MUST NOT stop, roll back, or invalidate unrelated successful sibling tasks.

#### Scenario: One dataset fails in a full collection run
- **WHEN** a full collection run succeeds for the independent siblings but one dataset fails
- **THEN** the successful snapshots remain committed, the failed dataset records its exact failure or retention state, and the parent run finishes as `partial`

#### Scenario: THS prerequisite fails
- **WHEN** `industry-ranking` fails with evidence that cannot drive its downstream THS tasks
- **THEN** `sector-turnover` and `sector-breadth` are reported as `blocked`, while unrelated datasets continue and retain their results

#### Scenario: Every dataset fails
- **WHEN** all seven dataset tasks fail without producing or retaining a usable exact-date result
- **THEN** the parent run finishes as `failed` and no previously successful snapshot is removed

#### Scenario: Every dataset succeeds
- **WHEN** all seven dataset tasks complete successfully
- **THEN** the parent run finishes as `success` and reports exactly one result for every canonical dataset

### Requirement: Single-dataset and full collection actions
The system SHALL provide a retry action for each public daily dataset and full collection actions that target the canonical set `core`, `breadth`, `limits`, `industry-ranking`, `sector-turnover`, `sector-breadth`, and `activeDirection`.

#### Scenario: Retry one failed dataset
- **WHEN** a user invokes the retry action for `breadth`
- **THEN** the system creates or reuses a collection run containing only `breadth` and does not recollect unrelated datasets

#### Scenario: Collect all datasets
- **WHEN** an enabled client invokes a full collection action
- **THEN** the system creates exactly one task for each canonical dataset, honors the THS dependency order, and continues processing unrelated tasks after any individual failure

#### Scenario: Duplicate collection request
- **WHEN** a collection task already holds the lease for the same dataset and exact date and another non-idempotent request reaches the coordinator
- **THEN** the system returns or references the active task as `busy` or in progress and issues no duplicate provider call

### Requirement: Manual collection access boundary
The system SHALL keep existing manual collection write operations enabled by default for local development and SHALL allow operators to disable them with an explicit server-side configuration switch. A deployment without application-level authentication MUST NOT expose those existing manual write operations through an anonymously reachable network endpoint. Separately, the sync-first full-collection automation endpoint SHALL have its own default-disabled server-side switch and MAY be explicitly enabled without application credentials only when an operator accepts a trusted, non-public internal network as the security boundary. Enabling automation collection MUST NOT enable the existing manual collection endpoints.

#### Scenario: Manual collection is enabled by default
- **WHEN** `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` is not configured in local development and the request passes date validation
- **THEN** the client can start collection runs and the server accepts the controlled manual POST request

#### Scenario: Manual collection is explicitly disabled
- **WHEN** `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` is set to a disabled value
- **THEN** the page hides or disables manual collection actions and the existing manual collection POST rejects requests without starting provider work

#### Scenario: Manual collection is explicitly enabled
- **WHEN** the manual collection switch is enabled and the request passes date validation
- **THEN** the client can start collection runs and the server permits the required controlled manual POST request

#### Scenario: Protected operator channel enables manual collection
- **WHEN** the deployment has no application-level authentication, the manual collection switch is enabled, and the application Service is reachable only through an authenticated operator channel bound to the operator's loopback interface
- **THEN** an authorized operator can start a date-valid manual collection run without exposing the write endpoint to anonymous LAN clients

#### Scenario: Anonymous NodePort remains prohibited
- **WHEN** the application has no application-level authentication and a NodePort or equivalent anonymous network endpoint is reachable
- **THEN** existing manual collection actions remain explicitly disabled regardless of CORS configuration or whether the client displays collection buttons

#### Scenario: Trusted-LAN automation is explicitly enabled
- **WHEN** the operator enables the dedicated automation switch on the non-public endpoint at `192.168.1.20:32001`
- **THEN** a client with network reachability, including Hermes on `192.168.1.21`, can invoke only the full-collection automation endpoint without credentials while existing manual collection actions remain disabled

#### Scenario: Automation endpoint is disabled
- **WHEN** the dedicated automation switch is unset or disabled
- **THEN** the full-collection automation endpoint rejects the request without creating a run or issuing a provider call

#### Scenario: Internal network reachability is the accepted boundary
- **WHEN** the credential-free automation endpoint is enabled
- **THEN** documentation states that every client able to route to `192.168.1.20:32001` can invoke it and MUST NOT describe idempotency, CORS, the UI, or the dataset lease as authentication

#### Scenario: Operator tunnel closes
- **WHEN** an authenticated port-forward or SSH tunnel used for the existing manual endpoint ends
- **THEN** the operator endpoint is no longer listening and no persistent anonymous manual write path remains

## ADDED Requirements

### Requirement: Sync-first full collection automation API
The system SHALL expose a dedicated full-collection automation POST that accepts no client-selected date or dataset list, resolves the target using `Asia/Shanghai`, always requests the canonical seven datasets, submits work to the bounded background executor, and waits up to a server-bounded request preference without making execution depend on the client connection.

#### Scenario: Full collection finishes within the wait budget
- **WHEN** the persisted run reaches `success`, `partial`, or `failed` before the wait deadline
- **THEN** the endpoint returns HTTP 200 with the terminal run and exactly one task result for each canonical dataset in stable order

#### Scenario: Full collection outlives the wait budget
- **WHEN** the run is still non-terminal at the wait deadline
- **THEN** the endpoint returns HTTP 202 with the current run, `runId`, a provider-free `statusUrl`, `Location`, and `Retry-After`, while background execution continues

#### Scenario: Client disconnects while waiting
- **WHEN** the client connection closes after the run has been created and submitted
- **THEN** the server does not cancel the run, release live task leases prematurely, or start a replacement run

#### Scenario: Parent run finishes as a business failure
- **WHEN** all seven tasks finish without a usable result and the parent status is `failed`
- **THEN** the endpoint returns HTTP 200 with the complete failed business result rather than converting it to an HTTP 5xx transport failure

#### Scenario: Invocation occurs before settlement
- **WHEN** the automation endpoint is called before the configured Shanghai settlement boundary
- **THEN** it rejects the request with HTTP 422 before creating a run or calling a provider

#### Scenario: Invocation occurs on a weekend
- **WHEN** the automation endpoint is called on Saturday or Sunday in `Asia/Shanghai`
- **THEN** it returns a structured `skipped` outcome with no run and performs no provider call

### Requirement: Persistent idempotent full collection trigger
The full-collection automation endpoint SHALL require an `Idempotency-Key`, SHALL atomically bind its endpoint scope and semantic request fingerprint to one persisted run, and SHALL preserve that mapping across process restarts. The fingerprint MUST include the resolved market date, operation version, and canonical dataset set, and MUST exclude the caller's wait timeout preference.

#### Scenario: Concurrent requests reuse one run
- **WHEN** two requests with the same idempotency key and semantic fingerprint arrive concurrently
- **THEN** exactly one parent run and one task per canonical dataset are created, both requests reference that run, and no dataset receives duplicate provider work from the duplicate trigger

#### Scenario: In-progress request is replayed
- **WHEN** the same key and fingerprint are replayed while the run is collecting
- **THEN** the endpoint reuses the existing run and may wait again for the caller's bounded preference without creating or submitting another run

#### Scenario: Terminal request is replayed
- **WHEN** the same key and fingerprint are replayed after the run is terminal
- **THEN** the endpoint returns the persisted terminal result without provider calls

#### Scenario: Key is reused for a different semantic request
- **WHEN** an existing key resolves to a different market date, operation version, or canonical dataset fingerprint
- **THEN** the endpoint returns HTTP 409 with a redaction-safe `idempotency-key-conflict` response that references the original run and status URL without presenting the old result as the new date

#### Scenario: Process stops between run creation and executor submission
- **WHEN** an idempotent run exists but was not successfully submitted before the process stopped or executor capacity rejected submission
- **THEN** replay of the same key recovers or safely terminates and resubmits that same run without creating another parent run or leaving permanent leases

### Requirement: Structured dataset failure results
Every persisted collection task and every collection-run response SHALL expose a redaction-safe nullable `failure` object containing `category`, `message`, and `retryable`, plus `retained` when applicable. Failed, blocked, busy, and worker-interrupted outcomes MUST use stable categories rather than requiring clients to parse warning text.

#### Scenario: Dataset fails and same-date data exists
- **WHEN** acquisition fails but a successful snapshot already exists for that exact date
- **THEN** the task reports `failed-retained`, `retained=true`, and the classified failure while leaving the snapshot intact

#### Scenario: Dataset fails without same-date data
- **WHEN** acquisition fails and no successful snapshot exists for that exact date
- **THEN** the task reports `failed-missing`, `retained=false`, and the classified failure

#### Scenario: Dataset is blocked or busy
- **WHEN** a dependency prevents execution or another task owns the dataset/date lease
- **THEN** the task reports `blocked` with category `dependency` or `busy` with category `concurrency`, including a safe reason and retryability

#### Scenario: Dataset succeeds
- **WHEN** a task reports `success`
- **THEN** its `failure` is null and its source, observations, timings, warnings, and dataset-specific detail remain available

#### Scenario: Structured failure is read later
- **WHEN** a client reads a persisted run or exact-date collection status after the originating process has restarted
- **THEN** the structured failure matches the full-collection response and the read performs no provider call
