## Why

The user requires direct LAN access to `http://192.168.1.20:32001/data-collection` without an SSH tunnel and has explicitly accepted that any client able to reach that endpoint can trigger unauthenticated provider work and SQLite writes. The deployed ClusterIP-only access model therefore needs an explicit, reversible scope change rather than an undocumented production override.

## What Changes

- **BREAKING** Restore the TrueNAS application Service as a fixed NodePort on `32001`, replacing the current ClusterIP-only operator access boundary.
- Keep manual collection enabled so the direct `/data-collection` page and collection POST operations remain usable from the reachable LAN.
- Define exposure honestly as every network able to route to the node port; prohibit public port forwarding and do not claim device or subnet restriction without separately verified firewall or ACL controls.
- Preserve the deployed image, single replica, existing PVC and SQLite path, disabled Ingress and scheduled collection, provider controls, date validation, lease behavior, and failure-retention semantics.
- Require a configuration-first rollback that disables manual collection before removing or retaining NodePort exposure, without deleting or replacing the PVC.
- Update architecture, product, runbook, status, execution-plan, and deployment-test evidence before production deployment.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-data-collection-management`: Permit an explicitly accepted unauthenticated NodePort deployment for manual collection, while defining its exposure, invariant-preservation, verification, and rollback requirements.

## Impact

- Deployment configuration: the reviewed TrueNAS values under `deploy/truenas/` will set `service.type=NodePort` and `service.nodePort=32001` while retaining exactly one enabled `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` entry.
- Network and security: clients able to route to `192.168.1.20:32001` can read the Dashboard and invoke collection POST operations without identity, TLS, or request-level authorization. NodePort is connectivity, not an access-control boundary.
- Runtime and data: no application code, API shape, image, schema, PVC, SQLite path, replica count, provider policy, or collection coordinator behavior changes.
- Documentation and tests: `docs/product-specs/market-environment-dashboard.md`, `docs/architecture.md`, `docs/runbooks.md`, `docs/status.md`, an active execution plan, and Helm render tests must describe and prove the accepted deployment state.
- Operations: implementation requires a separate approved apply/deployment phase. This proposal does not change Helm configuration, cluster resources, or SSH settings.
