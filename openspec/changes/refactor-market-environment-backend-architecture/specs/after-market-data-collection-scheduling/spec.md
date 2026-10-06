## MODIFIED Requirements

### Requirement: Configurable after-market schedule
The system SHALL provide a deployable scheduled collection job whose deployment defaults are fail-closed with `enabled=false` and `suspend=true`. When an operator explicitly enables and activates the reviewed schedule, the job SHALL run in the `Asia/Shanghai` business timezone after the configured settlement boundary on Monday through Friday, and deployment configuration SHALL continue to support disabling, suspending, or assigning a reviewed schedule.

#### Scenario: Default deployment is fail-closed
- **WHEN** the deployment uses the repository's default scheduled-collection configuration
- **THEN** the rendered deployment contains no scheduled-collection CronJob and cannot create provider-backed collection Jobs

#### Scenario: Scheduled collection is suspended
- **WHEN** an operator explicitly enables scheduled collection while retaining `suspend=true`
- **THEN** Kubernetes retains the reviewed CronJob definition but does not create new collection Jobs

#### Scenario: Default weekday run
- **WHEN** an operator completes the required schedule review and explicitly activates the enabled CronJob with `suspend=false`
- **THEN** Kubernetes schedules one collection job at the reviewed time corresponding to 16:30 Shanghai time on Monday through Friday

#### Scenario: Scheduled collection is disabled
- **WHEN** an operator disables scheduled collection in Helm configuration
- **THEN** the rendered deployment contains no scheduled-collection CronJob while the dashboard and manual CLI remain available

### Requirement: Persistent and visible scheduled results
Scheduled collection SHALL write collection runs, dataset tasks, successful snapshots, warnings, leases, and materialized aggregates to the same configured PostgreSQL runtime database used by the dashboard, and the existing `/data-collection` status path SHALL expose those results without provider calls.

#### Scenario: Scheduled run completes before page access
- **WHEN** a user opens `/data-collection` after a scheduled run completes
- **THEN** the page displays the exact-date availability and latest attempt for every scheduled dataset from PostgreSQL state without calling a provider

#### Scenario: Scheduled run is partial
- **WHEN** a scheduled run finishes as `partial`
- **THEN** the page distinguishes successful, failed-retained, and failed-missing datasets and allows the existing row-level retry action for failed datasets

#### Scenario: Dashboard reads while scheduled collection runs
- **WHEN** the dashboard reads the selected date during an active scheduled collection
- **THEN** it continues returning the latest local aggregate or snapshots without waiting for provider work or starting another collection

### Requirement: Deployment storage and security parity
The scheduled Job SHALL use the same immutable application image configuration, PostgreSQL Service and Secret contract, market timezone, provider environment, non-root identity, read-only root filesystem, temporary-volume boundary, and restricted container security posture as the dashboard deployment. The scheduled Job and dashboard SHALL NOT mount or create an application SQLite database PVC; PostgreSQL SHALL remain the only runtime component that owns the retained database PVC.

#### Scenario: Scheduled Job writes a snapshot
- **WHEN** a scheduled dataset task commits a successful result through the configured PostgreSQL connection
- **THEN** the dashboard process can read that result from the same PostgreSQL database without copying files or synchronizing a second database

#### Scenario: Scheduled manifest is rendered
- **WHEN** Kustomize or Helm renders an explicitly enabled scheduled-collection deployment
- **THEN** the CronJob has no service-account token, runs as non-root, drops Linux capabilities, receives the reviewed PostgreSQL connection through a Secret, mounts only approved temporary or auxiliary volumes, and defines bounded execution and Job history settings

#### Scenario: SQLite migration input is present
- **WHEN** an operator performs an explicitly reviewed one-time SQLite-to-PostgreSQL migration
- **THEN** the SQLite file is treated only as a stopped, read-only migration input and is not configured as a runtime fallback for the dashboard or scheduled Job

#### Scenario: Multi-node deployment is requested
- **WHEN** an operator attempts to run multiple dashboard or collection workers beyond the documented single-process and single-main PostgreSQL boundary
- **THEN** the deployment documentation identifies that topology as unsupported until shared provider limiting, database high availability, and coordination behavior are explicitly designed and verified
