## 1. Formal Route and No-Shadow Contract

- [x] 1.1 Trace production `core` composition to the typed acquisition plan and verify with registry/composition tests that enabling core produces the per-index order `Fuyao -> mootdx -> Baidu -> Sina -> Tencent -> Eastmoney`
- [x] 1.2 Add characterization tests proving a successful Fuyao result becomes the formal source with revision `fuyao-market-v2`, at least 280 bars and direct-turnover evidence while `core.shadowEnabled=false` produces no shadow attempts or comparison metadata
- [x] 1.3 Add per-index fallback tests for permission, rate-limit, transport, identity, short-history, missing OHLC/turnover, current-price-check and cross-date failures; verify successful fallbacks retain their actual source plus the Fuyao failure warning
- [x] 1.4 Add mixed-result and all-failed tests proving one Fuyao failure does not discard sibling successes, same-date retention remains valid, and no cross-date candidate enters the formal snapshot or aggregate

## 2. Self-Contained Fuyao Core Capability Policy

- [x] 2.1 Register a `fuyao/core/fuyao-market-v2` evidence policy that validates the historical endpoint, five canonical identities, OHLC/direct-turnover coverage, exact requested-date tails, at least 280 bars per index, permissions, positive request budget and requests-used bound
- [x] 2.2 Extend the core real-probe report evidence where necessary so every policy fact is explicit and redacted without including formal-provider values, shadow status, tolerances or comparison results; verify offline and real-probe fixture tests
- [x] 2.3 Add capability-promotion tests for a valid self-contained core report, missing index, missing turnover, short history, date mismatch, wrong endpoint/revision, permission failure, exhausted budget, checksum conflict and redaction mismatch; verify every rejection performs zero writes
- [x] 2.4 Verify generic promotion remains single-row, dry-run by default, idempotent for the same checksum and conflicting for a different checksum without constructing a provider, collector, snapshot writer or deployment client

## 3. Reviewed Formal Core Deployment Assets

- [x] 3.1 Add complete TrueNAS core-off and core-enabled values profiles that reuse the existing provider Secret, declare `fuyao-market-v2`, keep shadow false, and differ only by the formal core enabled flag
- [x] 3.2 Add or extend packet validation for both complete renders; verify it rejects image, hook, resource-set, Secret, PVC, Service, database, scheduling, shadow, another dataset or unrelated environment drift and accepts only `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED: 0 -> 1`
- [x] 3.3 Add manifest and packet tests covering off/enabled profiles, wrong/missing revision, shadow accidentally enabled, application CronJob/Job presence, image drift, Secret/PVC drift and unrelated configuration changes
- [x] 3.4 Add controlled deployment-script operations for staging core-off, promoting the core capability report, enabling formal core and disabling formal core; verify shell/fixture tests prove packet validation precedes network or Helm writes and config-only operations use the frozen image with `--no-hooks`
- [x] 3.5 Bind promotion to the reviewed provider/dataset/revision selectors, report file hash/checksum, exact disabled Ready Pod, masked database target, frozen image and reviewed off render; verify no credential value is exported or printed

## 4. Documentation and Plan Synchronization

- [x] 4.1 Update `docs/architecture.md` with Fuyao formal-first per-index routing, direct-turnover provenance, no-shadow decision, fallback warnings and provider-free read boundary
- [x] 4.2 Update `docs/runbooks.md` with offline probe/policy checks, read-only preflight, fresh settlement-gated core probe, reviewed promotion, same-image enable, one core-only collection and configuration rollback
- [x] 4.3 Update `docs/repository-guide.md`, `src/market_environment/AGENTS.md` and the market-environment product specification where the implementation/document mapping or operator-visible source semantics change
- [x] 4.4 Maintain `docs/exec-plans/active/activate-fuyao-core-provider.md` with implementation status, explicit external-operation authorizations, report/render checksums, production before/after evidence, remaining gaps and next step

## 5. Deterministic Verification

- [x] 5.1 Run focused core acquisition, Fuyao adapter, capability policy/promotion, deployment manifest, packet validator and deployment-script tests; record exact commands and pass counts in the active plan
- [x] 5.2 Run Helm strict lint and offline templates for reviewed core-off/enabled profiles; verify complete resource sets contain no application CronJob/Job, shadow remains off and the semantic diff is exactly the formal core enabled flag
- [x] 5.3 Run the market-environment architecture gate, relevant/full backend suite, OpenSpec strict validation, `git diff --check` and `python3 scripts/check-docs-contract.py --mode=full`; record every unrun check or blocker explicitly

## 6. Separately Authorized Production Activation

- [x] 6.1 After explicit authorization, perform a read-only production preflight that records Helm revision, frozen image, Ready pods, Secret/PVC/Service identities, database target, Fuyao flags, scheduling/Job absence, current capability rows and core task health without reading secret values or calling a provider
- [x] 6.2 After separate explicit authorization, converge to the reviewed complete core-off profile if required; verify the same frozen image, hooks disabled, formal core off, shadow off, revision v2, unchanged infrastructure and zero provider/collection action during rollout
- [x] 6.3 After settlement and separate explicit authorization, run one fresh Fuyao real probe into isolated local storage, select the core report, and verify five identities, exact dates, minimum history, direct-turnover coverage, permissions, budget, redaction and checksum without cross-provider comparison
- [x] 6.4 After separate explicit authorization, stream the reviewed core report to the exact disabled Ready Pod, run capability promotion dry-run then apply, and verify exactly one matching runtime row with no snapshot, task, aggregate, configuration or deployment mutation
- [x] 6.5 After separate explicit authorization, apply the same-image core-enabled profile with hooks disabled; verify the only off/on semantic difference is formal core enabled, shadow remains off, unrelated datasets/resources remain unchanged and health/provider-free reads remain available
- [x] 6.6 After settlement and separate explicit authorization, run exactly one core-only collection; verify all five index dates, sources, revisions, observation counts, direct-turnover evidence and fallback warnings, and mark acceptance partial rather than repeating automatically if any index falls back
- [x] 6.7 If rollout or collection acceptance fails, after explicit authorization apply the reviewed same-image core-off rollback; verify formal Fuyao attempts stop while the capability report, snapshots, task history, Secret and PVC remain intact
  - Not triggered: the config-only rollout and the single core-only collection both passed, with full all-Fuyao acceptance. No rollback was authorized or executed.

## 7. Completion and Handoff

- [x] 7.1 Update the active plan and task evidence with final offline/production results, clearly distinguish full all-Fuyao success from mixed fallback or rollback, and preserve the explicit no-shadow decision
- [x] 7.2 Re-run OpenSpec strict and docs-contract full after final evidence updates, then leave any further provider normalization, repeated observation or comparison as a separately proposed change
