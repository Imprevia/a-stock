## ADDED Requirements

### Requirement: Sector enrichment lineage is visible in collection results
The system SHALL preserve supplemental source, mapping revision, matched-row count, field coverage, latest-only date evidence, and enrichment warnings in sector snapshot quality and collection task metadata. Provider-free status and aggregate reads MUST expose the retained metadata without making a new provider request.

#### Scenario: Sector enrichment succeeds partially
- **WHEN** a Fuyao sector task fills some missing fields from the Eastmoney dataapi response
- **THEN** the task and snapshot report the Fuyao base source, the supplemental source, matched and unmatched counts, field coverage, and a degraded/partial warning

#### Scenario: Sector enrichment fails after Fuyao succeeds
- **WHEN** the supplemental request fails or fails validation after Fuyao produced a valid result
- **THEN** the task commits the Fuyao base snapshot, reports the supplemental warning, and does not mark the dataset as `failed-missing`

#### Scenario: Provider-free status is read after enrichment
- **WHEN** a client reads collection status, a collection run, or a materialized aggregate after a sector enrichment attempt
- **THEN** the response includes the stored lineage and warning metadata without contacting Eastmoney, Fuyao, or Tushare

### Requirement: Supplemental provider calls preserve collection isolation and retention
The system SHALL execute sector enrichment within the existing sector task lease and transport controls. An enrichment failure MUST NOT stop sibling dataset tasks, overwrite a successful same-date sector snapshot, or cause cross-date fallback.

#### Scenario: Enrichment fails in a full collection run
- **WHEN** sector enrichment fails while other dataset tasks are running
- **THEN** sibling tasks continue independently, the parent run records the sector quality warning, and successful sibling snapshots remain committed

#### Scenario: A later sector retry fails completely
- **WHEN** both the Fuyao base collection and its supplemental enrichment fail for a date with an existing successful sector snapshot
- **THEN** the task is recorded as `failed-retained`, the prior same-date snapshot and its lineage remain available, and no other-date snapshot is substituted
