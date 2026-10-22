## Why

Production currently exposes only the Hermes automation write path. Operators need the existing UI/API manual collection controls available at the same time for targeted recovery, without pausing the scheduled Hermes job or rebuilding the application image.

## What Changes

- Permit an explicitly approved production deployment to run with both automation and manual collection gates enabled.
- Add a same-image, hook-free, fail-closed rollout path that changes only `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` from `0` to `1` while preserving automation, Hermes, storage, credentials, provider policy, and scheduling retirement.
- Require zero active collection writers at cutover and retain the existing dataset/date lease and idempotency controls when later manual and automatic requests overlap.
- Preserve the existing `manual 1→0` non-destructive rollback and make enabling the gate provider-free.
- Record that the current internal NodePort remains unauthenticated and that concurrent enablement is an explicitly accepted trusted-network exception, not authentication.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-data-collection-management`: allow an explicitly approved trusted-network deployment to enable manual collection concurrently with automation, with a reviewed same-image rollout and fail-closed rollback.

## Impact

- Deployment controls: `scripts/deploy-truenas-k3s.sh`, `scripts/validate-scheduling-packet.py`, TrueNAS deployment environment and focused guard tests.
- Runtime configuration: one existing Deployment environment value; no API, schema, provider, database, image, Secret, PVC, CronJob, or Hermes job change.
- Documentation: product specification, architecture, runbook, repository guide, status, and the active execution plan.
- Production: one hook-free Helm revision after read-only drift and writer checks; enabling does not submit a collection request.
