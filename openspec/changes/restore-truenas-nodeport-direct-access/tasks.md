## 1. Establish the documented change boundary

- [x] 1.1 Create an active execution plan for the direct-access deployment, add it to `docs/exec-plans/active/_index.md`, and verify all required plan fields pass the docs-contract gate.
- [x] 1.2 Update `docs/product-specs/market-environment-dashboard.md` to record the explicitly accepted unauthenticated NodePort behavior and verify it does not describe NodePort as authentication or client authorization.
- [x] 1.3 Update `docs/architecture.md`, `docs/runbooks.md`, and `docs/status.md` with the reachable-network boundary, plaintext/write risks, deployment validation, monitoring, and configuration-first rollback; verify the documents consistently identify revision 4 ClusterIP as the rollback baseline.

## 2. Prepare the version-controlled deployment configuration

- [x] 2.1 Update the TrueNAS environment values to set `service.type=NodePort` and `service.nodePort=32001`, retaining exactly one `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1` entry; verify the rendered Service and Deployment contain those exact values.
- [x] 2.2 Preserve the immutable image, one replica, `a-stock-data` claim, `/data/snapshots.sqlite3` path, security context, disabled Ingress, and disabled scheduled collection; verify a Helm render diff contains no changes to those invariants and no PVC deletion or replacement.
- [x] 2.3 Update deployment manifest tests to cover the complete TrueNAS direct-access values combination, environment-variable uniqueness, PVC stability, Kubernetes 1.26 compatibility, and absence of unintended Ingress/CronJob resources; verify the targeted test module passes.

## 3. Complete offline gates and production baseline

- [x] 3.1 Run strict OpenSpec validation, Helm lint/template for Kubernetes 1.26, deployment tests, the full docs-contract gate, and `git diff --check`; record every command and result in the active plan.
- [ ] 3.2 Before deployment, verify node port `32001` is available and capture Helm revision 4 values/history, Service, Deployment, endpoints, image, pod security, PVC identity/usage, and scheduled-collection state; attach or record the evidence in the active plan.
- [ ] 3.3 Create a consistent SQLite backup, verify its integrity/readability and recovery location, and confirm the planned Helm diff neither deletes nor replaces the PVC before authorizing rollout.

## 4. Deploy and verify direct access

- [ ] 4.1 In the approved maintenance step, apply one Helm upgrade from the reviewed values and wait for the single Dashboard Deployment to become ready; verify the running image, replica, security context, claim, mount path, and disabled scheduled collection match the baseline.
- [ ] 4.2 From an intended LAN client, verify `http://192.168.1.20:32001/api/health`, `/data-collection`, and the provider-free collection status GET succeed, and verify the Service reports NodePort `32001` without an Ingress.
- [ ] 4.3 Submit one supported current-date dataset request, verify HTTP 202 and poll it to a valid terminal state, then verify an unsupported historical request remains HTTP 422 and existing snapshots and collection history remain readable.
- [ ] 4.4 Inspect node and router/firewall mappings for public exposure and record only the reachability actually demonstrated; fail acceptance if `32001` is intentionally mapped to a public interface or if a narrower client/subnet restriction is claimed without evidence.
- [ ] 4.5 Observe collection runs, provider warnings/rate limits, SQLite locks, task duration, and PVC growth for the agreed window; record the final release revision and evidence in the active plan and keep the issue in progress until verification is complete.

## 5. Exercise configuration-first rollback

- [ ] 5.1 Render and retain rollback values with `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`; apply them during the rollback exercise and verify collection POST returns HTTP 403 without provider work while health and snapshot reads remain available through NodePort.
- [ ] 5.2 Restore the revision 4 ClusterIP values or recorded Helm revision and verify the Service has no nodePort while the PVC identity, SQLite integrity, image, replica count, and historical data remain unchanged.
- [ ] 5.3 Reapply the accepted direct-access state only with explicit deployment authorization, then update the active plan Status, Completion Evidence, Remaining Gaps, and Next Step and verify the full docs-contract gate passes.
