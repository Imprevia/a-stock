## MODIFIED Requirements

### Requirement: Manual collection access boundary
The system SHALL keep manual collection write operations enabled by default for local development and SHALL allow operators to disable them with an explicit server-side configuration switch. A deployment without application-level authentication MUST identify whether enabled collection writes are protected by an independently authenticated operator channel or are intentionally exposed through an explicitly accepted anonymous network endpoint. An anonymous endpoint MUST NOT be represented as authenticated, authorized, or limited to particular clients unless an independently verified network control enforces that limit.

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

#### Scenario: Accepted anonymous NodePort enables manual collection
- **WHEN** the deployment has no application-level authentication, the configuration switch is enabled, and an authorized owner has explicitly accepted a fixed NodePort exposure
- **THEN** every client able to route to that node port can start a date-valid collection run without presenting an identity or credential

#### Scenario: Anonymous NodePort remains prohibited
- **WHEN** the application has no application-level authentication and no explicit authorized-owner acceptance of anonymous write exposure is recorded
- **THEN** manual collection remains explicitly disabled on a reachable NodePort regardless of CORS configuration or whether the client displays collection buttons

#### Scenario: Anonymous exposure is described accurately
- **WHEN** manual collection is exposed through a NodePort without an independently verified firewall or ACL
- **THEN** deployment documentation identifies the reachable network as the exposure boundary and does not claim restriction to a user, device, or subnet

#### Scenario: Operator tunnel closes
- **WHEN** the authenticated port-forward or SSH tunnel ends
- **THEN** the operator endpoint is no longer listening and any separately configured NodePort remains independently reachable according to its network route

### Requirement: Manual collection deployment preserves data and runtime invariants
Enabling, disabling, protecting, or anonymously exposing manual collection in an existing deployment SHALL preserve the configured snapshot PVC, SQLite path, single-replica boundary, provider controls, date-capability validation, and failure-retention behavior.

#### Scenario: Direct-access Helm configuration is rendered before deployment
- **WHEN** an operator prepares the accepted environment values for direct manual collection
- **THEN** the rendered resources contain one enabled manual-refresh environment variable, a NodePort Service fixed at `32001`, the existing PVC claim and snapshot path, one Dashboard replica, and no unintended Ingress or scheduled collection resource

#### Scenario: Helm configuration is rendered before deployment
- **WHEN** an operator prepares environment values for protected manual collection rather than accepted anonymous direct access
- **THEN** the rendered resources contain one explicit manual-refresh environment variable, a ClusterIP Service without a nodePort, the existing PVC claim and snapshot path, one Dashboard replica, and no unintended Ingress or scheduled collection resource

#### Scenario: Existing PVC is reused
- **WHEN** the Helm release is upgraded to change the manual-collection access model
- **THEN** the existing claim remains mounted at the same path and historical snapshots and collection records remain readable without a schema migration

#### Scenario: A provider fails during a manual run
- **WHEN** one or more provider calls fail, are rate limited, or return insufficient evidence
- **THEN** each dataset retains its independent terminal state, an existing successful same-date snapshot is not overwritten, and missing evidence remains degraded or insufficient rather than being replaced with zero

#### Scenario: A duplicate dataset/date request is made
- **WHEN** any client repeats a collection request for a dataset and date that already has an active lease
- **THEN** the existing lease and provider serialization rules prevent an uncontrolled duplicate provider call

### Requirement: Manual collection deployment is reversible
The deployment SHALL provide a configuration-first rollback that blocks new collection writes before or independently of changing network exposure, and rollback MUST NOT delete the snapshot PVC.

#### Scenario: Manual collection is disabled during rollback
- **WHEN** an operator sets `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` to a disabled value and rolls out the configuration
- **THEN** collection POST returns 403 without starting provider work while health and local snapshot reads remain available through the configured Service

#### Scenario: Anonymous NodePort remains read-only during staged rollback
- **WHEN** the manual collection switch has been verified disabled but the NodePort has not yet been removed
- **THEN** Dashboard reads remain reachable while collection POST operations are rejected without provider work

#### Scenario: ClusterIP access is restored
- **WHEN** an operator removes direct LAN access after disabling collection writes
- **THEN** the Service returns to ClusterIP without changing the existing PVC, snapshots, or collection history

#### Scenario: Previous service exposure is restored
- **WHEN** an operator restores a previously reviewed Service exposure model
- **THEN** the manual collection switch matches that model's reviewed access boundary before the restored endpoint becomes reachable

#### Scenario: Helm release is rolled back
- **WHEN** the operator rolls back to the recorded protected-access revision
- **THEN** the Deployment and Service return to the reviewed revision while the existing PVC, snapshots, and collection history are retained
