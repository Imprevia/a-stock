## Purpose

Provide a fail-closed operator boundary for validating and promoting one reviewed, redacted provider capability report into the runtime repository without collecting market data or exposing credentials.

## ADDED Requirements

### Requirement: Capability promotion is dry-run by default
The system SHALL expose a capability-report promotion command that selects exactly one report by provider, dataset, and revision, validates it, and performs no persistent write unless the operator supplies an explicit apply flag.

#### Scenario: Valid report is inspected without apply
- **WHEN** an operator invokes capability promotion with a valid report and omits the apply flag
- **THEN** the command reports the selected identity, status, checksum, target backend, and conflict state without changing the capability repository

#### Scenario: Input contains several reports
- **WHEN** the input is a provider-probe envelope containing reports for several datasets
- **THEN** the command selects only the report matching the explicit provider, dataset, and revision and does not promote any sibling report

### Requirement: Production promotion runs inside the reviewed disabled runtime
The system SHALL provide a controlled production promotion path that first proves exactly one
Ready application Pod is running the reviewed staged image with Fuyao sectors disabled, streams
the reviewed JSON envelope to the CLI over stdin, and relies only on the Pod's existing runtime
PostgreSQL Secret environment. The path MUST NOT print or copy database credentials, persist the
report inside the container, enable a provider, or invoke a provider.

#### Scenario: Reviewed report is dry-run inside the staged Pod
- **WHEN** an operator selects dry-run after the sectors-off image staging gate passes
- **THEN** the report is streamed over stdin to the Pod, the masked target and single-report plan are returned, and neither the report nor database credentials are written to the Pod filesystem

#### Scenario: Runtime identity or disabled gate is not proven
- **WHEN** the Pod is not Ready, more than one candidate Pod exists, its image differs from the frozen staged image, Fuyao sectors is enabled, or either application CronJob exists
- **THEN** production promotion is rejected before `kubectl exec` starts the CLI

#### Scenario: File input remains available outside the controlled production path
- **WHEN** an operator runs the CLI in an isolated local environment with a report file path
- **THEN** the command retains its existing file-input behavior without weakening the stdin or production wrapper checks

### Requirement: Promoted reports are complete, eligible, and redacted
The system MUST reject a report unless its checksum is valid, its provider/dataset/revision exactly match the requested identity, its status is `eligible`, its evidence is structurally complete, and applying the standard redaction policy would not alter the supplied report.

#### Scenario: Report identity or checksum differs
- **WHEN** the selected report has a mismatched provider, dataset, revision, or checksum
- **THEN** promotion fails before opening a write transaction and no capability row changes

#### Scenario: Report contains sensitive material
- **WHEN** the supplied report contains a token, API key, authorization value, cookie, password, credential, or another value removed by the standard redaction policy
- **THEN** promotion fails without echoing the sensitive value or writing the report

#### Scenario: Report is not eligible
- **WHEN** the selected report is `ineligible` or `unverified`, has no observations, or lacks required endpoint, date, field, permission, or rate-limit evidence
- **THEN** promotion fails and the existing capability repository remains unchanged

### Requirement: Promotion enforces a dataset-specific evidence policy
The system MUST apply a registered evidence policy for the selected provider, dataset, and
revision. For `fuyao/sectors/fuyao-market-v2`, the policy MUST require the three official
endpoints, matching envelope/requested/calendar/snapshot dates, 320 unique catalog rows,
320 unique snapshot rows with complete coverage, same-day batch timestamps, complete
code/name/changePct/amount coverage, explicit missing evidence for mainNet/mainNetPct/upCount/
downCount/leader, configured permission, and a positive bounded request budget. Unknown
policies and the legacy v1 revision MUST fail closed.

#### Scenario: Fuyao v2 evidence satisfies the frozen contract
- **WHEN** a checksum-valid eligible report proves one requested Shanghai trading date, 320/320 unique catalog-to-snapshot coverage, complete supported-field coverage, explicit five-field absence, configured permission, and `0 < requestsUsed <= requestBudget`
- **THEN** promotion validation succeeds and dry-run or explicit apply may proceed

#### Scenario: Fuyao v2 evidence is stale, partial, or legacy
- **WHEN** a report has mixed dates, fewer than 320 rows, incomplete coverage, missing field/permission/rate-limit evidence, a zero/unbounded request budget, claims unsupported fields as populated, or uses `fuyao-market-v1`
- **THEN** promotion is rejected before any repository write

### Requirement: Apply writes one report transactionally
The system SHALL use the configured runtime repository transaction to persist only the validated report when apply is explicit, SHALL treat an identical existing checksum as idempotent, and MUST reject an existing identity with different evidence.

#### Scenario: Eligible report is applied
- **WHEN** an operator applies a validated report to the configured PostgreSQL runtime repository
- **THEN** exactly one capability row is committed and the command returns its provider, dataset, revision, status, and checksum

#### Scenario: Identical report already exists
- **WHEN** the same provider/dataset/revision and checksum already exist
- **THEN** the command succeeds idempotently without changing unrelated rows

#### Scenario: Revision identity has different evidence
- **WHEN** the repository already contains the same provider/dataset/revision with a different checksum
- **THEN** the transaction is rejected and neither report is overwritten

### Requirement: Capability promotion has no market-data side effects
The promotion command MUST NOT call a provider, create a collection run, write a market snapshot, rebuild an aggregate, alter scheduling, change a Secret, or modify any provider enabled/approved-revision setting.

#### Scenario: Report is promoted while providers are unavailable
- **WHEN** a valid reviewed report is applied while every market provider is unreachable
- **THEN** the capability write can complete without any provider request or market snapshot mutation
