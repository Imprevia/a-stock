## 1. Confirm the access and operational decisions

- [x] 1.1 Obtain user approval for the recommended ClusterIP plus temporary authenticated tunnel model and the removal of direct LAN access on NodePort `32001`.
- [x] 1.2 Identify authorized SSH/kubeconfig holders and restrict SSH forwarding to the k3s API and application ClusterIP with `PermitOpen`, loopback binding, and no gateway or agent forwarding.
- [x] 1.3 Agree on the maintenance window, maximum interruption, observation period, PVC free-space threshold, initial datasets/date, and provider rollback thresholds.
- [x] 1.4 Define the SQLite backup location, retention, encryption, restore owner, and recovery validation.
- [x] 1.5 If persistent read access is required, stop this implementation path and create a separate authenticated reverse-proxy design covering identity, TLS, path authorization, secrets, and operations.

## 2. Establish documentation and baseline evidence

- [x] 2.1 Create an active exec plan and add it to `docs/exec-plans/active/_index.md` before any Helm or deployment change.
- [x] 2.2 Update `docs/product-specs/market-environment-dashboard.md`, `docs/architecture.md`, and `docs/runbooks.md` with the approved access boundary, deployment flow, verification, and rollback.
- [x] 2.3 Capture `helm get values --all`, `helm history`, image identity, Deployment, Service, endpoints, PVC, pod security context, scheduled-collection state, and current 403 behavior.
- [x] 2.4 Create a consistent SQLite backup and verify it is readable; record PVC usage and confirm the existing claim name and reclaim behavior.

## 3. Prepare the reviewed Helm configuration

- [x] 3.1 Update the version-controlled TrueNAS environment values to preserve the current immutable image, existing PVC, single replica, disabled Ingress, and disabled k3s 1.26 CronJob.
- [x] 3.2 Set the Service to ClusterIP with no nodePort and inject exactly one `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1` environment variable into the Dashboard container.
- [x] 3.3 Add or update deployment manifest tests for the ClusterIP/manual-refresh combination, PVC stability, environment-variable uniqueness, and absence of unintended Ingress/CronJob resources.
- [x] 3.4 Run Helm lint/template and review the rendered diff; prove the PVC claim, mount path, image, security context, and replica count remain unchanged.
- [x] 3.5 Run the full docs-contract gate and record results in the active plan.

## 4. Deploy in the approved maintenance window

- [x] 4.1 Execute one Helm upgrade using the reviewed environment values and wait for the single Dashboard Deployment to become ready.
- [x] 4.2 Verify health, pod identity/security, image, PVC mount, SQLite readability, logs, and that scheduled collection remains disabled.
- [x] 4.3 Verify the Service is ClusterIP, has no nodePort, and `192.168.1.20:32001` no longer serves the application.
- [x] 4.4 Verify the runtime manual-refresh variable is enabled exactly once without exposing its endpoint through any other Service, Ingress, host port, or proxy.

## 5. Validate the protected manual workflow

- [x] 5.1 Establish port-forward access using the approved least-privilege identity and bind only to `127.0.0.1`; if needed, carry it through the approved SSH channel.
- [x] 5.2 Verify health and collection status GET through the tunnel, and confirm the UI reports manual collection enabled.
- [x] 5.3 Trigger one approved, date-valid dataset; expect 202, poll the run to a terminal state, and inspect task status, source, quality, warnings, duration, logs, and PVC growth.
- [x] 5.4 Trigger the approved five-dataset run; verify independent task commits, partial/degraded handling, failed-retained behavior, provider rate-limit controls, and materialized aggregate readability.
- [x] 5.5 Verify a latest-only historical request returns 422 and a duplicate active dataset/date request does not create uncontrolled provider calls.
- [x] 5.6 Close the tunnel and prove the local listener disappears and no anonymous LAN write path exists.

## 6. Exercise rollback and finish evidence

- [x] 6.1 Set manual refresh to disabled, roll out, and verify collection POST returns 403 without provider calls while health and snapshot GET remain available.
- [x] 6.2 If required, roll back to the recorded Helm revision and restore NodePort only after the 403 check; verify the PVC and historical data remain intact.
- [x] 6.3 Reapply the approved final state only if rollback rehearsal and user approval permit it; otherwise leave the safe disabled state.
- [x] 6.4 Update the active plan Status, Completion Evidence, Remaining Gaps, and Next Step with release revision, commands, API outcomes, provider quality, PVC evidence, and any deferred authentication work.

> Implementation status: all approved tasks completed; production is on Helm revision 4 with protected manual collection enabled.
