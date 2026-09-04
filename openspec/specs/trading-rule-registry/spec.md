# Trading Rule Registry Specification

## Purpose

TBD: Define registry, coverage, lifecycle, and documentation-linkage contracts for trading rules.

## Requirements

### Requirement: Versioned machine-readable rule registry
The system SHALL load trading rules from versioned YAML files validated against a closed schema. Every rule SHALL have a globally unique stable rule ID, positive version, lifecycle status, scope, evaluator, input declarations, windows, threshold provenance, scoring, veto, missing-data behavior, outputs, and document references.

#### Scenario: Valid rule is loaded
- **WHEN** a rule file satisfies the schema and references a registered evaluator
- **THEN** the loader returns a typed immutable rule definition

#### Scenario: Invalid rule is rejected
- **WHEN** a rule contains an unknown field, duplicate ID, illegal status, missing threshold provenance, or unknown evaluator
- **THEN** validation fails before any evaluation runs

### Requirement: Complete rule coverage inventory
The system SHALL maintain a machine-readable inventory for every `QTS-*` ID found in the quantified documentation, including document path, implementation state, evaluator availability, tests, and evidence references.

#### Scenario: Repository coverage is complete
- **WHEN** the coverage command scans the quantified documentation and registry
- **THEN** all 330 documented rule IDs appear exactly once in the inventory and all executable rules have valid YAML definitions

### Requirement: Append-only rule registration without scoring-group mutation
The system SHALL NOT alter the membership, weights, or thresholds of existing scoring groups when registering new executable rules. `QTS-01-00-01` (price-volume group) SHALL keep exactly its five members `QTS-01-01-01` through `QTS-01-01-05` with unchanged weights, and newly registered rules `QTS-01-01-06` through `QTS-01-01-08` SHALL be registered with `metric.band` evaluators for dashboard display and future calibration without joining any aggregate group. Existing rule IDs SHALL NOT be renumbered or reordered by documentation edits.

#### Scenario: New rules leave existing group output unchanged
- **WHEN** the three new rules are registered and the existing fixed-snapshot golden replay is executed
- **THEN** `QTS-01-00-01` and every other existing rule produce identical scores and traces as before the registration

#### Scenario: New rules validate as standalone executables
- **WHEN** the registry loads the rule set containing `QTS-01-01-06` through `QTS-01-01-08`
- **THEN** each new rule loads with a unique stable ID, a `metric.band` evaluator, threshold provenance, and a document reference to the quantified Section 01-01 document

### Requirement: Controlled lifecycle transitions
The system SHALL enforce the lifecycle `draft`, `defined`, `backtested`, `validated`, and `retired`, and SHALL reject unsupported promotions or validation without required evidence.

#### Scenario: Unsupported validation is rejected
- **WHEN** a rule is marked `validated` without in-sample, out-of-sample, cost, confidence interval, version, and rollback evidence
- **THEN** registry validation fails

### Requirement: Documentation linkage
The system SHALL treat YAML as the machine execution source and Markdown as the explanatory source, and SHALL verify links in both directions.

#### Scenario: Documentation drift is detected
- **WHEN** a documented rule ID is absent from the inventory or an executable rule references a missing document
- **THEN** the documentation synchronization check fails
