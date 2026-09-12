## Purpose

Provide a safe, repeatable deployment contract for the existing TrueNAS k3s cluster so operators can install the shared SQLite storage, Dashboard service, and after-market collection schedule together or as independently verifiable components.

## ADDED Requirements

### Requirement: Component selection and dependency ordering

The TrueNAS k3s deployment entry point SHALL accept an all-components operation and independent `database`, `service`, and `schedule` component operations. The all-components operation SHALL process components in the order database, service, then schedule, and each independent operation SHALL fail before any write when a required prerequisite is absent.

#### Scenario: One-click deployment
- **WHEN** an operator selects the all-components operation with valid TrueNAS and image configuration
- **THEN** the entry point creates or verifies the namespace and SQLite storage, deploys the Dashboard service resources, and finally deploys the scheduled-collection resource in the documented order

#### Scenario: Independent service deployment without storage
- **WHEN** an operator selects the service component and the configured SQLite PVC is absent or not usable
- **THEN** the entry point reports a prerequisite error and does not modify the Deployment, Service, or Ingress

#### Scenario: Independent schedule deployment without service prerequisites
- **WHEN** an operator selects the schedule component and the configured namespace, PVC, or required immutable image is absent
- **THEN** the entry point reports a prerequisite error and does not create or modify the CronJob

### Requirement: SQLite PVC preservation

The database component SHALL represent the existing SQLite store at `/data/snapshots.sqlite3` on the configured `market-environment-data` or reviewed existing claim. It MUST preserve an existing PVC identity and data, MUST be idempotent when the claim already satisfies the requested contract, and MUST NOT create a PostgreSQL workload or delete, replace, or resize the claim implicitly.

#### Scenario: First database deployment
- **WHEN** the namespace exists or can be created and no conflicting claim is present
- **THEN** the entry point creates the reviewed RWO PVC with the configured storage class and capacity and reports the claim name and binding state

#### Scenario: Existing claim is reused
- **WHEN** a claim with the reviewed name is already bound and mounted by the release
- **THEN** the database operation leaves its UID, bound volume, data, and SQLite path unchanged and completes successfully after verification

#### Scenario: Conflicting storage contract
- **WHEN** the existing claim has an incompatible access mode, storage identity, or path contract
- **THEN** the entry point fails closed and requires an explicit reviewed remediation instead of deleting or replacing the claim

### Requirement: Independent Dashboard service deployment

The service component SHALL deploy the Dashboard Deployment, Service, and configured Ingress using the reviewed immutable image, one-replica SQLite topology, health probes, and non-root restricted security posture. It SHALL retain compatibility with the existing TrueNAS values, including NodePort or ClusterIP exposure and an existing PVC claim.

#### Scenario: Service component succeeds
- **WHEN** the configured image is available in the target k3s container runtime and the reviewed PVC is bound
- **THEN** the entry point applies the Dashboard service resources, waits for the single Deployment to become ready, and verifies `/api/health` through the configured internal endpoint

#### Scenario: Service rollout fails
- **WHEN** the Deployment does not become ready within the configured timeout or the health check fails
- **THEN** the entry point exits nonzero, reports the failing postcondition, and does not claim that the service component was deployed successfully

#### Scenario: Service-only update preserves storage
- **WHEN** an operator reruns the service component with a new immutable image tag
- **THEN** the Deployment rolls to the new image while the existing PVC UID, SQLite path, replica count, and security constraints remain unchanged

### Requirement: Safe scheduled-collection component

The schedule component SHALL deploy the existing `scheduled-refresh` CronJob using the same image, PVC, timezone, environment, and restricted security settings as the Dashboard. The component operation SHALL default to a suspended CronJob or no CronJob according to the reviewed baseline, and SHALL NOT activate production scheduling by boolean configuration alone; activation MUST continue through the existing reviewed Gate B/Gate C workflow.

#### Scenario: Schedule component is deployed safely
- **WHEN** an operator selects the schedule component with valid service and storage prerequisites and no activation authorization
- **THEN** the entry point renders or applies a CronJob with the reviewed schedule and `spec.suspend: true` (or leaves it absent when the baseline explicitly disables scheduling), and reports that no collection Job was started

#### Scenario: Unauthorized activation is rejected
- **WHEN** an operator requests an active production CronJob without the required reviewed authorization references and exact packet checks
- **THEN** the entry point fails before the CronJob write and leaves the existing schedule state unchanged

#### Scenario: Scheduled resource matches service and storage
- **WHEN** the schedule component is rendered for a valid release
- **THEN** its image reference, SQLite mount, `/data/snapshots.sqlite3` path, Shanghai timezone, non-root security context, no-token policy, bounded deadlines, and `Forbid` concurrency policy match the reviewed Dashboard contract

### Requirement: TrueNAS image and target safety

The deployment workflow SHALL validate the TrueNAS target, build or select an immutable image tag, verify its checksum, import it into the target k3s container runtime when required, and use the same reviewed image reference for every component in one operation. It SHALL support dry-run or discovery output and SHALL stop before target writes when required tools, connectivity, image, values, or Kubernetes version checks fail.

#### Scenario: Image is prepared for an all-components operation
- **WHEN** an operator runs the all-components operation with a clean or explicitly accepted checkout and valid environment file
- **THEN** the workflow produces an immutable image artifact, verifies its digest after transfer/import, and uses that exact reference for the service and schedule resources

#### Scenario: Image preparation fails
- **WHEN** local build, smoke test, checksum verification, transfer, or k3s runtime import fails
- **THEN** the workflow exits nonzero before applying the affected component resources and identifies the failed preparation step

#### Scenario: Dry-run does not mutate the cluster
- **WHEN** an operator requests component rendering or discovery in dry-run mode
- **THEN** the workflow reports the selected component, dependency checks, effective resource names, and planned actions without creating, updating, deleting, or suspending any Kubernetes resource

### Requirement: Idempotence, observability, and non-destructive recovery

Each component operation SHALL be safe to repeat, SHALL report the observed resource names and postconditions, and SHALL provide a non-destructive failure path that preserves the SQLite PVC and existing snapshots. Component failures SHALL be distinguishable from prerequisite failures and SHALL NOT be reported as successful deployments.

#### Scenario: Repeating a successful component operation
- **WHEN** an operator repeats the same component operation with unchanged reviewed inputs
- **THEN** the operation performs no destructive storage action, converges resources to the same desired state, and reports success with the same claim and workload identities

#### Scenario: Partial all-components failure
- **WHEN** database deployment succeeds but service or schedule deployment fails
- **THEN** the workflow reports the completed and failed components separately, preserves the successful PVC and resources, and provides the exact next component to retry

#### Scenario: Recovery from an unexpected active schedule
- **WHEN** discovery finds an active or drifted application CronJob outside the reviewed packet
- **THEN** the ordinary component operation stops and requires the existing exact-resource scheduling disable/rollback procedure before retrying, without deleting the SQLite PVC
