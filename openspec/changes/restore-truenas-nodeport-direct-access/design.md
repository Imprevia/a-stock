## Context

See `proposal.md` for motivation. The TrueNAS k3s 1.26 release currently runs as Helm revision 4 with a ClusterIP Service, one non-root Dashboard replica, static PVC `a-stock-data`, SQLite at `/data/snapshots.sqlite3`, no Ingress, and scheduled collection disabled. Manual collection is enabled but currently reachable only through an authenticated SSH loopback tunnel. The application has no identity, TLS, role authorization, or request-level rate limit at its HTTP boundary.

The Helm Chart already supports `service.type=NodePort` and `service.nodePort`; existing deployment tests render `32001` on Kubernetes 1.26. The scope is therefore a version-controlled environment and documentation change followed by a separately approved production release, not a template or application feature.

## Goals / Non-Goals

**Goals:**

- Restore direct access at `http://192.168.1.20:32001/data-collection` with manual collection usable.
- Make the accepted unauthenticated exposure and its actual routing boundary explicit and auditable.
- Preserve the image, workload, storage, provider, scheduling, and collection invariants of revision 4.
- Make disabling writes the first and independently deployable response to misuse or runtime pressure.

**Non-Goals:**

- Add authentication, TLS, RBAC, API tokens, rate limiting, firewall rules, or public access.
- Change application code, API contracts outside the access-boundary requirements, SQLite schema, providers, datasets, or collection semantics.
- Enable scheduled collection or introduce an Ingress controller on k3s 1.26.
- Prove a client, device, or subnet restriction that the current NodePort does not enforce.

## Decisions

### 1. Use the existing Helm NodePort interface

The TrueNAS environment values will change only `service.type` from `ClusterIP` to `NodePort` and `service.nodePort` from `null` to `32001`. The reviewed values will continue to pin the current image, PVC, mount, replica count, disabled Ingress, and disabled CronJob.

This is preferred over modifying the Service template or applying an online `kubectl patch`: the Chart already renders the required Kubernetes 1.26 resource, and version-controlled values keep actual state reproducible. An authenticated reverse proxy remains the preferred long-term design but does not satisfy the accepted minimal direct-access scope.

### 2. Keep the HTTP write switch explicitly enabled

The values will retain exactly one `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1` entry. Direct access is requested specifically for the data-collection workflow; restoring NodePort while setting the switch to `0` would provide only read access and would not meet that requirement.

This means every routed client can trigger provider calls and SQLite writes. CORS, hidden UI controls, logs, leases, and provider serialization are not authorization. Existing leases and serialization limit duplicate work but do not prevent sequential abuse.

### 3. Define exposure by reachability, not intent

The accepted boundary is all networks that can route to `192.168.1.20:32001`. Implementation must verify that no router or firewall maps the port to a public interface, but this change does not add or assume network ACLs. Any future claim such as “only VLAN X” requires separate configuration and evidence.

Binding NodePort only to a selected node address was considered but rejected for this minimal change because kube-proxy node address behavior is cluster-specific and has not been verified. The required address is instead validated from the intended LAN client and checked for absence of known public forwarding.

### 4. Preserve runtime and storage state exactly

No image, replica, snapshot path, claim, schema, provider policy, settlement setting, security context, Ingress, or CronJob change is allowed in the same release. Before upgrade, capture revision 4 values and resource state and create a readable SQLite backup using a consistent backup mechanism.

The release uses the same PVC in place. A Helm diff that deletes or replaces the claim, changes the image, or enables another network/scheduled resource fails review.

### 5. Roll back capability before connectivity

On unexpected calls, provider pressure, SQLite lock contention, or PVC growth, first deploy `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` and verify collection POST returns 403 without provider activity. The NodePort may temporarily remain for read access. Then restore the revision 4 ClusterIP values or use the recorded Helm rollback if direct access must also be removed.

This two-step approach is preferred over immediately removing the Service because it stops writes through a small configuration change and leaves health/status visibility available. Rollback never uses Helm uninstall and never deletes or replaces the PVC.

## Risks / Trade-offs

- [Any routed client can invoke writes] -> Record explicit owner acceptance, prohibit public forwarding, monitor collection runs, and use the write switch as the immediate kill control.
- [Repeated valid requests can consume provider, CPU, bandwidth, and storage] -> Retain leases, serialization, bounded retries, single replica, and operational monitoring; disable writes when thresholds or abnormal activity are observed.
- [Traffic is plaintext and unauthenticated] -> Limit this design to the accepted LAN deployment and keep authenticated TLS ingress as the long-term replacement.
- [NodePort reachability can exceed the assumed LAN] -> Validate routing and router/firewall mappings during deployment; describe only observed reachability.
- [A broad Helm change could alter data state] -> Use the complete reviewed environment values, render and diff offline, pin the image/PVC, and take a consistent SQLite backup.
- [Rollback to an older revision could restore stale values] -> Prefer the explicit revision 4 protected values; verify the rendered diff and write-switch state before rollout.

## Migration Plan

1. Create an active execution plan and update product, architecture, runbook, and status facts before changing deployment configuration.
2. Capture revision 4 Helm values/history, Service, Deployment, endpoints, pod security, image identity, PVC identity/usage, and current ClusterIP behavior. Create and validate a consistent SQLite backup.
3. Change only the version-controlled TrueNAS values to `NodePort`/`32001`, retaining one enabled manual-refresh variable and all other revision 4 invariants.
4. Run strict OpenSpec validation, deployment tests, Helm lint/template against Kubernetes 1.26, Helm diff when available, docs-contract full, and whitespace checks.
5. In a separately approved maintenance step, verify `32001` is available, apply one Helm upgrade, and wait for the single Deployment to become ready.
6. From an intended LAN client, verify health, the data-collection page and status GET; submit one valid current-date dataset, expect HTTP 202, and poll it to a valid terminal state. Verify an unsupported historical request remains HTTP 422 and retained snapshots remain readable.
7. Inspect node/router exposure, logs, run/task activity, provider warnings, SQLite locks, and PVC growth during the observation window. Do not declare narrower reachability than the evidence proves.

Rollback:

1. Apply reviewed values with `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` and verify collection POST returns HTTP 403 without provider work.
2. If connectivity must also be removed, restore the revision 4 ClusterIP values or roll back to the recorded protected-access revision, then verify the Service has no nodePort.
3. Verify health, historical snapshot reads, PVC identity, SQLite integrity, replica count, image, and disabled scheduled collection. Retain the backup and collection audit records.
