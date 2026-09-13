## Execution routing

- Gate A is approved for repository implementation, offline/fake-target verification, and documentation only. Gate B real TrueNAS preflight/canary/backup/suspended CronJob work and Gate C activation remain unauthorized.
- Serial stages: Stage 1 (1.1-3.7) senior backend engineer; Stage 2 (4.1-5.3) senior backend engineer; Stage 3 (6.1) senior test engineer; Stage 4 (6.2) senior operations specialist. Stage 2-4 are parked until the previous stage is accepted.
- No frontend work is in scope because this change does not alter Dashboard UI, browser flows, frontend API contracts, or application/provider behavior.
- The active execution plan records the dependency graph, relative schedule, risk register, child issue routing, and required evidence; these task checkboxes remain the implementation source of truth.

### Stage 1 rework state

The first Stage 1 delivery was independently rejected. Tasks 1.2 and 3.2-3.7 are reopened until the implementation proves all of the following on a deliverable exact commit:

- The baseline fixture is consumed by tests that reject missing or conflicting release, namespace, PVC, image, topology, and scheduling invariants.
- Independent `database`, `service`, and `schedule` operations observe and validate their declared namespace/PVC/service/image prerequisites before reporting success; a render-only early exit is not a dependency check.
- `service` preserves `component=service` in the final pre-write render and Helm write, rather than falling back to the chart default `all`.
- `schedule` validates and injects the reviewed frozen image repository/tag before rendering, and proves the target runtime digest before any schedule write.
- Reviewed schedule operations preserve `component=schedule` through the existing suspended-release, activation, disable, and recovery guards without upgrading unrelated service or PVC resources.
- `all` performs observable `database -> service -> schedule` orchestration with prerequisite barriers, per-component completed/failed states, PVC preservation, and one actionable retry target; a summary string is not sufficient evidence.
- Focused fake-target tests cover those paths, are reproducible in a declared test environment, and the resulting task commit is clean and reviewable. Stage 2 remains parked until independent Stage 1 acceptance.

## 1. Scope and baseline

- [x] 1.1 Create `docs/exec-plans/active/componentized-truenas-k3s-deployment.md` with Stage, Status, Acceptance, Completion Evidence, Remaining Gaps, and Next Step, and register it in `docs/exec-plans/active/_index.md`; verify the plan fields and index entry are present before code changes.
- [x] 1.2 Capture the reviewed TrueNAS baseline assumptions in fixtures (release name/namespace, existing claim option, image identity, one-replica topology, and scheduling state); verify the fixture rejects missing or conflicting storage and schedule invariants.

## 2. Chart and component rendering

- [x] 2.1 Add explicit component intent values and template guards for database, service, and schedule resources while preserving existing default rendering; verify `helm lint --strict` and a values matrix render produce the expected resource sets.
- [x] 2.2 Implement chart-managed versus `persistence.existingClaim` behavior for the database component; verify a chart-managed PVC can be created, an existing claim is verification-only, and no render path deletes, replaces, or resizes a claim.
- [x] 2.3 Preserve service invariants (single replica, shared snapshot path, probes, non-root/read-only-rootfs security, NodePort/ClusterIP and Ingress compatibility); verify rendered Deployment, Service, Ingress, and volume fields against the existing manifest tests.
- [x] 2.4 Preserve scheduled-collection parity and fail-closed defaults, including shared image/PVC, Shanghai timezone, `Forbid`, bounded deadlines, and suspended/disabled states; verify native/controller render validation and unauthorized active values fail before a write.

## 3. TrueNAS component entry point

- [x] 3.1 Extend `scripts/deploy-truenas-k3s.sh` argument parsing and help output with `all`, `database`, `service`, and `schedule` component selection while keeping legacy invocations compatible; verify `bash -n` and invalid-component tests.
- [x] 3.2 Add component-aware preflight and dependency checks that run before target writes (namespace, PVC contract, release/service readiness, image availability, Kubernetes version, and scheduling state); verify fake-target tests show no write command after each failed prerequisite.
- [x] 3.3 Implement ordered `all` orchestration (`database -> service -> schedule`) and component-specific execution summaries; verify fake kubectl/Helm traces prove ordering, idempotent reruns, and distinct completed/failed component reporting.
- [x] 3.4 Reuse the existing immutable image build, smoke test, checksum, SCP, and k3s containerd import path only for `all`/`service`, skip it for `database`, and require a proven frozen image for `schedule`; verify command-trace tests and digest mismatch failures.
- [x] 3.5 Render and apply a complete reviewed Helm packet for each component operation without introducing competing Helm ownership or inheriting opaque release values; verify rendered hashes, release identity, and component-specific desired state in fake Helm tests.
- [x] 3.6 Integrate schedule operations with the existing suspended-release, activation, and disable/rollback authorization guards; verify unauthorized activation is rejected before any CronJob write and unexpected active/drifted resources route to the exact-resource recovery path.
- [x] 3.7 Add server-observed postconditions, rollout/health checks, resource identity reporting, and non-destructive failure handling; verify service timeout, partial `all`, and PVC-preservation scenarios exit nonzero with actionable retry guidance.

## 4. Automated verification

- [x] 4.1 Extend deployment manifest tests for component resource sets, dependency failures, PVC identity preservation, image reuse, schedule suspension, and security parity; verify the focused deployment suite passes with no production network access.
- [x] 4.2 Extend TrueNAS guard tests for component ordering, skipped image work, Helm packet ownership, idempotence, authorization boundaries, and failure postconditions; verify the focused guard suite and existing scheduling regression suite pass.
- [x] 4.3 Add shell/Python syntax, Helm lint/template, and fake SSH/kubectl/containerd integration checks to the documented offline validation commands; verify all commands are reproducible without TrueNAS, real providers, or production SQLite/PVC access.

## 5. Documentation and operator workflow

- [x] 5.1 Update `docs/runbooks.md` with prerequisites, environment variables, all-components and independent component commands, dependency behavior, suspended scheduling semantics, and rollback steps; verify every executable example passes the repository command audit.
- [x] 5.2 Update `docs/architecture.md` with the component dependency graph, single Helm release ownership, shared SQLite PVC boundary, image flow, and schedule authorization boundary; verify the architecture text matches rendered manifests and script behavior.
- [x] 5.3 Update `docs/repository-guide.md`, README deployment guidance, `docs/status.md`, and the active plan with the new entry point and code-document mappings; verify docs-contract fast/full checks pass or record an explicit unrelated blocker.

## 6. Acceptance and handoff

- [x] 6.1 Run the complete offline acceptance matrix (all/database/service/schedule, first install and rerun, chart-managed and existingClaim storage, suspended and unauthorized active schedule); verify expected resource sets, ordering, postconditions, and exit codes.
- [x] 6.2 Record Completion Evidence, Remaining Gaps, and Next Step in the active plan, including the lack of real TrueNAS/provider execution and any required maintenance-window authorization; verify the plan status and OpenSpec strict validation report complete artifacts.
