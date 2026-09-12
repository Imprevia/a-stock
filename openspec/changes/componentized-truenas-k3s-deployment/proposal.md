## Why

The supported TrueNAS k3s entry point can publish the complete market-environment release, but it does not expose safe, idempotent operations for the shared SQLite storage, Dashboard service, and after-market CronJob as separate components. Operators therefore cannot repair or bootstrap one layer without rerunning a broader release workflow, while the existing shared PVC and scheduling safety boundaries must remain intact.

## What Changes

- Add a component-aware TrueNAS k3s deployment workflow with `all`, `database`, `service`, and `schedule` targets.
- Make `all` apply components in dependency order: namespace/SQLite PVC, Dashboard service resources, then the scheduled-collection CronJob.
- Define the database component as the existing SQLite PVC at `/data/snapshots.sqlite3`; do not introduce PostgreSQL, a database container, or destructive PVC replacement.
- Add preflight, dependency, idempotence, and postcondition checks for each target so a component cannot silently run without its required namespace, PVC, image, or service resources.
- Keep scheduled collection fail-closed: component deployment may create a suspended CronJob, while production activation continues through the existing reviewed Gate B/Gate C workflow.
- Reuse the existing TrueNAS image build, checksum, transfer, k3s containerd import, Helm/Kubernetes access, and rollback safety boundaries where applicable.
- Add offline/fake-target tests and update the deployment runbook, architecture, repository guide, and active execution plan with component commands and recovery behavior.

## Capabilities

### New Capabilities

- `truenas-k3s-component-deployment`: Componentized and one-click deployment of the Dashboard service, shared SQLite PVC, and scheduled collection resources to the existing TrueNAS k3s cluster.

### Modified Capabilities

- None.

## Impact

- Deployment entry point and its environment/configuration validation.
- Helm/Kubernetes rendering or component manifests used by the TrueNAS release.
- Deployment-focused tests and fake SSH/kubectl/containerd fixtures.
- `docs/architecture.md`, `docs/runbooks.md`, `docs/repository-guide.md`, and the active execution-plan index.
- No market-environment API, provider, SQLite schema, or frontend behavior changes are required.

## Approval and execution boundaries

- Gate A is approved for repository implementation, offline/fake-target verification, and documentation synchronization only.
- Gate B (real TrueNAS read-only preflight, exact admission/canary, backup, or suspended CronJob work) and Gate C (real schedule activation) remain unauthorized for this change. They require separate action-level authorization and evidence.
- There is no frontend scope: this change does not alter Dashboard UI, browser flows, frontend API contracts, or market-environment application behavior. Work is limited to the deployment script, Helm rendering, deployment tests, and operator documentation.
- The execution order is serial: implementation, offline verification, independent test acceptance, then a read-only operations plan. `all` itself remains `database -> service -> schedule`.
