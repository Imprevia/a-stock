## MODIFIED Requirements

### Requirement: Sector ranking falls back to the delayed endpoint
The system SHALL request the primary Eastmoney industry ranking endpoint first and SHALL fall back to the compatible delayed endpoint after the primary path exhausts its permitted recovery attempts. When both Eastmoney endpoints fail, the system SHALL try an independent provider only when that provider has an approved capability revision for `sectors`; an unapproved, unverified, or disabled provider MUST NOT be used for a successful snapshot.

#### Scenario: Primary sector endpoint disconnects
- **WHEN** the primary industry ranking endpoint remains unavailable after bounded transient retries and the delayed endpoint returns valid rows
- **THEN** the sector dataset is saved with those rows, a fallback quality status and source, and a warning containing the primary failure

#### Scenario: Both Eastmoney endpoints fail and the independent provider is approved
- **WHEN** neither Eastmoney industry endpoint returns a valid payload and an independent provider is enabled with a matching `eligible` capability revision
- **THEN** the system requests the independent provider and may save its validated result with the provider source, revision, degraded or fallback quality status, and warnings for the Eastmoney failures

#### Scenario: Independent provider is not approved
- **WHEN** neither Eastmoney endpoint returns a valid payload and the independent provider is disabled, unverified, ineligible, or has a revision mismatch
- **THEN** the system does not call that provider and reports the sector collection as failed or missing according to same-date retention

#### Scenario: Both Eastmoney endpoints and the approved independent provider fail
- **WHEN** all configured sector provider paths fail or return invalid evidence
- **THEN** collection reports failure and retains an existing successful snapshot only when it belongs to the same exact date

#### Scenario: Both sector endpoints fail
- **WHEN** neither the primary nor delayed industry ranking endpoint returns a valid payload
- **THEN** collection reports failure and retains an existing successful snapshot only when it belongs to the same exact date

#### Scenario: Historical sector collection is requested
- **WHEN** a sector collection request targets a date other than the current Shanghai market date and the independent provider cannot prove that exact date
- **THEN** the request is rejected or remains insufficient and no latest snapshot is relabeled as the requested date

### Requirement: Sector leader fields match the provider contract
The system SHALL expose the industry leader as a security name derived from the provider's leader-name field and MUST NOT display the leader security code as the name. An independent provider that has no leader-name field MUST return `null` for `leader`.

#### Scenario: Provider returns leader name and code
- **WHEN** an industry row contains a leader name in `f128` and a leader code in `f140`
- **THEN** the API `leader` field contains the `f128` name value

#### Scenario: Provider omits the optional leader name
- **WHEN** an otherwise valid industry row does not contain a leader name or the independent provider does not expose one
- **THEN** the row remains usable and its `leader` field is `null`

### Requirement: Sector failure remains auditable
The system SHALL preserve existing collection isolation and exact-date retention semantics when sector recovery and fallback are exhausted, and SHALL retain the source, capability revision, provider warnings, and missing-field warnings for any degraded independent-provider result.

#### Scenario: Sector retry fails with a same-date snapshot
- **WHEN** sector collection fails after all recovery paths and a successful sector snapshot exists for the same date
- **THEN** the task is recorded as `failed-retained`, the snapshot remains available, and the latest failure warning is exposed

#### Scenario: Sector retry fails without a same-date snapshot
- **WHEN** sector collection fails after all recovery paths and no successful sector snapshot exists for that date
- **THEN** the task is recorded as `failed-missing` and no snapshot from another date is substituted

#### Scenario: Independent provider returns a degraded result
- **WHEN** the approved independent provider returns valid ranking rows with documented unsupported optional fields
- **THEN** the task may complete as partial or fallback, stores the real source and revision, and exposes all degradation warnings without treating the result as full-field `ok`

## ADDED Requirements

### Requirement: Independent sector provider preserves exact-date and field quality evidence
The system SHALL validate an independent provider's Shanghai trading-date evidence, stable ranking, and required identity, change, and turnover fields before accepting its rows. Fields unavailable from the provider, including main-net flow, up/down counts, or leader name, MUST remain `null`; the system MUST lower quality rather than substitute zeroes, codes, or data from another date.

#### Scenario: Independent provider returns a complete dated ranking subset
- **WHEN** the provider returns an industry directory, matching snapshot timestamp or trading-date evidence, stable rank inputs, names, codes, change percentages, and turnover for the requested date
- **THEN** the system emits the top ten rows in deterministic order and records the exact provider date and capability revision

#### Scenario: Provider omits unsupported sector fields
- **WHEN** a provider returns valid sector identity, change, and turnover but does not expose main-net flow, up/down counts, or a leader name
- **THEN** the API keeps those fields `null`, marks the quality as degraded or fallback, and exposes a warning naming the missing fields

#### Scenario: Provider returns mismatched or unverifiable date evidence
- **WHEN** the provider timestamp, calendar evidence, or response date does not match the requested Shanghai trading date
- **THEN** the system rejects the result, does not persist it as a successful snapshot, and preserves the date-mismatch warning

#### Scenario: Provider ranking evidence is incomplete
- **WHEN** the provider returns duplicate identities, incomplete directory coverage, unstable ordering, or rows without required name/code/change/turnover fields
- **THEN** the system rejects the result or marks it insufficient and does not invent missing values
