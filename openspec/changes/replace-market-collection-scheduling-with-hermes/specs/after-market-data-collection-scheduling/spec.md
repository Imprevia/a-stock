## MODIFIED Requirements

### Requirement: Configurable after-market schedule
The repository SHALL NOT render, install, suspend, or activate an application-owned market-data CronJob. The reviewed after-market schedule SHALL instead be owned by Hermes Agent on `192.168.1.21`, use an explicitly verified `Asia/Shanghai` timezone, and invoke the backend full-collection automation endpoint at `http://192.168.1.20:32001` at 16:30 Monday through Friday. Missing the scheduled slot MAY be recovered only within 30 minutes; a later catch-up SHALL be skipped and reported.

#### Scenario: Default deployment is fail-closed
- **WHEN** any supported Helm or Kustomize deployment configuration is rendered
- **THEN** it contains no market-data CronJob and exposes no values or deployment mode capable of activating one

#### Scenario: Scheduled collection is suspended
- **WHEN** an operator pauses the Hermes job while leaving its reviewed definition installed
- **THEN** Hermes creates no new collection run and the backend automation endpoint remains independently controllable

#### Scenario: Default weekday run
- **WHEN** Hermes reaches 16:30 on Monday through Friday in its explicitly configured `Asia/Shanghai` timezone
- **THEN** it invokes the enabled full-collection automation endpoint once with a stable idempotency key for that schedule slot

#### Scenario: Hermes gateway is unavailable at the schedule time
- **WHEN** the missed execution is discovered no more than 30 minutes after 16:30 Shanghai time
- **THEN** Hermes may invoke the same schedule-slot idempotency key once and report the recovered execution

#### Scenario: Catch-up deadline has elapsed
- **WHEN** the missed execution is discovered more than 30 minutes after 16:30 Shanghai time
- **THEN** no provider-backed collection is started for that schedule slot and the missed run is reported to the configured delivery target

#### Scenario: Scheduled collection is disabled
- **WHEN** the Hermes job is paused or removed, or the backend automation switch is disabled
- **THEN** no new scheduled collection run is created while local status reads and explicit maintenance commands remain available

### Requirement: Complete dataset coverage and failure isolation
Each Hermes-triggered run SHALL request `core`, `breadth`, `limits`, `industry-ranking`, `sector-turnover`, `sector-breadth`, and `activeDirection` through the full-collection automation endpoint, and a failure in one dataset MUST NOT stop, roll back, or invalidate unrelated successful sibling datasets.

#### Scenario: All scheduled datasets succeed
- **WHEN** all seven tasks complete successfully
- **THEN** the run finishes as `success`, every successful snapshot is committed, and the exact-date materialized aggregate is rebuilt

#### Scenario: One scheduled dataset fails
- **WHEN** one task fails and at least one unrelated task succeeds or produces an accepted partial result
- **THEN** the successful evidence remains committed, the failed task preserves its exact failure or retention state, and the parent run finishes as `partial`

#### Scenario: THS dependency fails
- **WHEN** a THS prerequisite cannot produce compatible same-date evidence
- **THEN** its dependent THS tasks report `blocked`, unrelated datasets continue, and Hermes includes all states in the notification

#### Scenario: Every scheduled dataset fails
- **WHEN** none of the seven tasks can produce or retain a usable exact-date result
- **THEN** the parent run finishes as `failed` and no previous successful snapshot is deleted or overwritten

### Requirement: Scheduled date and settlement safety
The full-collection automation endpoint SHALL resolve its target date and time in `Asia/Shanghai`, SHALL reject provider collection before the configured settlement boundary, and MUST preserve exact-date and provider date-capability rules. Hermes MUST NOT override the server-selected date.

#### Scenario: Scheduled command runs after settlement
- **WHEN** Hermes invokes the endpoint on a weekday after the configured settlement time and within the allowed schedule window
- **THEN** the server targets the current effective Shanghai market date and starts the seven tasks

#### Scenario: Scheduled command runs before settlement
- **WHEN** Hermes invokes the endpoint before the configured settlement time
- **THEN** the server rejects it before run creation and provider collection and Hermes reports the rejection without changing the date

#### Scenario: Weekend invocation
- **WHEN** the endpoint is invoked on Saturday or Sunday in `Asia/Shanghai`
- **THEN** it returns a structured `skipped` result, performs no provider calls, and Hermes reports the skip without retrying the batch

#### Scenario: Exchange holiday or unverified current-date data
- **WHEN** a weekday is not a trading session or a provider cannot prove that its result belongs to the server-selected date
- **THEN** affected tasks record their true failed-retained, failed-missing, blocked, or insufficient evidence and no other date is stored under the selected date

### Requirement: Overlap and duplicate protection
Hermes SHALL use one stable idempotency key per scheduled slot, the backend SHALL persistently reuse the run for matching replays, and the collection coordinator SHALL remain the final dataset/date lease guard for other HTTP or maintenance triggers.

#### Scenario: Hermes retries after losing the response
- **WHEN** Hermes retries the POST because the response was lost or timed out
- **THEN** it reuses the same idempotency key and receives the original run without duplicate tasks or provider calls

#### Scenario: Previous scheduled Job is still running
- **WHEN** the synchronous wait returns HTTP 202
- **THEN** Hermes follows the returned provider-free status URL and does not issue another POST for that schedule slot

#### Scenario: Manual and scheduled collection overlap
- **WHEN** an explicit maintenance trigger and the Hermes-triggered run target the same dataset and exact date concurrently using different parent requests
- **THEN** one task holds the dataset/date lease and the other reports `busy` without issuing a duplicate provider call

#### Scenario: Scheduled Pod terminates unexpectedly
- **WHEN** the service stops while a task is collecting
- **THEN** persisted idempotency, task recovery, and lease expiry make the original run recoverable rather than creating an unbounded duplicate or leaving it permanently active

### Requirement: Persistent and visible scheduled results
Hermes-triggered collection SHALL write collection runs, idempotency bindings, dataset tasks, structured failures, successful snapshots, warnings, leases, and materialized aggregates to the configured PostgreSQL runtime database, and existing provider-free status paths SHALL expose those results.

#### Scenario: Scheduled run completes before page access
- **WHEN** a user opens `/data-collection` after a Hermes-triggered run completes
- **THEN** the page displays exact-date availability and latest attempt for every canonical dataset without calling a provider

#### Scenario: Scheduled run is partial
- **WHEN** a Hermes-triggered run finishes as `partial`
- **THEN** stored results distinguish success, partial, failed-retained, failed-missing, blocked, and busy states and keep successful siblings available

#### Scenario: Dashboard reads while scheduled collection runs
- **WHEN** the dashboard reads the selected date during an active Hermes-triggered run
- **THEN** it continues returning the latest local aggregate or snapshots without waiting for provider work or starting another collection

### Requirement: Structured scheduled-run outcome
The full-collection endpoint SHALL return a structured run containing the run identifier when created, server-selected target date, parent status, status URL, and every dataset task's status, source, observations, duration, warning, and classified failure. Hermes SHALL deliver a concise Chinese summary for terminal, still-running, skipped, rejected, and unreachable outcomes without converting partial or retained failures into success.

#### Scenario: Successful scheduled run output
- **WHEN** a run finishes as `success`
- **THEN** Hermes reports all seven successful dataset results with the run identifier and target date

#### Scenario: Partial scheduled run output
- **WHEN** at least one dataset succeeds or produces an accepted partial result and another fails, is retained, blocked, or busy
- **THEN** Hermes reports the parent as `partial` and lists every non-success state with its safe reason

#### Scenario: Automatic retry after partial result
- **WHEN** a Hermes-triggered run reaches terminal status `partial`
- **THEN** neither Hermes nor the backend automatically reruns the complete batch and targeted recovery requires a separate explicit action and key

#### Scenario: Scheduled run is still active after Hermes wait budget
- **WHEN** the backend and subsequent bounded polling do not reach a terminal state before the Hermes execution deadline
- **THEN** Hermes reports `still running` with the run identifier and does not start another batch

#### Scenario: Backend is unreachable
- **WHEN** `192.168.1.21` cannot reach `http://192.168.1.20:32001`
- **THEN** Hermes reports an endpoint failure, does not call providers or a local CLI as a fallback, and does not mislabel the condition as a dataset failure

### Requirement: Deployment storage and security parity
Hermes SHALL access the application only through the reviewed internal HTTP endpoint and SHALL NOT receive PostgreSQL credentials, mount application storage, call market providers directly, or execute deployment commands. The backend SHALL preserve the existing PostgreSQL, snapshot, provider policy, non-root application workload, and single-process coordination boundaries. The credential-free automation endpoint SHALL be default-disabled and its accepted security boundary SHALL be documented as all hosts able to route to `192.168.1.20:32001`.

#### Scenario: Scheduled Job writes a snapshot
- **WHEN** a dataset commits through the backend's configured PostgreSQL connection
- **THEN** the dashboard can read it from the same database without Hermes copying files or receiving database access

#### Scenario: Scheduled manifest is rendered
- **WHEN** Helm or Kustomize renders the application deployment
- **THEN** it contains no scheduled collection workload and preserves the reviewed application and PostgreSQL security contexts and storage ownership

#### Scenario: SQLite migration input is present
- **WHEN** an operator performs an explicitly reviewed one-time SQLite-to-PostgreSQL migration
- **THEN** the SQLite file remains a stopped, read-only migration input and is not made available to Hermes or configured as a runtime fallback

#### Scenario: Legacy scheduled resource is discovered
- **WHEN** a normal deployment preflight discovers either the former Helm-owned or legacy market-data CronJob
- **THEN** the deployment fails closed and requires a separately reviewed cleanup rather than ignoring or activating the resource

#### Scenario: Credential-free internal endpoint is enabled
- **WHEN** the operator enables automation collection without application authentication
- **THEN** documentation states that reachability grants invocation ability, the existing manual write endpoint remains disabled, and idempotency is not represented as access control

#### Scenario: Multi-node deployment is requested
- **WHEN** an operator attempts to run multiple application or collection workers beyond the documented coordination boundary
- **THEN** deployment documentation identifies that topology as unsupported until shared provider limiting, database high availability, and coordination behavior are explicitly designed and verified
