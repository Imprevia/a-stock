## Why

TrueNAS k3s currently has no market-data CronJob because the production Helm values disable scheduled collection. Enabling the existing template directly is unsafe: the target cluster is k3s 1.26, while the template unconditionally emits `spec.timeZone` and the repository has conflicting 1.26/1.27 compatibility claims.

## What Changes

- Add an explicit, fail-closed scheduling-timezone strategy: clusters with native CronJob timezone support use `spec.timeZone`, while k3s 1.26 may omit that field only after the controller timezone is verified and the cron expression is expressed in that timezone.
- Make Helm rendering, TrueNAS environment values, deployment preflight, tests, and operator documentation agree on the selected strategy; an unverified 1.26 timezone or non-equivalent schedule must block enablement.
- Stage TrueNAS activation as an authorized no-provider scheduling canary, a suspended application CronJob, then one approved provider-backed Job using the shared image/PVC, and finally a separately approved unsuspend after trigger semantics, logs, provider access, SQLite integrity, and exact-date results pass.
- Preserve the existing five-dataset coordinator, CLI, failure isolation, `Forbid` concurrency policy, zero automatic retries, single-node SQLite boundary, Dashboard/NodePort behavior, and manual-collection setting.
- Define rollback as suspend/disable first while preserving the Deployment, PVC, snapshots, and audit records; do not uninstall the release or perform a destructive data rollback.
- Require explicit user approval of these planning artifacts before implementation, and a second explicit production authorization after offline implementation evidence and a read-only target preflight.

## Approval Record

- Gate A was approved on 2026-09-08 (Asia/Shanghai) in parent issue `GYT-45`: member comment `01a07e3a-141c-71ac-b30b-0f06cf0c4a8b` replied "批准" to the architecture-review thread, and follow-up comment `01a07e3d-5a77-7972-a9cd-360c9d41dc84` recorded the decision.
- This approval authorizes repository implementation and offline verification only. It does not authorize production access or preflight, a server-side dry-run, the no-provider canary, a SQLite backup, a suspended application CronJob, any provider-backed Job, or recurring activation.
- Delivery is governed by `docs/exec-plans/active/enable-truenas-scheduled-market-collection.md`. Gate A repository work is assigned to the existing senior backend engineer through serial backlog stages; there is no frontend scope because no UI, browser workflow, or frontend API contract changes are planned.
- Gate B and Gate C remain unapproved. Later-stage work must not be created or promoted as executable work until its explicit authorization is recorded.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `after-market-data-collection-scheduling`: Add deterministic Kubernetes 1.26 timezone compatibility, fail-closed configuration validation, and staged production activation requirements to the existing scheduled-collection contract.

## Impact

- Deployment configuration and validation: `deploy/helm/a-stock/`, `deploy/truenas/`, `scripts/deploy-truenas-k3s.sh`, and `tests/test_deployment_manifests.py`.
- Documentation: a new active execution plan plus `README.md`, `docs/product-specs/market-environment-dashboard.md`, `docs/architecture.md`, `docs/runbooks.md`, and `docs/status.md` before implementation changes.
- Production boundary: the current Helm revision, image, Service, Deployment, PVC, and controller timezone must be captured during a later read-only preflight; production changes remain out of scope until separately authorized.
- No application API, dataset, provider, SQLite schema, or frontend behavior changes are planned.
