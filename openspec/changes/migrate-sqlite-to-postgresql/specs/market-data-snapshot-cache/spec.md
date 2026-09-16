## ADDED Requirements

### Requirement: Shared PostgreSQL snapshot store
The snapshot cache SHALL use the configured PostgreSQL database as the shared store for Dashboard and CronJob reads and writes while preserving exact-date isolation, checksums, freshness metadata, and failure-retention behavior.

#### Scenario: Dashboard reads a CronJob snapshot
- **WHEN** the CronJob commits a successful exact-date snapshot in PostgreSQL
- **THEN** the Dashboard reads the same snapshot without file copying or PVC synchronization

#### Scenario: PostgreSQL transaction conflict
- **WHEN** concurrent aggregate or snapshot commits conflict
- **THEN** the losing transaction is retried or reported as a conflict without partially publishing a materialized response

