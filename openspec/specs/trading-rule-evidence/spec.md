# Trading Rule Evidence Specification

## Purpose

TBD: Define evidence, backtest, validation, and hashing contracts for trading rules.

## Requirements

### Requirement: Verifiable evidence bundle
The system SHALL generate a manifest-based evidence bundle containing canonical input, input hash, rule-set version, Git SHA, provider status, warnings, per-rule trace, aggregate result, and hashes for every declared file.

#### Scenario: Evidence is intact
- **WHEN** the evidence verifier processes an unmodified bundle
- **THEN** all declared files, hashes, versions, and references validate successfully

#### Scenario: Evidence is tampered with
- **WHEN** any declared input, trace, or result file changes after manifest creation
- **THEN** evidence verification fails with the affected path

### Requirement: Historical backtest evidence
The system SHALL support chronological replay over at least 500 available trading days with a target of 750, explicit in-sample and out-of-sample partitions, transaction costs, and coverage reporting.

#### Scenario: Provider history is short
- **WHEN** fewer than 500 valid trading days are available
- **THEN** the backtest records the coverage gap and cannot produce validation evidence

### Requirement: Validation promotion evidence
The system SHALL require in-sample metrics, out-of-sample metrics, transaction cost assumptions, confidence intervals, rule and data versions, and rollback criteria before a rule can be promoted to `validated`.

#### Scenario: Rule parameters change
- **WHEN** a validated rule changes evaluator, parameters, threshold, input definition, or version
- **THEN** previous validation is invalidated and the rule returns to `defined` or `backtested`

### Requirement: Canonical hashing
The system SHALL canonicalize structured data with sorted keys, ISO dates, finite numbers, and UTF-8 before calculating SHA-256 hashes.

#### Scenario: Cross-platform hashing
- **WHEN** equivalent structured data is serialized on supported operating systems
- **THEN** the canonical bytes and SHA-256 digest are identical
