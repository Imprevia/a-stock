## MODIFIED Requirements

### Requirement: Standard market environment snapshot
The system SHALL accept a canonical snapshot containing as-of date, provider quality, daily market indicators, breadth, limit statistics, tier returns, sector concentration, active turnover securities, liquidity, and structured events. The canonical metric set SHALL support `sector.relative_strength_percentile`, `sector.top_turnover_days`, `sector.above_ma20_ratio_percentile`, `sector.disagreement_recovery_percentile`, and `sector.top5_turnover_concentration_percentile`. A sector metric not proven for the snapshot's exact date or quality contract MUST remain absent or `null` rather than being replaced with zero, a provider ranking field, current membership, or another date's value.

#### Scenario: Missing critical input
- **WHEN** a rule lacks a critical declared input
- **THEN** it follows its declared missing-data policy and emits `insufficient` or reduced confidence rather than substituting zero

#### Scenario: Complete sector metrics are present
- **WHEN** all five exact-date metrics have acceptable compatible quality
- **THEN** `QTS-01-05-01` through `QTS-01-05-05` consume the canonical inputs and emit deterministic individual traces

#### Scenario: Only current-day observations are present
- **WHEN** a source contains ranking rows but no point-in-time continuity metrics
- **THEN** ranking fields and provider identities are not substituted and affected rules follow missing-data policy

#### Scenario: Sector metric coverage is partial
- **WHEN** only a subset of the five metrics meets exact-date and quality requirements
- **THEN** proven metrics remain evaluable, unavailable canonical names are listed, and confidence is reduced by valid coverage

## ADDED Requirements

### Requirement: Production sector metrics retain reproducible provenance
The system SHALL copy sector metrics from same-date market-environment analysis into the canonical trading snapshot without independently recomputing or renaming them. `sector.relative_strength_percentile`, `sector.top_turnover_days`, `sector.above_ma20_ratio_percentile`, and `sector.disagreement_recovery_percentile` SHALL come from the first deterministically ranked canonical Shenwan industry; `sector.top5_turnover_concentration_percentile` SHALL remain the market-wide value. When no first canonical industry exists, the first four metrics SHALL remain absent or `null` while an independently valid concentration metric MAY remain available.

The snapshot and evidence SHALL retain source dataset, actual date, history and constituent coverage, data version, classification version, membership version, universe version, adjustment version, benchmark version, calculation version, upstream immutable evidence checksums/references, rule-set version, and each rule-trace version. Every participating value and version SHALL participate in deterministic hashing. A reference to the evidence bundle being generated from the snapshot MUST NOT enter that same snapshot's hash.

#### Scenario: Same-date analysis is bridged
- **WHEN** a compatible continuity result exists for the requested snapshot date
- **THEN** its canonical values and provenance are copied with the same `asOf` and no provider call

#### Scenario: No first canonical industry exists
- **WHEN** market-wide concentration is valid but no exact-date canonical Shenwan industry can be ranked first
- **THEN** concentration may be copied while the four candidate-specific metrics remain absent or `null`

#### Scenario: Provenance is incompatible
- **WHEN** a value lacks compatible date, classification, calculation, evidence, or quality metadata
- **THEN** it is not admitted as a canonical input and the affected rule follows missing-data policy

#### Scenario: Equivalent production evidence is replayed
- **WHEN** identical normalized values, provenance, rule set, and code version are evaluated again
- **THEN** snapshot hash, rule traces, confidence, vetoes, and result bytes are identical

#### Scenario: A provenance version changes
- **WHEN** a participating data, classification, calculation, or evidence version changes
- **THEN** the snapshot records the new provenance and has a distinct identity even if the displayed number is unchanged

#### Scenario: Current evidence bundle is generated
- **WHEN** an evidence bundle identifier is derived from the normalized snapshot hash
- **THEN** that output bundle identifier is excluded from its own snapshot input while upstream immutable evidence references remain hashed
