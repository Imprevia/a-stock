## MODIFIED Requirements

### Requirement: Durable trading-date snapshots
The system SHALL persist each supported market dataset by dataset identifier and exact trading date, together with its normalized payload, source, fetch time, observation count, quality status, warnings, and integrity checksum. For every newly written successful snapshot, the snapshot key date, normalized payload `asOf`, quality `asOf`, candidate actual date, and dataset-specific effective-date evidence MUST agree. A mismatch MUST be rejected before persistence, and a legacy compatibility exception MUST NOT authorize a new mismatched write.

#### Scenario: Snapshot survives a service restart
- **WHEN** a dataset snapshot has been stored successfully and the API service restarts
- **THEN** a request for the same dataset and trading date reads the stored snapshot without calling the external provider

#### Scenario: Historical dates remain isolated
- **WHEN** a request targets a trading date for which no exact snapshot exists
- **THEN** the system does not substitute a snapshot captured for another date and returns the dataset as missing or insufficient

#### Scenario: Mismatched core snapshot write is rejected
- **WHEN** a core candidate is keyed by one date but its payload, quality, actual date, or latest effective index observation proves an earlier date
- **THEN** the write is rejected atomically, checksum and component revision are not advanced, and any prior successful same-date snapshot remains unchanged

#### Scenario: Exact-date partial core snapshot is accepted
- **WHEN** a partial core candidate contains only selected-date results or retained results from the same selected date and identifies unavailable indices explicitly
- **THEN** the snapshot may be stored as partial or degraded without copying an index result from another date

#### Scenario: Existing mismatched row is detected
- **WHEN** a normal read encounters a stored row whose key, payload, actual-date, or effective-date evidence is inconsistent
- **THEN** the row is treated as an integrity failure and is not returned, relabeled, migrated, deleted, or used as evidence by the read operation
