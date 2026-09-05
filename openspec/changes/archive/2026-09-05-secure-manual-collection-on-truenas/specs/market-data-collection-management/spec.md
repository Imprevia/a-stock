## MODIFIED Requirements

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
