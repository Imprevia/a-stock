## ADDED Requirements

### Requirement: Chapter 01 uses separate THS and Shenwan sector fields
The materialized Chapter 01 response SHALL expose THS provider observations as `industryRanking`, `sectorTurnover`, and `sectorBreadth`, and canonical Shenwan continuity analysis as `sectorAnalysis`. The legacy `sectors` field MUST NOT appear in newly materialized public responses, and historical legacy snapshots MUST NOT be rewritten to satisfy the new schema.

#### Scenario: New THS snapshots are available
- **WHEN** one or more compatible new THS dataset snapshots exist for the exact date
- **THEN** the corresponding new fields are populated from local snapshots and `sectorAnalysis` remains independently sourced and qualified

#### Scenario: Only legacy sectors evidence exists
- **WHEN** an old date has only a historical `sectors` snapshot
- **THEN** the new THS fields remain missing or insufficient and the old payload is not projected as new evidence

### Requirement: Sector-only commits rebuild Chapter 01
Every successful commit of `industry-ranking`, `sector-turnover`, or `sector-breadth` SHALL attempt the same validated atomic aggregate rebuild used by other Chapter 01 datasets.

#### Scenario: A one-dataset retry succeeds
- **WHEN** a sector-only collection run commits a successful snapshot
- **THEN** the exact-date Chapter 01 aggregate is created or replaced without requiring a later core or full collection run
