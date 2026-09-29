## ADDED Requirements

### Requirement: Independent provider capability metadata is auditable
The system SHALL record the independent provider's capability revision, actual source, date evidence, quality status, and preceding provider warnings in collection task or snapshot metadata without exposing credentials. Status reads MUST remain provider-free.

#### Scenario: Approved fallback succeeds after Eastmoney failure
- **WHEN** the independent sector provider returns a validated degraded result after both Eastmoney endpoints fail
- **THEN** the collection task exposes the independent source, capability revision, degraded or fallback status, and the Eastmoney failure warnings

#### Scenario: Capability gate blocks a provider
- **WHEN** the independent provider switch is enabled but no matching eligible capability report exists
- **THEN** the task fails or retains same-date data with an explanatory capability warning and does not call the provider

#### Scenario: Status is read while providers are unavailable
- **WHEN** the collection status page is loaded after a provider failure or while all providers are unreachable
- **THEN** it returns stored source, revision, quality, latest-attempt, and warning metadata without making an external provider request

### Requirement: Effective core date is used for lazy sector sections
The system SHALL use the effective Shanghai trading date returned by the core response for subsequent lazy chapter-section requests, including `sectors`, when a user-selected weekend or holiday date is normalized by the server.

#### Scenario: Manual non-trading date is normalized by core
- **WHEN** a user selects a weekend or holiday, the core response returns a prior valid trading date, and the user opens the sectors section
- **THEN** the section request uses the normalized core date, matches the core response date, and does not classify the request as an unsupported historical latest-only request solely because of the original selected date

#### Scenario: Explicit supported historical date remains unchanged
- **WHEN** a user selects a date that is already a valid supported trading date
- **THEN** the sectors section continues to request that exact date and preserves the provider's date-capability restrictions
