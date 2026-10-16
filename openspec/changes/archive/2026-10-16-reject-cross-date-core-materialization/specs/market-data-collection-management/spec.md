## MODIFIED Requirements

### Requirement: Core index failure isolation
The system SHALL collect and report the five configured core indices as independently evaluated sub-results within the `core` dataset. A core index result SHALL count as current-date evidence only when its normalized latest effective observation date equals the selected date; an earlier provider history date MUST NOT be relabeled through candidate actual-date or quality metadata. A non-exact result MAY be replaced only by a previously successful result for the same dataset and selected date, and every retained result MUST independently satisfy the exact-date contract.

#### Scenario: One core index fails
- **WHEN** four configured indices collect successfully for the selected date and one index fails
- **THEN** the `core` task finishes as `partial`, preserves the four successful exact-date index results, and exposes the failed index and warning

#### Scenario: Failed index retains an exact-date value
- **WHEN** one index fails but the same selected date has a prior successful result for that index
- **THEN** the new core snapshot retains that same-date index value with `failed-retained` metadata rather than removing it or using another date

#### Scenario: No core index is available
- **WHEN** all five indices fail and no same-date index result can be retained
- **THEN** the `core` task finishes as `failed-missing` and no new core snapshot or invalid core aggregate is published

#### Scenario: Provider returns prior-session history for one index
- **WHEN** a provider request for the selected date returns an index whose latest effective observation belongs to an earlier session
- **THEN** that index is classified as a date-mismatch failure, the warning records the requested and actual dates, and the result does not count as a current success

#### Scenario: Four indices are exact and one is cross-date
- **WHEN** four indices prove the selected date and one index proves only an earlier date with no same-date value available for retention
- **THEN** the `core` task may publish a `partial` exact-date snapshot containing only the four usable indices while the fifth remains explicitly failed or missing

#### Scenario: Every provider result belongs to an earlier date
- **WHEN** all five newly acquired index results prove only an earlier date and no successful core snapshot exists for the selected date
- **THEN** the task finishes as `failed-missing`, preserves the actual-date diagnostics, and writes neither a core snapshot nor a materialized aggregate for the selected date

#### Scenario: Cross-date refresh retains an existing selected-date snapshot
- **WHEN** all newly acquired index results are cross-date but a successful core snapshot already exists for the selected date
- **THEN** the task finishes as `failed-retained` and leaves the existing selected-date snapshot and aggregate unchanged

### Requirement: Materialized market-environment aggregate
The system SHALL rebuild and validate the selected date's materialized market-environment response after each successful dataset commit, using the latest successful exact-date result for every dataset. Before atomic replacement, the system MUST verify that the aggregate key, aggregate `asOf`, core snapshot identity, core payload `asOf`, core effective-date evidence, and included component actual-date evidence agree with the selected date. A failed validation MUST abort replacement and MUST NOT publish the candidate as successful evidence.

#### Scenario: Successful dataset updates the aggregate
- **WHEN** a dataset task commits a new successful exact-date snapshot and all materialization date checks pass
- **THEN** the system rebuilds the aggregate, validates it against the API response contract, and atomically replaces the previous materialized aggregate

#### Scenario: Aggregate contains incomplete evidence
- **WHEN** one or more datasets have no successful exact-date snapshot
- **THEN** the aggregate remains available when exact-date core data is usable, marks coverage as partial or degraded, and keeps unavailable evidence missing or insufficient

#### Scenario: Failed task does not remove aggregate evidence
- **WHEN** a task fails while the materialized aggregate already references a same-date successful snapshot for that dataset
- **THEN** the aggregate continues serving the retained evidence and exposes the latest refresh warning

#### Scenario: Cross-date core blocks materialization
- **WHEN** a core snapshot key uses the selected date but its payload or effective-date evidence belongs to an earlier date
- **THEN** aggregate replacement is rejected atomically, an existing valid same-date aggregate remains unchanged, and no cross-date value is served as selected-date evidence

#### Scenario: Valid partial core is materialized
- **WHEN** the core snapshot contains only current-date or same-date retained index results and identifies all unavailable indices as missing or failed
- **THEN** the system may materialize a partial or degraded aggregate whose public `asOf` remains the selected date
