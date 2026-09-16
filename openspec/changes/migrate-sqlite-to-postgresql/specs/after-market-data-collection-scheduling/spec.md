## ADDED Requirements

### Requirement: PostgreSQL-backed scheduled results
Scheduled collection SHALL write runs, tasks, snapshots, warnings, facts, and materialized aggregates to the shared PostgreSQL database used by the Dashboard.

#### Scenario: Dashboard and CronJob run concurrently
- **WHEN** the Dashboard serves reads while the scheduled collector writes a dataset
- **THEN** both workloads use PostgreSQL transactions, neither mounts a SQLite file, and the Dashboard continues serving the last committed aggregate

#### Scenario: Scheduled workload has no database PVC mount
- **WHEN** the scheduled Helm deployment is rendered
- **THEN** the CronJob contains only temporary writable storage needed by the process and a PostgreSQL connection contract, with no snapshot SQLite PVC mount

