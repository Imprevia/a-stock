## ADDED Requirements

### Requirement: Derived active-direction snapshots remain available but visibly degraded
The system SHALL accept a validated `fallback-derived` active-direction payload as an exact-date snapshot and SHALL expose its source, ranking method, mapping evidence, and warnings through collection status and normal snapshot reads. The corresponding collection task MUST be `partial` and a parent run containing that task MUST NOT be reported as an all-success run.

#### Scenario: Derived active-direction result is committed
- **WHEN** the TDX-derived active-direction payload passes date, row, name, amount, and deterministic sorting validation
- **THEN** the system commits the exact-date snapshot with source `tdx-daily-package-derived`, quality status `fallback-derived`, and the task remains available for normal reads

#### Scenario: Parent run contains only derived active-direction success
- **WHEN** a collection run contains a validated `fallback-derived` active-direction task and no failed sibling task
- **THEN** the active-direction task is reported as `partial` and the parent run is reported as `partial`, while the snapshot is retained

#### Scenario: Status view reads a derived snapshot without providers
- **WHEN** the data-collection status view is requested for a date with a `fallback-derived` active-direction snapshot
- **THEN** the view reports the retained source, degraded quality, ranking method, mapping coverage, and latest attempt without calling any external provider

#### Scenario: Derived candidate fails after Eastmoney failures
- **WHEN** the TDX candidate is missing, date-mismatched, insufficient, or cannot resolve trusted names
- **THEN** no derived snapshot is written, the task follows `failed-retained` or `failed-missing` semantics, and all relevant warnings remain visible

#### Scenario: Existing clients read derived payload fields
- **WHEN** a client reads only the existing active-direction state, summary, and Top-10 stock fields
- **THEN** the client remains compatible and may ignore the additional quality and mapping metadata
