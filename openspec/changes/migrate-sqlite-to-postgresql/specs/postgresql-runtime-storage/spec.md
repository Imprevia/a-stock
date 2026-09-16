## Purpose

为市场环境服务提供可并发访问、可审计迁移且具备事务一致性的 PostgreSQL 运行时存储，替代应用进程之间共享 SQLite 文件的部署边界。

## ADDED Requirements

### Requirement: PostgreSQL runtime persistence
The system SHALL persist market snapshots, collection state, leases, materialized aggregates, limits facts, date-relabel audits, and timezone preferences in the configured PostgreSQL database during normal application operation.

#### Scenario: Service starts with PostgreSQL configuration
- **WHEN** `MARKET_ENVIRONMENT_DATABASE_URL` is configured and the database is reachable
- **THEN** the service initializes through PostgreSQL migrations and does not open or create a SQLite runtime database

#### Scenario: Database is unavailable
- **WHEN** the configured PostgreSQL endpoint cannot be reached or authentication fails
- **THEN** startup or the affected operation fails explicitly and does not silently fall back to a local SQLite file

### Requirement: Concurrent lease coordination
The system SHALL enforce one active dataset/date lease across independent application connections using transactional PostgreSQL locking and generation fencing.

#### Scenario: Dashboard and CronJob request the same dataset/date
- **WHEN** two PostgreSQL connections attempt to acquire the same dataset/date lease concurrently
- **THEN** at most one connection receives an active lease and the other receives a busy/retryable result without duplicate provider work

#### Scenario: Stale lease owner writes
- **WHEN** an expired or superseded lease owner attempts a fenced write
- **THEN** the write is rejected and the persisted lease-fence audit records the rejection

### Requirement: SQLite import verification
The system SHALL provide a controlled one-time import from an isolated SQLite copy into PostgreSQL with integrity and idempotence checks.

#### Scenario: Valid SQLite copy is imported
- **WHEN** the source passes integrity, schema, checksum, and date checks
- **THEN** durable history is imported transactionally, active lease ownership is not carried forward, and row/checksum verification is reported

#### Scenario: Import verification fails
- **WHEN** the source is corrupt, incomplete, inconsistent, or differs from the imported PostgreSQL counts/checksums
- **THEN** the import fails without marking the migration successful and leaves the source unchanged

### Requirement: PostgreSQL schema migration
The system SHALL apply versioned, idempotent PostgreSQL schema migrations before the application or scheduled collector writes data.

#### Scenario: Migration is rerun
- **WHEN** the same migration command runs against an already migrated database
- **THEN** it completes without destructive schema changes or duplicate rows

