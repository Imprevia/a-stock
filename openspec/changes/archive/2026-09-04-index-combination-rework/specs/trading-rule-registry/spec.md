## MODIFIED Requirements

### Requirement: Complete rule coverage inventory

The system SHALL maintain a machine-readable inventory for every `QTS-*` ID found in the quantified documentation, including document path, implementation state, evaluator availability, tests, and evidence references. The documented rule count SHALL be 330 after registering `QTS-01-01-06` (five-state index synchronization), `QTS-01-01-07` (20-day range position), and `QTS-01-01-08` (5-day turnover ratio), and the executable scope of Chapter 01 SHALL be 49 rules.

#### Scenario: Repository coverage is complete

- **WHEN** the coverage command scans the quantified documentation and registry
- **THEN** all 330 documented rule IDs appear exactly once in the inventory and all executable rules have valid YAML definitions

## ADDED Requirements

### Requirement: Append-only rule registration without scoring-group mutation

Registering new executable rules SHALL NOT alter the membership, weights, or thresholds of existing scoring groups. `QTS-01-00-01` (price-volume group) SHALL keep exactly its five members `QTS-01-01-01` through `QTS-01-01-05` with unchanged weights, and newly registered rules `QTS-01-01-06` through `QTS-01-01-08` SHALL be registered with `metric.band` evaluators for dashboard display and future calibration without joining any aggregate group. Existing rule IDs SHALL NOT be renumbered or reordered by documentation edits.

#### Scenario: New rules leave existing group output unchanged

- **WHEN** the three new rules are registered and the existing fixed-snapshot golden replay is executed
- **THEN** `QTS-01-00-01` and every other existing rule produce identical scores and traces as before the registration

#### Scenario: New rules validate as standalone executables

- **WHEN** the registry loads the rule set containing `QTS-01-01-06` through `QTS-01-01-08`
- **THEN** each new rule loads with a unique stable ID, a `metric.band` evaluator, threshold provenance, and a document reference to the quantified Section 01-01 document
