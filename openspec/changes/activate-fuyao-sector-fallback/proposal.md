## Why

The production `sectors` task still ends as `failed-missing` when both Eastmoney hosts fail because the implemented Fuyao fallback is disabled and the runtime PostgreSQL store has no approved `fuyao-market-v2` sectors capability report. The existing probe writes only to isolated SQLite, so operators currently lack an auditable, fail-closed path for promoting reviewed evidence before enabling the fallback.

## What Changes

- Add a generic capability-report promotion CLI that is dry-run by default and writes exactly one reviewed report to the runtime PostgreSQL repository only with `--apply`.
- Require checksum, provider, dataset, revision, `eligible` status, redacted evidence, and target-store validation before promotion; register a strict `fuyao/sectors/fuyao-market-v2` evidence policy for exact-date and 320/320 coverage.
- Stage the reviewed immutable application image with Fuyao sectors still disabled before promotion, then stream the reviewed report over stdin to the running application Pod so the CLI uses only its existing PostgreSQL Secret environment and does not persist the report in the container.
- Add deployment values and operational steps for enabling only the Fuyao sectors fallback with revision `fuyao-market-v2`, while keeping schedule, Scrapling, and Eastmoney sector enrichment disabled.
- Add a config-only service rollout path that reuses the exact staged image for both enablement and rollback, rejects image build/import or image identity drift, and preserves CronJob absence, Secrets, PVCs, reports, snapshots, and task history.
- Prevent a disabled `component=all` stage from writing a trailing schedule-only Helm revision, and add a separately reviewed same-image sectors-off release repair operation for an interrupted stage whose live Deployment is already healthy but whose stored Helm manifest was narrowed. The repair performs one hook-free complete-release write and never rebuilds, transfers, imports, probes, promotes, or collects.
- Enforce the current Shanghai trading date and settlement time before a real probe can construct provider clients or create output artifacts; the first production collection remains settlement-gated and sectors-only.
- Define controlled after-hours probe, one-dataset collection, observation, and configuration-only rollback evidence without deleting reports, snapshots, task history, or PVCs.
- Preserve the existing HTTP API, `SectorRow`, snapshot schema, Eastmoney-first ordering, exact-date behavior, and unsupported-field `null` semantics.

## Capabilities

### New Capabilities

- `provider-capability-report-promotion`: Validate and promote one reviewed, redacted provider capability report into the runtime repository through an explicit dry-run/apply CLI boundary.

### Modified Capabilities

- `sector-data-collection-stability`: Make the controlled Fuyao sectors activation and rollback evidence explicit without changing its existing field or date contract.

## Impact

- Affects the market-environment CLI, provider capability repository/UoW wiring, Fuyao sectors Helm values, controlled Pod promotion/config-only rollout entrypoints, deployment tests, and the market-environment architecture/product/runbook/status documentation.
- Adds no public HTTP route, database table, frontend field, crawler runtime, or new provider dependency.
- Production probe, sectors-off image staging, same-image release repair when required, capability promotion, config-only enablement, collection, and conditional config-only rollback remain separately auditable operational actions; repository implementation and offline verification do not perform them.
