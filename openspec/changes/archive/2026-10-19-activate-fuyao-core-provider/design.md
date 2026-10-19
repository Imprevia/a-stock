## Context

See `proposal.md` for motivation. The runtime already has a Fuyao v2 core adapter and the typed core acquisition order is `Fuyao -> mootdx -> Baidu -> Sina -> Tencent -> Eastmoney` when the dataset gate is enabled. Formal routing is fail-closed on an exact eligible capability report. The generic promotion command exists, but the registered evidence-policy map currently covers Fuyao sectors and THS operation datasets rather than `fuyao/core/fuyao-market-v2`, so a core-specific self-contained policy is required before production promotion.

The user has explicitly chosen direct formal activation without shadow or continuous cross-provider comparison. Existing exact-date, field, history-depth and current-date quote validation remain safety contracts; the Tencent quote is a current-date sanity check, not a retained shadow comparison or provider-equivalence report.

Production probe, capability promotion, Helm rollout, provider collection, and rollback are distinct externally mutating or networked operations and require separate authorization during implementation.

## Goals / Non-Goals

**Goals:**

- Enable Fuyao v2 as the formal first source for each core index.
- Keep the existing providers as per-index fallbacks with visible Fuyao failure evidence.
- Approve Fuyao from its own endpoint/field/date/history/permission/budget evidence without cross-provider comparison.
- Make the production capability write and config-only enablement narrow, auditable, and reversible.

**Non-Goals:**

- Do not run shadow, generate comparison reports, require a multi-day observation window, or reconcile Fuyao values against historical values from another provider.
- Do not remove or reorder the existing fallback providers after Fuyao.
- Do not change database schema, public API payloads, trading rules, dashboard calculations, scheduling ownership, or other dataset switches.
- Do not normalize or rescale Fuyao turnover based on the previously observed cross-provider amount difference.

## Decisions

### 1. Reuse the typed Fuyao-first acquisition route

The typed core acquisition plan remains the single runtime path. With the gate disabled it skips Fuyao; with the gate enabled it tries Fuyao first independently for each configured index and then walks the existing fallback order. Implementation work should be limited to characterization or gap fixes needed to prove this composition is the only supported production route.

Alternative considered: replace the full core provider with a single all-or-nothing Fuyao call. Rejected because one bad index would discard four valid Fuyao results and weaken the existing failure-isolation contract.

### 2. Keep shadow unconditionally off in the activation profile

The reviewed off and enabled profiles both set `core.shadowEnabled=false`. Formal enablement must not invoke the shadow branch, persist comparison metadata, or require a continuous observation window.

Alternative considered: leave shadow enabled for diagnostics while Fuyao is formal. Rejected because the user explicitly requested no comparison and the formal route already records each attempt and fallback warning.

### 3. Register a Fuyao core v2 capability evidence policy without comparison fields

Add `("fuyao", "core", "fuyao-market-v2")` to the existing deterministic evidence-policy registry. The policy validates:

- endpoint `/api/a-share-index/prices/historical`;
- exactly the five configured canonical index identities;
- successful OHLC and direct-turnover coverage for every index;
- requested date and last-valid-bar equality for every index;
- at least 280 valid bars per index and a positive aggregate sample count;
- permission configured/approved through an explicit real probe;
- positive request budget with requests used not exceeding the budget;
- redaction equality and canonical checksum through the existing generic promotion command.

No shadow status, formal-provider revision, cross-provider value, tolerance, or multi-date comparison is accepted or required as eligibility evidence.

Alternative considered: bypass promotion and set only the environment flag. Rejected because runtime policy deliberately refuses an enabled dataset without an exact eligible report and bypassing it would remove the fail-closed audit boundary.

### 4. Generate a fresh self-contained core report after settlement

Use the existing explicit Fuyao real-probe path after its Shanghai settlement/date gate, but select and review only the `core` report for promotion. The probe may use the required current-date Tencent quote sanity check; it must not call the existing formal history providers or create a shadow comparison. The report is written to isolated local storage and a redacted JSON envelope, never directly to production.

The report must be fresh for the rollout packet rather than relying on the 2026-09-29 temporary artifact, whose file availability, credential lifecycle, and current endpoint stability are not guaranteed.

Alternative considered: promote the historical report from plan text. Rejected because prose is not a checksum-valid report envelope and cannot prove current permissions or endpoint behavior.

### 5. Promote exactly one reviewed core report into the disabled runtime

Reuse the generic `capabilities promote` dry-run/apply command and narrow PostgreSQL unit of work. The production wrapper selects the exact Ready disabled Pod, streams the redacted envelope over stdin, and binds the operation to provider `fuyao`, dataset `core`, revision `fuyao-market-v2`, file hash, report checksum, target database identity, frozen image, and reviewed off render. Promotion changes only `provider_capability_reports`; it performs no provider call, collection, configuration change, snapshot write, or deployment hook.

Alternative considered: direct SQL insertion. Rejected because it bypasses checksum, redaction, evidence-policy, idempotency and conflict validation.

### 6. Use paired reviewed core-off and core-enabled profiles

Both complete TrueNAS profiles reuse the existing provider Secret reference, declare approved revision `fuyao-market-v2`, and keep shadow off. The off profile keeps formal core disabled; the enabled profile changes only formal core to enabled. If live production lacks the approved revision metadata, first converge to the reviewed off profile, then perform a same-image, hook-free config-only enable whose only semantic diff is `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED: 0 -> 1`.

The packet validator rejects image, hook, resource-set, Secret, PVC, Service, database, scheduling, shadow, other dataset, topology, or unrelated environment drift before Helm writes.

Alternative considered: enable and declare the revision in one live diff. Rejected because a one-field off-to-on diff is easier to review and gives rollback an exact complete target.

### 7. Verify one core-only collection without adding an observation program

After settlement and separate authorization, run exactly one core-only collection. Full activation acceptance requires all five indices to prove the selected date from Fuyao with at least 280 bars and direct turnover. If one or more indices fall back, the collection remains valid under the runtime contract but rollout acceptance is partial: retain the warnings and decide whether to keep the fallback-capable activation or execute the reviewed off rollback. No automatic second collection or multi-day comparison follows.

### 8. Roll back by configuration only

Rollback uses the same frozen image, reviewed off profile and `--no-hooks`. It changes only the formal core enabled flag from `1` to `0`, retains the promoted report and all collection evidence, and restores the existing provider chain as the first attempted formal route. It never deletes snapshots, tasks, Secrets or PVCs.

## Risks / Trade-offs

- [Direct activation cannot detect a semantic turnover difference that still passes the Fuyao contract] -> Accept this explicitly as the consequence of no cross-provider comparison; preserve direct-turnover provenance and do not rescale or relabel values.
- [Fuyao fails or rate-limits after activation] -> Fall back per index through the existing chain, retain the Fuyao failure warning, and use same-date retention when every source fails.
- [A stale or weak report is promoted] -> Require a fresh settlement-gated probe and a registered core evidence policy bound to endpoint, identities, fields, dates, history depth, permissions, budget, checksum and redaction.
- [Current-date Tencent quote is unavailable] -> Reject current-date Fuyao evidence and use fallbacks; historical collections remain quote-free and exact-date validated from bars.
- [A config rollout changes unrelated state] -> Stage the complete off profile, freeze the image and rendered packets, and reject every semantic diff except the formal core enabled flag.
- [The first collection is mixed Fuyao/fallback] -> Report partial/degraded activation evidence rather than claiming full Fuyao success; do not hide which index used which provider.

## Migration Plan

1. Implement the core v2 capability evidence policy, formal-route characterization, deployment profiles, packet validation and deterministic tests with all new switches disabled by default.
2. Update architecture, runbook, repository mapping, product specification and active plan; pass backend, Helm, OpenSpec and docs-contract gates offline.
3. After separate authorization, perform a read-only production preflight and stage the reviewed complete core-off profile with the frozen image if revision metadata is not already present.
4. After settlement and separate authorization, run a fresh Fuyao real probe into isolated local files and review only the self-contained core report.
5. After separate authorization, stream the exact report to the disabled Ready Pod, run promotion dry-run, then apply the single capability row and verify its checksum without exporting database credentials.
6. After separate authorization, apply the same-image, hook-free core-enabled profile and prove the only off/on semantic diff is the formal core enabled flag while shadow remains off.
7. After settlement and separate authorization, run one core-only collection and inspect each index's exact date, source, revision, observations, direct-turnover evidence and fallback warnings.
8. If rollout or collection acceptance fails, apply the reviewed same-image core-off profile and retain the report, snapshots, task history, Secret and PVC.
