## ADDED Requirements

### Requirement: Legacy sectors collection is retired without evidence loss
The historical Eastmoney-first and Fuyao-fallback `sectors` collection contract SHALL be retired from public API, scheduling, frontend, and new collection execution. Its stored snapshots, tasks, warnings, and capability evidence SHALL remain immutable audit records and MUST NOT be deleted, relabeled, or treated as successful `industry-ranking`, `sector-turnover`, or `sector-breadth` data.

#### Scenario: A new collection run is created
- **WHEN** a client starts a current supported collection run
- **THEN** no legacy `sectors` task or Eastmoney sector-ranking request is created

#### Scenario: Historical evidence is inspected
- **WHEN** an administrator audits an old `sectors` run
- **THEN** its original dataset ID, source, payload, warning, date, and checksum remain unchanged

### Requirement: THS observations and Shenwan analysis remain distinct
Provider-specific THS identities and current constituents SHALL NOT be accepted as Shenwan Level 1 point-in-time identities or historical memberships. No display-name similarity or legacy `SectorRow` compatibility field may bridge the two contracts.

#### Scenario: A THS code resembles a canonical industry
- **WHEN** a THS observation name matches a Shenwan display name
- **THEN** the system keeps separate identities and does not populate canonical continuity metrics or rule inputs

## REMOVED Requirements

### Requirement: Sector endpoints use the unified transport without changing fallback order
**Reason**: The legacy Eastmoney-first `sectors` acquisition path is no longer a supported collection dataset.
**Migration**: Use the three Fuyao THS datasets; unified transport controls still apply to every external request they start.

### Requirement: Eastmoney requests are serialized and recover transient failures
**Reason**: Eastmoney sector ranking is removed from the new sector collection path.
**Migration**: Historical evidence remains unchanged; new Fuyao requests use the repository-wide transport policy and request budget.

### Requirement: Sector ranking falls back to the delayed endpoint
**Reason**: The compatibility ranking task is replaced by complete four-classification `industry-ranking`.
**Migration**: Query the new local catalog/ranking APIs or run the explicitly gated ranking task.

### Requirement: Fuyao sector fallback uses the documented THS index contract
**Reason**: Fuyao is no longer a fallback that emits a reduced legacy `SectorRow`; it is the explicit source for three independently qualified datasets.
**Migration**: Use `fuyao-ths-sector-datasets` requirements and exact capability revisions for the new endpoints.

### Requirement: Fuyao sector fallback exposes only supported fields
**Reason**: The reduced legacy shape discarded volume and could not represent complete ranking, K-line, or breadth facts.
**Migration**: Read the typed ranking, turnover, and breadth contracts; unsupported fields remain null at their field-specific source.

### Requirement: Fuyao sector capability is fail-closed and auditable
**Reason**: The single `fuyao/sectors/fuyao-market-v2` gate is insufficient for the distinct catalog/snapshot/history/dump contracts.
**Migration**: Promote and configure exact eligible capability revisions for each new provider operation before any provider I/O.

### Requirement: Sector leader fields match the provider contract
**Reason**: The legacy leader field is not part of the new dataset contracts.
**Migration**: Use stable member Top gain/turnover lists derived from verified same-day facts; do not synthesize leader roles.

### Requirement: Sector failure remains auditable
**Reason**: Failure retention is now defined independently for each new dataset and historical backfill checkpoint.
**Migration**: Use collection management task states and new-dataset quality/lineage while retaining old attempts for audit.
