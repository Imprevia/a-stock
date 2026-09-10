## Why

The issue reports that TrueNAS k3s currently has no market-data CronJob and that its production Helm values disable scheduled collection; those live facts remain unverified until the permitted read-only preflight. Enabling the existing template directly is unsafe: the reported target is k3s 1.26, while the template unconditionally emits `spec.timeZone` and the repository has conflicting 1.26/1.27 compatibility claims.

## What Changes

- Add an explicit, fail-closed scheduling-timezone strategy: clusters with native CronJob timezone support use `spec.timeZone`, while k3s 1.26 may omit that field only after the controller timezone is verified and the cron expression is expressed in that timezone.
- Make Helm rendering, TrueNAS environment values, deployment preflight, tests, and operator documentation agree on the selected strategy; an unverified 1.26 timezone or non-equivalent schedule must block enablement.
- Stage TrueNAS activation as an authorized no-provider scheduling canary, a suspended application CronJob, then one approved provider-backed Job using the shared image/PVC, and finally a separately approved unsuspend after trigger semantics, logs, provider access, SQLite integrity, and exact-date results pass.
- Preserve the existing five-dataset coordinator, CLI, failure isolation, `Forbid` concurrency policy, zero automatic retries, single-node SQLite boundary, Dashboard/NodePort behavior, and manual-collection setting.
- Define rollback as suspend/disable first while preserving the Deployment, PVC, snapshots, and audit records; require a separately namespaced reference whose digest is auditably bound to the exact disable operation and frozen packet, and keep an exact-resource fail-safe active until absent/suspended is proven. Do not uninstall the release or perform a destructive data rollback.
- Treat executable deployment documentation as part of the release boundary: CommonMark/Bash parsing must fail closed on brace/glob expansion, `eval`, stdin-fed shells, command-resolution mutation, dynamic executable/action construction, and unknown Helm plugins/actions.
- Make the Chart and every generic install, upgrade, or application rollback fail closed with scheduled collection disabled and suspended; route all documented production writes through `scripts/deploy-truenas-k3s.sh`, do not inherit opaque release values, perform raw uninstall, or restore historical Helm values outside the guarded Gate B/Gate C path.
- Before a generic build or target write, freeze the validated chart/values packet and require the Helm stored manifest and exact release-derived live CronJob to be absent. Exact-resource discovery must not depend on a mutable instance-label selector. An active, suspended, or identity-drifted CronJob in either view must first be resolved through a separately reviewed and authorized `--disable-schedule` operation. Re-render and bind the frozen disabled packet immediately before Helm writes. A generic write succeeds only after the server-observed exact schedule remains absent; on failure, an unexpected active CronJob is precisely suspended and verified as absent/suspended, while an unreadable or uncertain postcondition remains a failure and NO-GO.
- Require explicit approval of the planning artifacts before implementation. Gate B/Gate C progression authorization has since been recorded, but it does not bypass the new clean HEAD review, Stage 3 acceptance, exact production packet, Gate B evidence acceptance, or the explicit Gate C catch-up choice.

## Approval Record

- Gate A was approved on 2026-09-08 (Asia/Shanghai) in parent issue `GYT-45`: member comment `01a07e3a-141c-71ac-b30b-0f06cf0c4a8b` replied "批准" to the architecture-review thread, and follow-up comment `01a07e3d-5a77-7972-a9cd-360c9d41dc84` recorded the decision.
- This approval authorizes repository implementation and offline verification only. It does not authorize production access or preflight, a server-side dry-run, the no-provider canary, a SQLite backup, a suspended application CronJob, any provider-backed Job, or recurring activation.
- Delivery is governed by `docs/exec-plans/active/enable-truenas-scheduled-market-collection.md`. Gate A repository work is assigned to the existing senior backend engineer through serial backlog stages; there is no frontend scope because no UI, browser workflow, or frontend API contract changes are planned.
- Gate B and Gate C progression authorization was recorded later in `GYT-47` member comment `01a07fcd-9140-7aa7-b05a-83485a7ed8c7`. GYT-52 rejected exact pushed HEAD `0b319c1501d6706f0be4eb680c46dd0d66f2c4dc` for four remaining release-safety gaps, so its historical GO evidence and Stage 3 packet are not current acceptance evidence. GYT-47 is remediating those gaps on a clean successor with GYT-21 excluded; GYT-52 must approve the new exact HEAD before Gate B preparation can proceed. The exact Gate B packet must still be reviewed, and Gate C must explicitly select `next-schedule` or `immediate catch-up` after Gate B evidence is accepted.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `after-market-data-collection-scheduling`: Add deterministic Kubernetes 1.26 timezone compatibility, fail-closed configuration validation, and staged production activation requirements to the existing scheduled-collection contract.

## Impact

- Deployment configuration and validation: `deploy/helm/a-stock/`, `deploy/truenas/`, `scripts/deploy-truenas-k3s.sh`, and `tests/test_deployment_manifests.py`.
- Documentation: a new active execution plan plus `README.md`, `docs/product-specs/market-environment-dashboard.md`, `docs/architecture.md`, `docs/runbooks.md`, and `docs/status.md` before implementation changes.
- Production boundary: the current Helm revision, image, Service, Deployment, PVC, and controller timezone must be captured during a later read-only preflight. The recorded progression permission covers that read-only step after repository prerequisites; each production mutation remains out of scope until the frozen exact packet receives Gate B action authorization or the accepted Gate B evidence receives final Gate C operation authorization, as applicable.
- No application API, dataset, provider, SQLite schema, or frontend behavior changes are planned.
