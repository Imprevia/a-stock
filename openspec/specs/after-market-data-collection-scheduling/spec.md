# After-Market Data Collection Scheduling Specification

## Purpose

TBD: Define the scheduling contract for after-market data collection.

## Requirements

### Requirement: Configurable after-market schedule
The system SHALL provide a deployable scheduled collection job that is enabled by default for the market-environment deployment, runs in the `Asia/Shanghai` timezone after the configured settlement boundary on Monday through Friday, and can be disabled, suspended, or assigned a different schedule through deployment configuration.

#### Scenario: Default weekday run
- **WHEN** the deployment uses the default scheduled-collection configuration
- **THEN** Kubernetes schedules one collection job at 16:30 Shanghai time on Monday through Friday

#### Scenario: Scheduled collection is disabled
- **WHEN** an operator disables scheduled collection in Helm configuration
- **THEN** the rendered deployment contains no scheduled-collection CronJob while the dashboard and manual CLI remain available

#### Scenario: Scheduled collection is suspended
- **WHEN** an operator sets the scheduled-collection CronJob to suspended
- **THEN** Kubernetes retains the CronJob definition but does not create new collection Jobs

### Requirement: Complete dataset coverage and failure isolation
Each scheduled run SHALL request `core`, `breadth`, `limits`, `sectors`, and `activeDirection` through the existing collection coordinator, and a failure in one dataset MUST NOT stop, roll back, or invalidate successful sibling datasets.

#### Scenario: All scheduled datasets succeed
- **WHEN** all five scheduled dataset tasks complete successfully
- **THEN** the run finishes as `success`, every snapshot is committed, and the selected date's materialized aggregate is rebuilt from the successful exact-date data

#### Scenario: One scheduled dataset fails
- **WHEN** four scheduled dataset tasks succeed and `sectors` fails
- **THEN** the four successful snapshots remain committed, the `sectors` attempt is recorded as failed or retained, and the parent run finishes as `partial`

#### Scenario: Every scheduled dataset fails
- **WHEN** none of the five scheduled dataset tasks can produce or retain a valid exact-date result
- **THEN** the parent run finishes as `failed` and no previously successful snapshot is deleted or overwritten

### Requirement: Scheduled date and settlement safety
The scheduled CLI SHALL resolve its target date and time in `Asia/Shanghai`, SHALL refuse provider collection before the configured settlement boundary, and MUST preserve the existing exact-date and provider date-capability rules.

#### Scenario: Scheduled command runs after settlement
- **WHEN** the scheduled command starts on a weekday after the configured settlement time
- **THEN** it targets the current Shanghai market date and starts the five independent dataset tasks

#### Scenario: Scheduled command runs before settlement
- **WHEN** the scheduled command starts before the configured settlement time
- **THEN** it rejects the run before provider collection and returns a structured boundary error

#### Scenario: Weekend invocation
- **WHEN** the scheduled command is invoked on Saturday or Sunday
- **THEN** it returns a structured `skipped` result, performs no provider calls, and exits successfully

#### Scenario: Exchange holiday or unverified current-date data
- **WHEN** a weekday is not a trading session or a provider cannot prove that its result belongs to the current Shanghai date
- **THEN** the affected task records `failed-retained` or `failed-missing` and the system does not store another date's data under the scheduled date

### Requirement: Overlap and duplicate protection
The scheduled deployment SHALL prevent overlapping Jobs from the same CronJob, and the collection coordinator SHALL remain the authoritative duplicate-call guard for scheduled, CLI, and HTTP triggers that target the same dataset and date.

#### Scenario: Previous scheduled Job is still running
- **WHEN** the next CronJob time arrives while the previous scheduled Job is active
- **THEN** Kubernetes does not start a second scheduled Job for that CronJob

#### Scenario: Manual and scheduled collection overlap
- **WHEN** a manual trigger and the scheduled Job request the same dataset and exact date concurrently
- **THEN** one task holds the existing dataset/date lease and the other request reuses or reports the active task without issuing a duplicate provider call

#### Scenario: Scheduled Pod terminates unexpectedly
- **WHEN** a scheduled Pod exits while a task is recorded as collecting
- **THEN** the existing lease expiry and recovery rules make the task retryable rather than leaving it permanently active

### Requirement: Persistent and visible scheduled results
Scheduled collection SHALL write collection runs, dataset tasks, successful snapshots, warnings, and materialized aggregates to the same SQLite store used by the dashboard, and the existing `/data-collection` status path SHALL expose those results without provider calls.

#### Scenario: Scheduled run completes before page access
- **WHEN** a user opens `/data-collection` after a scheduled run completes
- **THEN** the page displays the exact-date availability and latest attempt for every scheduled dataset from local SQLite state

#### Scenario: Scheduled run is partial
- **WHEN** a scheduled run finishes as `partial`
- **THEN** the page distinguishes successful, failed-retained, and failed-missing datasets and allows the existing row-level retry action for failed datasets

#### Scenario: Dashboard reads while scheduled collection runs
- **WHEN** the dashboard reads the selected date during an active scheduled collection
- **THEN** it continues returning the latest local aggregate or snapshots without waiting for provider work or starting another collection

### Requirement: Structured scheduled-run outcome
The scheduled CLI SHALL emit a structured result containing the trigger, run identifier when created, target date, parent status, and each dataset task's status, source, observations, duration, and warning, and SHALL use exit codes that distinguish success or skip from partial, failed, and rejected runs.

#### Scenario: Successful scheduled run output
- **WHEN** a scheduled run finishes as `success`
- **THEN** the CLI emits a complete JSON result and exits with code 0

#### Scenario: Partial scheduled run output
- **WHEN** at least one dataset succeeds and at least one dataset fails
- **THEN** the CLI emits every task result, reports parent status `partial`, and exits nonzero without discarding successful data

#### Scenario: Automatic retry after partial result
- **WHEN** the CronJob process exits nonzero because a run is `partial`
- **THEN** the deployment does not automatically rerun the complete five-dataset batch and leaves targeted recovery to the existing retry action or explicit CLI

### Requirement: Deployment storage and security parity
The scheduled Job SHALL use the same immutable application image configuration, snapshot PVC path, market timezone, provider environment, non-root identity, read-only root filesystem, temporary-volume boundary, and restricted container security posture as the dashboard deployment.

#### Scenario: Scheduled Job writes a snapshot
- **WHEN** a scheduled dataset task commits a successful result
- **THEN** the dashboard process can read that result from the shared configured SQLite path without copying or synchronizing a second database

#### Scenario: Scheduled manifest is rendered
- **WHEN** Kustomize or Helm renders an enabled scheduled-collection deployment
- **THEN** the CronJob has no service-account token, runs as non-root, drops Linux capabilities, mounts the configured data PVC and `/tmp`, and defines bounded execution and Job history settings

#### Scenario: Multi-node deployment is requested
- **WHEN** an operator attempts to use the scheduled design with multiple dashboard replicas or a storage backend that does not satisfy the existing single-node SQLite boundary
- **THEN** the deployment documentation identifies that topology as unsupported until a shared coordination and storage design is implemented
