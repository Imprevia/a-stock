## ADDED Requirements

### Requirement: Fail-closed production scheduling default

The system SHALL keep production scheduled market-data collection absent or
suspended until both of the following have been recorded as canonical change
artifacts: Gate B action authorization (covering the exact packet's admission
probe, no-provider canary, suspended application release, and one named
provider-backed Job) AND Gate C operation authorization (covering the exact
active-overlay apply and the chosen catch-up behavior). Until both
authorizations are recorded, no deployed release SHALL create or unsuspend an
application CronJob that calls `snapshots scheduled-refresh`, and no
controller-created Job from such a CronJob SHALL appear in the cluster. A
recorded Gate B / Gate C progression authorization alone MUST NOT be treated
as a substitute for either Gate B action authorization or Gate C operation
authorization.

The Chart, the TrueNAS baseline values, and every TrueNAS scheduling overlay
SHALL default to `scheduledCollection.enabled=false` and
`scheduledCollection.suspend=true`. The generic install, upgrade, and
application-rollback deployment entry points SHALL refuse to proceed unless
the typed values are exactly that pair before the first Helm render, image
work, or target API access. Any other initial state MUST cause the entry
point to exit nonzero with a message identifying the violated invariant and
MUST NOT perform a release write.

The active execution plan, the project status document, and the deployment
runbook SHALL each carry a visible statement of this fail-closed contract
so an operator who observes the absence of a CronJob in production can
verify the absence is the intended Gate A policy rather than a deployment
defect, without reading the Chart, the overlays, or the entry point source.
Each of those documents SHALL also state that the current absence reflects
"progression authorization recorded, action and operation authorizations not
yet recorded" rather than a permanent off-by-design decision.

#### Scenario: Default Chart render omits the application CronJob

- **WHEN** an operator renders the Chart with no values overrides
- **THEN** the rendered manifest contains no application CronJob that
  targets the market-data collection command

#### Scenario: TrueNAS baseline and overlays default to off

- **WHEN** an operator reads the TrueNAS baseline values or any of the
  scheduled overlays without applying further overrides
- **THEN** every file declares `scheduledCollection.enabled=false` and
  `scheduledCollection.suspend=true`

#### Scenario: Entry point rejects a non-off initial state

- **WHEN** an operator invokes the generic deployment entry point with
  typed values that are not exactly `enabled=false` and `suspend=true`,
  AND neither Gate B action authorization nor Gate C operation
  authorization has been recorded as a canonical change artifact
- **THEN** the entry point exits nonzero with a message naming the
  violated invariant, performs no Helm write, copies no image, and
  accesses no target API

#### Scenario: Human-readable artifacts surface the contract

- **WHEN** an operator opens the active execution plan, the project
  status document, or the deployment runbook
- **THEN** each document contains an explicit statement that production
  scheduled collection is absent because Gate B action authorization and
  Gate C operation authorization have not yet been recorded as canonical
  change artifacts, AND that a recorded progression authorization alone
  is not an operation authorization