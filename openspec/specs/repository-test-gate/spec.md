# Repository Test Gate Specification

## Purpose

Defines how the repository prevents its own test suite from silently weakening: a committed monotonic baseline over measurable test and interface-coverage facts, a layered offline commit gate with declared time budgets, auditable bypasses, and a verified hook installation precondition.

## Requirements

### Requirement: Test hooks are installed and verified before relying on them

The repository SHALL provide an installation step that mounts the tracked hooks and a verification step that reports whether they are active for the current checkout. A gate that depends on hook execution MUST NOT report success when the hooks are unmounted, and MUST NOT report success when its required interpreter or tool is unavailable.

#### Scenario: Hooks are unmounted on a fresh clone

- **WHEN** a checkout has no `core.hooksPath` configuration and the tracked hooks are therefore inert
- **THEN** the verification step reports the hooks as inactive, names the installation command, and the gate does not claim that commits were verified

#### Scenario: A hook dependency is unavailable

- **WHEN** a hook cannot locate its required interpreter
- **THEN** it returns nonzero and names the missing dependency; only an explicit audited local bypass may proceed and MUST be labeled unverified

### Requirement: The test suite has a monotonic committed baseline

The repository SHALL commit executable test inventory, exercised HTTP operations and per-file uncovered-statement ceilings. Missing inventory/operations or uncovered counts exceeding ceilings SHALL fail. Baseline updates SHALL be explicit and reviewed against the trusted parent/target baseline; ordinary verification MUST NOT rewrite it. Tightening means adding protected inventory/operations or reducing uncovered ceilings. Renames and intentional removals require documented reconciliation, not a silent reset.

#### Scenario: A test is deleted

- **WHEN** a change removes an existing test case without recording a deliberate baseline reduction
- **THEN** the gate fails and identifies the decreased fact together with the previously recorded value

#### Scenario: A test is added

- **WHEN** a change adds test cases so that measured facts exceed the baseline
- **THEN** the gate passes and reports the improvement, and the baseline remains unchanged until it is deliberately raised

#### Scenario: The baseline is raised deliberately

- **WHEN** a change updates the baseline together with the test additions that justify the increase
- **THEN** the gate passes and the baseline artifact records the new values as the reference for subsequent changes

#### Scenario: Baseline artifact is regenerated without review

- **WHEN** the baseline artifact changes without accompanying test changes or a stated justification
- **THEN** the change is rejected during review because raising the baseline is an explicit decision rather than a build side effect

### Requirement: Every declared HTTP operation is exercised at least once at runtime

The gate SHALL verify that each HTTP operation declared by the application's OpenAPI schema is invoked at least once during the test suite. Operations introduced without runtime verification MUST be reported rather than passing silently. Verification MUST be satisfied by an actual request through the application and MUST NOT be satisfied solely by a declaration-level assertion such as checking that a path name appears in the schema.

#### Scenario: A newly added endpoint has no runtime test

- **WHEN** a change adds an HTTP operation and no test issues a request to it
- **THEN** the gate fails and lists the operation by method and path

#### Scenario: An endpoint appears only in a schema expectation table

- **WHEN** an operation is listed in an OpenAPI expectation assertion but no test issues a request to it
- **THEN** the operation is still reported as unexercised

#### Scenario: Every declared operation is invoked

- **WHEN** tests issue at least one request to every declared HTTP operation
- **THEN** the interface-coverage check passes and no operation is reported as unexercised

### Requirement: Line coverage is ratcheted per file on uncovered statements

The gate SHALL enforce per-file ceilings on uncovered backend statements. Increased counts SHALL fail; deleting already-covered statements alone MUST NOT fail this coverage check. Newly observed files SHALL be reported with candidate entries; persisting entries requires an explicit reviewed update. Ordinary verification MUST NOT mutate the committed baseline. Report aggregate coverage for review without enforcing an arbitrary percentage.

Uncovered statements are chosen over a coverage ratio as the enforced fact because a ratio conflates two directions: removing covered code lowers a ratio while improving nothing, whereas an uncovered count only rises when tested behavior is lost or untested behavior is added.

#### Scenario: Untested code is added to a covered file

- **WHEN** a change adds statements without tests to a file recorded in the baseline
- **THEN** the gate fails and names that file with its recorded and current uncovered-statement counts

#### Scenario: Tests are removed while their target remains

- **WHEN** a change deletes tests that exercised a file recorded in the baseline
- **THEN** that file's uncovered count rises and the gate fails

#### Scenario: Covered code is deleted together with its tests

- **WHEN** a change removes statements that were covered along with the tests exercising them
- **THEN** the coverage sub-check reports no regression from that deletion alone; inventory reconciliation and all other checks still apply

#### Scenario: A new source file has no tests

- **WHEN** a change adds a previously unrecorded source file and no test covers it
- **THEN** the gate reports a candidate entry and the newly observed uncovered count without silently persisting a baseline change

#### Scenario: A file's coverage improves

- **WHEN** a change adds tests that reduce a recorded file's uncovered statements
- **THEN** the gate passes and the baseline remains unchanged until it is deliberately raised

### Requirement: The authoritative layer preserves database-backed verification

The layer that executes the complete suite SHALL also provide the test database configuration the suite expects. Relocating or consolidating the complete-suite execution MUST preserve the database service and connection configuration, because test files that require a database silently skip when that configuration is absent, and such skips are indistinguishable from passing checks in the job summary.

#### Scenario: The complete suite is consolidated into another workflow or job

- **WHEN** the complete suite execution is moved or merged into a different workflow or job
- **THEN** the database service and its connection environment move with it and the previously configured database-backed tests still execute

#### Scenario: Database-backed tests are enabled in the authoritative layer

- **WHEN** the authoritative layer runs in continuous integration
- **THEN** the tests requiring a database execute and their results are reported rather than reported as skipped

#### Scenario: Coverage is compared in an environment that differs from the baseline environment

- **WHEN** coverage is measured under a database configuration that differs from the configuration recorded with the baseline
- **THEN** the gate reports the mismatch with a nonzero incomplete result, blocks authoritative success and does not compare incompatible measurements

### Requirement: The commit gate is layered with explicit time budgets

The repository SHALL define ordered verification layers with declared responsibilities and time budgets. A fast layer SHALL run before a commit is recorded, an intermediate layer SHALL run before commits are published, and an authoritative layer SHALL run in continuous integration. Each layer MUST state which checks it owns, and a check owned by a slower layer MUST NOT be duplicated in a faster layer without an explicit budget justification.

#### Scenario: A commit runs the fast layer

- **WHEN** a commit is recorded
- **THEN** the fast layer runs its assigned checks and reports elapsed time against its advisory budget; only an actual verification failure blocks success

#### Scenario: The fast layer exceeds its budget

- **WHEN** the fast layer would exceed its declared budget for the current change
- **THEN** it reports an overrun warning; selection fallback is chosen before execution and elapsed time MUST NOT turn unfinished or failing tests into a pass

#### Scenario: A commit bypasses an intermediate layer

- **WHEN** commits are published without the intermediate layer completing
- **THEN** the authoritative layer still evaluates the full suite and the omission is visible in the recorded outcome

### Requirement: The fast layer selects tests by change scope and declares its fallback

The fast layer SHALL select tests from the files changed by the change under evaluation. When the mapping is ambiguous or the change is too broad to select a meaningful subset, the layer SHALL fall back to a declared deterministic subset instead of running nothing.

#### Scenario: A source module changes

- **WHEN** a change modifies a source module that maps to specific test files
- **THEN** the fast layer runs those test files and reports the mapping it used

#### Scenario: A change is too broad to map

- **WHEN** a change touches more files than the declared mapping threshold or spans unrelated areas
- **THEN** the fast layer runs the declared fallback subset and reports that the fallback was applied

#### Scenario: A change touches no testable code

- **WHEN** a change contains only documentation or other non-code files
- **THEN** the fast layer skips test execution, reports that no testable change was found, and the existing documentation contract still runs

### Requirement: Gate bypasses are explicit and auditable

Local bypasses SHALL be explicit and audited: use the documented emergency variable for execution and validate a reason-bearing marker at commit-message validation time or an equivalent audit step. Pre-commit MUST NOT trust a stale commit-message file. A bypass SHALL be labeled unverified, never a passing test result. Authoritative CI MUST ignore local bypasses.

#### Scenario: A commit bypasses the test gate with a marker

- **WHEN** a commit message carries the documented skip marker with a reason
- **THEN** the gate permits the commit and records that the bypass occurred

#### Scenario: The emergency variable is used

- **WHEN** the documented emergency environment variable is set
- **THEN** the gate is skipped for that invocation and the runbook states that this path is reserved for recovery rather than normal development

#### Scenario: A bypass is attempted without either mechanism

- **WHEN** neither a skip marker nor the emergency variable is present and the gate fails
- **THEN** the commit does not proceed

### Requirement: Gate behavior is equivalent across supported platforms

The gate SHALL produce equivalent results on Windows, macOS, and Linux and MUST NOT bind to a single platform's path separators, interpreter command name, or shell.

#### Scenario: The gate runs on Windows

- **WHEN** the gate executes on Windows where the interpreter command differs
- **THEN** it resolves an available interpreter and produces the same pass or fail result as on Unix-like systems

#### Scenario: The gate runs in continuous integration

- **WHEN** the authoritative layer executes in continuous integration
- **THEN** it performs the same verification as the local layers and remains offline and deterministic

### Requirement: The gate remains offline and provider-free

The gate and its ratchet checks SHALL execute without network access and MUST NOT invoke real market-data providers, production databases, Kubernetes or Helm write operations, or deployment smoke. Tests requiring an external database SHALL continue to skip through their existing environment-variable guard.

#### Scenario: A gate runs without network access

- **WHEN** the gate executes in an environment with no reachable market-data network
- **THEN** all ratchet and gate checks complete using committed fixtures and local state

#### Scenario: Database-backed tests are present but unconfigured

- **WHEN** the suite contains integration tests that require a configured test database and no such configuration exists
- **THEN** non-authoritative local runs may report the guarded skips explicitly, but authoritative CI MUST block with a nonzero incomplete result instead of claiming full verification
