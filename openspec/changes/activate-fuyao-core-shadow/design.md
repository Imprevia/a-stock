## Context

See `proposal.md` for motivation. The repository already contains a Fuyao v2 core history adapter, a typed core acquisition plan, redacted provider comparison, Helm environment wiring, and a default-off `core.shadowEnabled` value. The formal core route is independently capability-gated; shadow execution is available while formal Fuyao collection remains disabled. The last real probe proved five-index history depth but the isolated shadow still reported a turnover-basis difference, so activation must collect evidence without implying cutover approval.

Production provider calls, capability writes, Helm changes, and observation runs are external writes or network operations and remain separately authorized implementation steps. This design only establishes the assets and gates they must use.

## Goals / Non-Goals

**Goals:**

- Activate only Fuyao core shadow against the existing formal provider chain.
- Make the deployment delta mechanically reviewable and rollback-safe.
- Persist bounded, redacted, exact-date comparison evidence for all five indices.
- Define a five-settled-session observation packet that can support a later cutover decision.

**Non-Goals:**

- Do not enable `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED` or change formal provider ordering.
- Do not promote a capability report, declare Fuyao production-eligible, or normalize away turnover differences in this change.
- Do not change public API payloads, database schema, scheduling, manual/automation access, other datasets, rules, or dashboard calculations.
- Do not embed credentials or real provider data in Git, fixtures, values, logs, or review packets.

## Decisions

### 1. Use paired shadow-off and shadow-on overlays

Add two minimal TrueNAS values overlays applied after the currently reviewed environment values. Both set `core.enabled=false` and `core.approvedRevision=fuyao-market-v2`; the off overlay sets `core.shadowEnabled=false`, while the on overlay sets it to `true`. The provider Secret remains an existing reference and its value is never rendered.

Deployment is two-stage when the live approved revision is initially empty: first converge to the reviewed off render, then compare off versus on renders and allow only `MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED: 0 -> 1`. This avoids combining revision declaration with provider activation and gives rollback an exact reviewed target.

Alternative considered: edit the shared TrueNAS values in place. Rejected because it obscures the one-flag semantic delta and risks changing unrelated runtime state.

### 2. Keep formal enablement and capability promotion out of shadow gating

Shadow uses the declared `fuyao-market-v2` adapter revision while `core.enabled` remains false. It does not require promoting an eligible production capability report because its purpose is to produce the missing comparison evidence. The existing formal cutover gate remains unchanged and therefore cannot infer approval from `shadowEnabled=true`.

Alternative considered: require an eligible capability report before shadow calls. Rejected because that makes the evidence needed for approval depend on approval already existing. Credential availability, endpoint contract, exact-date validation, request budgets, and redaction still fail closed at runtime.

### 3. Reuse typed core acquisition shadow evidence

The typed core acquisition plan remains the source of truth. It first collects formal core evidence, then—only when formal Fuyao cutover is disabled and shadow is enabled—requests Fuyao for each index and writes the bounded comparison under quality/task observation metadata. Shadow failure appends diagnostics but does not replace formal candidates or independently determine the task terminal state.

If implementation inspection finds the legacy collector can still be selected by a supported runtime path, either route that path through the typed acquisition plan or prove equivalent behavior with characterization tests; do not add a third shadow implementation.

Alternative considered: add a separate shadow job or dataset. Rejected because it would create new scheduling, lease, storage, and ownership semantics and could drift from the exact formal collection being compared.

### 4. Treat turnover basis as evidence, not an automatic tolerance increase

The comparison retains field-level mismatches and classifies known direct-turnover versus current-quote-calibrated turnover differences as `provider-basis`. The observation packet summarizes ratios and classifications per index/date but does not silently rescale values or widen the existing tolerance merely to obtain `match`.

After five complete settled dates, a reviewer may conclude that a deterministic documented conversion is justified, that the formal comparison source is unsuitable, or that cutover must remain blocked. Any normalization or tolerance policy change requires an explicit artifact update and deterministic fixtures before cutover.

Alternative considered: ignore `amount` during shadow. Rejected because historical turnover availability is the reason for evaluating Fuyao.

### 5. Separate activation acceptance from cutover acceptance

Activation is successful when the reviewed shadow-only render is deployed, formal source and infrastructure invariants are unchanged, and shadow evidence is produced without affecting formal snapshots. The observation phase then collects at least five complete settled trading dates. A mismatch does not make shadow activation itself a failure; it is a valid result that blocks formal cutover.

The final observation packet contains only dates, revisions, counts, status/category summaries, bounded per-index field differences, turnover-basis attribution, request-budget/rate-limit outcomes, and checksums of the reviewed renders. It excludes raw provider payloads and credentials.

### 6. Make every production step explicitly authorized and reversible

Repository implementation and offline rendering precede any production action. Production preflight is read-only. Staging the off render, enabling shadow, triggering a collection outside the normal authorized automation path, or querying production observation metadata are distinct actions and require explicit authorization recorded in the active plan. Rollback reuses the same frozen image and reviewed off render with hooks disabled; it does not delete capability rows, snapshots, tasks, PVCs, or Secrets.

## Risks / Trade-offs

- [Fuyao shadow doubles five-index history requests during core collection] -> Reuse the shared transport gateway, request budget, single-flight, cooldown, and bounded retry policy; record rate-limit outcomes and roll back shadow on sustained pressure.
- [The formal provider falls back to a source with estimated or missing turnover] -> Preserve source and amount-basis attribution per index/date; do not interpret a provider-basis mismatch as Fuyao corruption or as an automatic match.
- [Shadow warnings make an otherwise successful core task appear degraded] -> Keep formal terminal-state calculation independent; expose shadow status as observation metadata and a bounded warning without overwriting formal quality facts.
- [A minimal overlay is accidentally applied without the reviewed environment values] -> Add render validation that requires the complete release resource set and exact expected Secret/PVC/Service/scheduling invariants before any Helm write.
- [Five dates are statistically limited] -> Treat five sessions as the minimum operational gate, not proof of long-term equivalence; retain all results and allow the later cutover review to require a longer window.
- [Current deployment differs from the repository's assumed baseline] -> Fail before Helm writes when the live image, resource identities, hooks, environment, or stored values differ from the reviewed packet.

## Migration Plan

1. Implement offline fixtures/tests for shadow-only configuration, exact-date comparison, turnover-basis attribution, failure isolation, redaction, and render diffs.
2. Add paired shadow-off/on overlays and a validator proving a complete same-image release with no CronJob/Job and only the reviewed core shadow flag difference between the two renders.
3. Update architecture, runbook, repository mapping, product/operations documentation where required, and pass deterministic backend, Helm, OpenSpec, and docs-contract gates.
4. After separate authorization, run a read-only production preflight and converge to the reviewed shadow-off render if necessary.
5. After separate authorization and after settlement, apply the same-image shadow-on render without hooks; verify formal core enablement remains off and other resources/configuration are unchanged.
6. Observe at least five complete settled trading dates, storing only redacted bounded comparison evidence. Do not force extra collections unless separately authorized.
7. Produce the observation packet. If any required evidence remains unresolved, keep shadow on or roll it off according to provider pressure, but keep formal cutover disabled.
8. Rollback, when required, applies the reviewed shadow-off render with the same image and verifies zero subsequent Fuyao shadow attempts while retaining all historical evidence.

## Open Questions

- Whether five sessions should be extended before a later formal-cutover proposal can be decided after the first observation packet; extending the window does not change this shadow-only contract.
