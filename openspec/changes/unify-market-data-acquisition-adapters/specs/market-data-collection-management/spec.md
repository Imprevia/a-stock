## ADDED Requirements

### Requirement: Collection orchestration consumes normalized acquisition outcomes
The system SHALL invoke each dataset through the stable collector contract and SHALL derive task transitions, same-date retention, snapshot commits, and aggregate rebuilds from the normalized acquisition outcome rather than provider-specific methods or payload fields.

#### Scenario: Collector returns a successful candidate
- **WHEN** a dataset collector returns a normalized successful or partial candidate for the requested date
- **THEN** collection orchestration validates the outcome, commits the candidate under the active lease, records its source and quality, and triggers the existing materialized aggregate rebuild

#### Scenario: Collector returns a failure without a candidate
- **WHEN** a dataset collector returns a classified failure and no successful candidate
- **THEN** collection orchestration records `failed-retained` when a same-date successful snapshot exists or `failed-missing` when it does not, without consulting a vendor-specific failure type

#### Scenario: Collector returns mismatched identity
- **WHEN** a collector outcome identifies another dataset or another requested date
- **THEN** collection orchestration rejects it before snapshot commit and records the attempt as failed without overwriting same-date evidence

### Requirement: Provider adapter changes preserve collection compatibility
Changing the eligible provider adapter or request engine behind a dataset SHALL preserve existing collection-run APIs, task states, five stable dataset identifiers, public response fields, exact-date validation, sibling-task isolation, and same-date failure-retention behavior.

#### Scenario: Dataset succeeds through another eligible adapter
- **WHEN** an existing dataset is collected through a different registered adapter that satisfies the same dataset contract
- **THEN** collection status and run APIs remain compatible while exposing the actual source, quality, observations, timing, and warnings

#### Scenario: Optional enhanced transport is disabled
- **WHEN** the optional enhanced request engine is disabled or not configured
- **THEN** collection continues through the default transport and existing provider plans without requiring an API, database, or frontend migration

#### Scenario: Normal dashboard reads occur after adapter migration
- **WHEN** a client reads collection status or market-environment data after provider adapters have been migrated
- **THEN** the request remains provider-free and returns locally stored exact-date evidence without initializing an enhanced transport or browser runtime
