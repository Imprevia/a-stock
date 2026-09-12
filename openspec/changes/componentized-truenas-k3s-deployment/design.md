## Context

The current TrueNAS workflow uses one Helm release for the Dashboard Deployment, Service, optional Ingress, SQLite PVC reference, and optional after-market CronJob. The release is reached through the existing SSH/kubeconfig and image-import path, and its scheduling operations already enforce typed values, immutable image checks, exact CronJob identity, and Gate B/Gate C authorization. TrueNAS may use a pre-provisioned static claim such as `a-stock-data`; in that case the chart must verify the claim rather than create or replace it.

The application has no database server abstraction: the Dashboard and collector CLI share `/data/snapshots.sqlite3` on a single-node RWO PVC. The deployment design must therefore preserve the existing release ownership and storage identity while adding component-level commands.

## Goals / Non-Goals

**Goals:**

- Add one canonical TrueNAS k3s entry point with `all`, `database`, `service`, and `schedule` component targets.
- Keep one Helm release and one reviewed values packet so component operations do not create competing ownership records.
- Make component operations idempotent, dependency-aware, observable, and safe to retry.
- Reuse the existing Podman build, checksum, SSH/SCP, containerd import, rollout, and scheduling guard behavior.
- Preserve the SQLite PVC and provide clear behavior for both chart-managed claims and reviewed `existingClaim` values.

**Non-Goals:**

- Adding PostgreSQL, another database container, a SQLite-to-PostgreSQL migration, or a schema change.
- Supporting multi-replica or multi-node SQLite deployments.
- Bypassing Gate B/Gate C or providing a raw CronJob activation/patch path.
- Replacing the existing Helm release with several independently owned Helm releases.
- Changing market-environment API, provider, collection, or frontend behavior.

## Decisions

### 1. Extend the canonical TrueNAS entry point

The component selector will be added to `scripts/deploy-truenas-k3s.sh` rather than introducing a second production entry point. This keeps SSH tunneling, environment validation, image provenance, release naming, and fail-closed scheduling checks in one audited path. Existing invocations retain their current behavior.

Alternatives considered:

- A second wrapper script would duplicate safety-sensitive checks and could drift from the supported release workflow.
- A local-only kubectl script would not cover the TrueNAS image transfer and private API boundary.

### 2. Keep one Helm release and render a complete reviewed packet

The chart will expose explicit component intent while the entry point always computes a complete desired release packet from reviewed values. A component operation changes only the selected component and its declared prerequisites; other components are retained from the same reviewed profile rather than inherited from opaque Helm history. Helm remains the owner of resources, preventing conflicts between filtered `kubectl apply` output and later Helm upgrades.

Alternatives considered:

- Filtering `helm template` output by Kubernetes kind and applying it with kubectl would leave Helm history and live ownership out of sync.
- Separate database/service/schedule Helm releases would require resource renaming and a risky migration from the existing `a-stock` release.

### 3. Treat the database component as storage assurance

The database target ensures the configured namespace and SQLite PVC contract. For a chart-managed claim it may create the reviewed RWO PVC; for a TrueNAS `persistence.existingClaim` it performs read-only identity, binding, capacity, and mount-path verification and never creates, deletes, replaces, or resizes that claim. The operation does not start a database process.

### 4. Separate image work by component

`all` and `service` perform the existing immutable image build/smoke/checksum/transfer/import flow. `database` performs no image work. `schedule` reuses the reviewed image already present in the target runtime and fails if the exact image cannot be proven. This prevents a storage-only repair from changing application code and prevents a schedule-only action from silently changing the collector image.

### 5. Keep scheduling fail-closed

The schedule target first renders or verifies the suspended/disabled state from the reviewed profile. Creating a suspended application CronJob and activating it remain distinct operations: the former uses the existing reviewed suspended-release path, and the latter uses the existing Gate C suspend-only diff and authorization. A boolean flag or `all` operation without those authorizations cannot create an active CronJob.

### 6. Enforce dependency and postcondition checks

Before a service write, the entry point verifies the namespace and PVC and records the target image. Before a schedule write, it additionally verifies a ready Dashboard release or an explicitly reviewed service prerequisite, the shared PVC, and image identity. After each write it reads server-observed resource state, waits for rollout where applicable, and emits component-specific success/failure records. An unexpected active or identity-drifted CronJob transfers control to the existing exact-resource disable/rollback procedure.

### 7. Test without requiring production access

The implementation will extend deployment manifest and TrueNAS guard tests with fake Helm, SSH, kubectl, and containerd commands. Tests will assert component ordering, skipped image work, prerequisite failures before writes, PVC identity preservation, schedule authorization rejection, idempotent reruns, and partial `all` outcomes. Real TrueNAS, production Kubernetes, provider calls, and production SQLite remain outside local verification.

### 8. Delivery sequencing and ownership

The 21 tasks are delivered through four serial stages. A senior backend engineer owns tasks 1.1-3.7 and the offline evidence tasks 4.1-5.3; a senior test engineer independently owns acceptance task 6.1; a senior operations specialist owns the read-only handoff plan in task 6.2. A senior frontend engineer has no assigned work because the change does not modify dashboard UI, browser flows, or frontend API contracts. Stage 2, 3, and 4 remain parked until the preceding stage reaches a terminal accepted state. Gate A permits only repository and offline work; Gate B and Gate C remain separate unauthorized production gates.

## Risks / Trade-offs

- **[Helm packet drift]** Component operations could accidentally inherit live release values. **Mitigation:** require a complete reviewed baseline/profile, render once into a read-only packet, hash it, and reject unknown or conflicting values before any target access.
- **[Existing static PVC mismatch]** A claim may be bound under a different name or storage class than the profile. **Mitigation:** verify exact claim UID/volume/access mode/path and fail closed; never auto-rebind or resize.
- **[Schedule safety regression]** A component flag could be mistaken for activation authorization. **Mitigation:** preserve typed `enabled/suspend` validation and route all creation/activation through the existing reviewed scheduling operations.
- **[Partial all-components failure]** Storage may succeed while service or schedule fails. **Mitigation:** report each component independently, retain successful non-destructive resources, and print the exact retry target.
- **[Single-node SQLite limits]** Componentization does not remove SQLite locking or RWO constraints. **Mitigation:** keep one replica/node and document PostgreSQL as a separate future architecture change.

## Migration Plan

1. Capture the current release values, exact Deployment/Service/CronJob state, PVC UID/volume, and target Kubernetes version using the existing read-only discovery path.
2. Run the database component against the reviewed baseline; on an existing `existingClaim`, expect verification-only success and no PVC mutation.
3. Run the service component with the immutable image packet, wait for the single Dashboard rollout, and verify `/api/health` and PVC continuity.
4. Run the schedule component in disabled or suspended mode. If production scheduling is required, continue with the already reviewed suspended-release, evidence, and Gate C activation sequence; do not use a raw patch or direct apply.
5. For rollback, disable/suspend the exact CronJob first when present, then use the existing application rollback workflow. Preserve the PVC and SQLite snapshots throughout; no uninstall or implicit storage deletion is introduced.
