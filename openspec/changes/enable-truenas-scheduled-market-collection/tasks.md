## 0. Gate And Delivery Control

| Multica stage | OpenSpec tasks | Owner | Dependency | Activation state | Required evidence |
|---|---|---|---|---|---|
| Stage 1 - planning | 1.1-1.2 | Senior project manager | Gate A approval | Planning ready for review; 1.2 remains open until the clean-baseline staged gate | Approval trace, active plan registration, strict OpenSpec validation |
| Stage 2 - implementation (`GYT-47`) | 1.3, 2.1-2.5 | Senior backend engineer | Stage 1 accepted; reviewed clean commit/worktree | Backlog; do not start in the shared dirty tree | Documentation baseline, focused tests, reviewable implementation diff |
| Stage 3 - offline verification (`GYT-48`) | 3.1-3.5 | Senior backend engineer | `GYT-47` terminal and reviewed | Backlog | Render matrix, manifest invariants, fake-provider tests, full offline gates |
| Gate B preparation and validation | 4.1-5.7 | Unassigned | Stage 3 accepted plus separate read-only/Gate B authorization | Not authorized | Target preflight and bounded production-validation packet |
| Gate C activation | 6.1-6.3 | Unassigned | Gate B evidence accepted plus explicit Gate C authorization | Not authorized | Approval record and suspend-only production diff |
| Closeout | 7.1-7.3 | Assigned only after the preceding authorized stage | Applicable production evidence | Not started | Rollback, final facts, gates, and handoff |

There is **no frontend scope** in the approved change: no Dashboard UI, browser workflow, or frontend-facing API contract changes are planned. The existing senior frontend engineer therefore receives no child issue. Any later frontend need is a scope change and must be reviewed before assignment.

## 1. Approval And Documentation Baseline

- [x] 1.1 Obtain explicit Gate A approval for this OpenSpec change and verify the approval states that repository implementation is allowed but production access, provider calls, and production mutations are not. Approved on 2026-09-08 (Asia/Shanghai); evidence: `GYT-45` comments `01a07e3a-141c-71ac-b30b-0f06cf0c4a8b` and `01a07e3d-5a77-7972-a9cd-360c9d41dc84`.
- [ ] 1.2 Create and register `docs/exec-plans/active/enable-truenas-scheduled-market-collection.md` with `Stage`, `Status`, `Acceptance`, `Completion Evidence`, `Remaining Gaps`, and `Next Step`, then run the fast docs-contract gate before implementation edits. The plan is created in the shared worktree; keep this task open until it is carried to the reviewed clean implementation baseline and the staged fast gate is rerun there.
- [ ] 1.3 Reconcile the scheduling and compatibility facts in `README.md`, the market-environment product spec, `docs/architecture.md`, `docs/runbooks.md`, and `docs/status.md`; verify they distinguish Chart-wide Kubernetes 1.26 support from native CronJob-timezone 1.27+ support and record revision 7 as reported but pending live preflight confirmation.

## 2. Fail-Closed Helm Compatibility

- [ ] 2.1 Add explicit `native` and `controller` scheduled-collection timezone values and conditionally render `spec.timeZone` only for native mode; verify Helm keeps the Dashboard installable on Kubernetes 1.26 and emits the field for a valid 1.27+ native render.
- [ ] 2.2 Add template/deployment validation for Kubernetes version, allowed controller timezone, numeric `M H * * 1-5` schedule shape, strict post-settlement ordering, and Shanghai 16:30 controller equivalence; verify unknown strategies, native mode below 1.27, missing controller evidence, early/equal/complex schedules, and mismatched UTC/Shanghai schedules all fail before cluster submission.
- [ ] 2.3 Add ordered TrueNAS overlays for suspended, active, and off scheduling while preserving the baseline image, NodePort, manual-refresh setting, PVC, snapshot path, replica count, and security values; verify each effective Helm render differs only in the reviewed scheduling fields.
- [ ] 2.4 Extend the TrueNAS deployment entry point to accept the reviewed baseline plus one scheduling overlay, use the actual target Kubernetes version for rendering, report the effective Shanghai trigger, and separate read-only discovery from an explicit write-authorized server-dry-run mode without automatically creating a canary/validation Job or unsuspending; verify shell syntax and fixture-based command tests pass.
- [ ] 2.5 Document Kustomize as native-timezone/1.27+ unless separately redesigned, and verify no implementation path presents its unconditional `spec.timeZone` manifest as k3s 1.26 compatibility evidence.

## 3. Offline Verification

- [ ] 3.1 Add Helm render tests for disabled, suspended, and active modes across Kubernetes 1.26 controller-UTC, 1.26 controller-Shanghai, and 1.27+ native profiles; verify the default and a valid custom native post-settlement schedule, reject earlier/equal settlement times and list/range/step/multiple-time expressions, and assert exact cron/timeZone output plus every invalid configuration's failure message.
- [ ] 3.2 Extend deployment-manifest tests to verify the scheduled Pod retains the Dashboard image, PVC, snapshot path, non-root/read-only-rootfs/no-token security posture, `Forbid`, `backoffLimit: 0`, deadlines, Job history limits, and the `scheduled-refresh` command.
- [ ] 3.3 Run the existing fake-provider scheduled-refresh success, partial, failed, skipped, settlement, and lease-conflict tests and verify no real provider, production SQLite/PVC, or cluster is accessed.
- [ ] 3.4 Run Helm lint/template, the deployment test suite, strict OpenSpec validation, `python scripts/check-docs-contract.py --mode=full`, and `git diff --check`; record exact results and confirm the implementation diff contains no application API, provider, dataset, SQLite schema, frontend, or production-state change.
- [ ] 3.5 Submit the clean implementation diff and offline evidence for review and verify no production command is scheduled or run until Gate B is separately authorized.

## 4. Read-Only Production Preflight

- [ ] 4.1 Obtain explicit permission for the read-only TrueNAS preflight, then capture live Helm revision/history/full values, k3s version, CronJob/Job state, Deployment image tag/digest and security context, Service/NodePort, manual-refresh value, PVC/PV UID/capacity, snapshot path, and rollback baseline; verify reported revision 7 and all immutable assumptions against live evidence.
- [ ] 4.2 Prove a single active controller topology and capture reproducible TrueNAS host, k3s service, and running k3s process namespace/environment/timezone evidence; verify it is unambiguously `Etc/UTC` or `Asia/Shanghai`, otherwise record NO-GO and leave scheduling disabled.
- [ ] 4.3 Render and hash the exact ordered baseline-plus-suspended packet using the live Kubernetes version and prepare a Helm diff without submitting an admission request; verify the 1.26 controller render omits `spec.timeZone`, maps exactly to Shanghai 16:30, and proposes no Deployment, Service, PVC, manual-setting, or image change.
- [ ] 4.4 Record the exact server-dry-run resource/verb, no-provider canary manifest and predicted minute, one approved post-settlement validation date, operator, observer, backup target, provider-call boundary, stop thresholds, exact validation Job name, and exact-Job termination procedure; verify the packet is complete before requesting Gate B.

## 5. Suspended Release And One-Time Validation

- [ ] 5.1 Obtain explicit Gate B production-validation authorization covering the exact server-side dry-run, one no-provider scheduling canary, non-overwriting backup, suspended application CronJob release, and exactly one provider-backed Job; verify the authorization does not include recurring activation.
- [ ] 5.2 Submit only the recorded suspended resource through server-side dry-run with the authorized create/patch verb and capture admission output; verify no resource persists and stop on any mutation/defaulting outside the reviewed packet.
- [ ] 5.3 Run the bounded no-provider CronJob canary for one predicted controller-local minute, capture manifest/events/API creation time/UTC-and-Shanghai log, then suspend and remove only its exact resources after evidence capture; verify it mounts no PVC, has no service-account token or collection command, and produces exactly one Job at the predicted instant.
- [ ] 5.4 Create a consistent non-overwriting SQLite backup, record SHA-256, validate a recovery copy with `PRAGMA quick_check`, and verify the source PVC UID, file ownership, free-space threshold, and current Dashboard reads before applying the suspended application release.
- [ ] 5.5 Apply only the reviewed suspended overlay and verify the application CronJob exists with `suspend=true`, no scheduled Job was created, server-observed spec/image/PVC/security fields match the packet, and the Dashboard/NodePort/manual-collection behavior remains unchanged.
- [ ] 5.6 Before provider work, verify the CronJob image reference equals the Dashboard immutable tag, bind the running Dashboard `imageID` to the target containerd digest, freeze image import/re-tag operations, then clone exactly the approved Job and verify its `imageID` before collecting structured logs, dataset tasks, PVC/lease/SQLite/provider-free-read evidence.
- [ ] 5.7 Classify the validation as GO, explicit-partial-review, or NO-GO using the recorded date/timezone/security/storage/integrity/lease/provider/resource thresholds; verify no automatic full-batch retry occurs and suspend/disable immediately on any hard-boundary failure or single-dataset duration approaching the 600-second lease TTL.

## 6. Recurring Activation

- [ ] 6.1 Submit the one-time Job evidence for review, calculate the previous/next trigger and 1800-second missed-schedule window in UTC and Shanghai, and obtain Gate C authorization that explicitly selects next-schedule activation or one immediate catch-up; verify any `partial` disposition is written before changing `suspend`.
- [ ] 6.2 Lock the Gate B commit/chart/baseline/overlay hashes, run a fresh Helm diff, and apply the active overlay only when the diff contains exactly the application CronJob `/spec/suspend: true -> false`; verify any other drift invalidates Gate C and returns the change to review.
- [ ] 6.3 Observe the next controller-created Job and verify its creation time corresponds to 16:30 `Asia/Shanghai`, it does not overlap another Job, it preserves task-level failure isolation without Kubernetes retry, and the Dashboard reads the resulting exact-date local state without provider calls.

## 7. Rollback And Closeout

- [ ] 7.1 Render and review the off overlay and exact-Job incident commands before activation; on a hard stop, suspend/off first, terminate only the recorded active Job name/UID when required, and verify Pod termination, lease release/expiry, SQLite integrity, no new Job, and intact Dashboard/NodePort/manual/PVC/snapshot/audit behavior.
- [ ] 7.2 Update the product spec, architecture, runbook, status, and active plan with actual strategy, release revision, trigger evidence, task outcomes, rollback readiness, remaining gaps, and next step; verify no unobserved claim is recorded as fact.
- [ ] 7.3 Re-run strict OpenSpec validation, full docs-contract, deployment tests, and `git diff --check`, then attach the final evidence to review and verify the plan's `Status`, `Completion Evidence`, and `Remaining Gaps` match the actual production state.
