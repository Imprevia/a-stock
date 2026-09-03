## ADDED Requirements

### Requirement: Deterministic typed evaluation
The system SHALL resolve evaluator names through an explicit Python registry and SHALL NOT execute arbitrary expressions from YAML. Equivalent normalized input, rule version, and code version SHALL produce equivalent normalized output.

#### Scenario: Fixed snapshot is replayed
- **WHEN** the same fixed snapshot and rule set are evaluated twice
- **THEN** scores, confidence, vetoes, traces, and canonical result bytes are identical

### Requirement: Standard market environment snapshot
The system SHALL accept a canonical snapshot containing as-of date, provider quality, daily market indicators, breadth, limit statistics, tier returns, sector concentration, active turnover securities, liquidity, and structured events.

#### Scenario: Missing critical input
- **WHEN** a rule lacks a critical declared input
- **THEN** it follows its declared missing-data policy and emits `insufficient` or reduced confidence rather than substituting zero

### Requirement: Scoring confidence and veto precedence
The system SHALL use the score bands 0, 25, 50, 75, and 100, SHALL calculate confidence from valid input coverage and evidence consistency, and SHALL apply hard vetoes before aggregate scores.

#### Scenario: High score with hard veto
- **WHEN** component scores are high but a systemic-risk veto is triggered
- **THEN** the final result records the veto and cannot be classified as offensive

### Requirement: Chapter 01 executable coverage
The system SHALL provide executable definitions for all 46 rule IDs in market environment chapter 01 and SHALL emit an individual trace for each rule.

#### Scenario: Chapter 01 evaluation completes
- **WHEN** a complete market environment fixture is evaluated
- **THEN** the result contains exactly 46 distinct chapter 01 rule traces and a deterministic aggregate environment classification

### Requirement: Structured human event input
The system SHALL validate human-provided events for source, publication time, entry time, direction, scope mapping, expiry, and invalidation conditions. Unobservable actor intent SHALL NOT be inferred automatically.

#### Scenario: Untraceable event is rejected
- **WHEN** an event omits its source or expiry and invalidation information
- **THEN** snapshot validation rejects the event
