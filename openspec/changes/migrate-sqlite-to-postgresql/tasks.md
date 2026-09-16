## 1. Dependencies and database configuration

- [x] 1.1 Add SQLAlchemy 2, psycopg 3, Alembic and PostgreSQL test dependencies; update Docker/runtime dependency checks.
- [x] 1.2 Define database URL/configuration loading, pool and timeout settings, and fail-closed startup behavior.

## 2. PostgreSQL storage and schema

- [x] 2.1 Add Alembic environment and initial PostgreSQL schema for snapshots, collection state, leases/fencing, aggregates, limits facts, sessions, audits, and timezone preferences.
- [x] 2.2 Refactor `SnapshotStore` and `TimezonePreferenceStore` to SQLAlchemy Core/PostgreSQL while preserving public methods and response semantics.
- [x] 2.3 Implement PostgreSQL lease locking, generation fencing, CAS aggregate updates, explicit UTC/date/JSONB conversions, and transaction boundaries.
- [x] 2.4 Update date relabel and migration helpers to use the shared PostgreSQL transaction boundary instead of SQLite internals.

## 3. SQLite import and operational CLI

- [x] 3.1 Add read-only SQLite backup/integrity inspection and PostgreSQL import command with dry-run/apply modes.
- [x] 3.2 Add idempotent import, active-lease expiry conversion, table/checksum/date verification, and structured failure output.
- [x] 3.3 Add migration/rollback runbook commands and preserve old SQLite PVC/backup as detached archival data.

## 4. Helm/k3s deployment

- [x] 4.1 Add PostgreSQL StatefulSet, ClusterIP Service, retained RWO PVC, readiness/liveness probes, and values/schema validation.
- [x] 4.2 Add existingSecret contract and inject PostgreSQL configuration into Dashboard Deployment and collection CronJob.
- [x] 4.3 Remove SQLite path/PVC mounts from application workloads and update component dependency/render guards and migration Job ordering.

## 5. Tests and documentation

- [x] 5.1 Add PostgreSQL unit/integration tests for schema migration, concurrent leases, aggregate CAS, collection isolation, date relabel, and timezone audit.
- [x] 5.2 Add SQLite import fixture tests for checksum mismatch, corruption, idempotence, active leases, and rollback-safe failure.
- [x] 5.3 Update deployment manifest tests, CI PostgreSQL service, architecture/runbook/README/status and affected active plans.
- [x] 5.4 Run pytest, CLI rules/docs checks, Helm lint/template, OpenSpec strict validation, docs-contract full, and record any unrun production/provider checks.
