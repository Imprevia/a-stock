## 1. Baseline and Contract Characterization

- [ ] 1.1 Trace every supported `core` collection runtime to the typed acquisition plan and document whether any legacy collector remains reachable; verify with focused composition/registry tests and update the design before implementation if a second active path exists
- [ ] 1.2 Add characterization tests proving `core.enabled=false` plus `core.shadowEnabled=true` keeps the existing formal provider candidate authoritative, records a shadow attempt for each of the five indices, and never publishes Fuyao as the formal source
- [ ] 1.3 Add failure-isolation tests for Fuyao permission, rate-limit, transport, short-history, missing-turnover, identity, price-check, and cross-date failures; verify the formal task state and same-date retention result are unchanged except for bounded shadow diagnostics

## 2. Shadow Evidence Completeness

- [ ] 2.1 Extend the core shadow comparison only where characterization exposes a gap so it records exact requested date, both revisions, five-index comparable counts, identity gaps, OHLC/changePct/amount differences, tolerances, and bounded difference classifications; verify deterministic fixture tests cover every field
- [ ] 2.2 Preserve and test `amountEvidence`/`amountBasis` attribution so direct Fuyao turnover and estimated or unavailable formal turnover are classified as provider-basis or field-missing evidence without rescaling or widening tolerances
- [ ] 2.3 Add redaction and size-bound tests proving shadow metadata excludes API keys, authorization/cookie/header values, raw provider envelopes, and unbounded history rows while retaining safe error category, request date, revision, counts, and difference summary
- [ ] 2.4 Add observation-completeness logic or a bounded reporting helper that counts a date only when all five Fuyao series prove the same settled exact date, contain at least 280 valid OHLC/turnover bars, and satisfy the current-date Tencent quote check; verify incomplete dates remain visible but do not advance the five-date window

## 3. Reviewed Shadow-Only Deployment Assets

- [ ] 3.1 Add minimal TrueNAS `core-shadow-off` and `core-shadow-on` values overlays with `core.enabled=false`, `core.approvedRevision=fuyao-market-v2`, and only the shadow flag differing; verify neither file contains a credential value or changes another dataset
- [ ] 3.2 Add or extend a packet validator for the complete off/on Helm renders; verify it rejects image, Secret reference, Service, PVC, database, scheduling, hook, resource-set, other environment, or non-core dataset drift and accepts only `MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED: 0 -> 1`
- [ ] 3.3 Add manifest and validator tests for both overlays, including fail-closed cases for `core.enabled=1`, missing/wrong revision, CronJob/Job presence, a changed image, a changed Secret/PVC, and unrelated environment drift
- [ ] 3.4 Add deployment-script entry points only if required to stage off, enable shadow, and disable shadow with the frozen reviewed image and `--no-hooks`; verify shell syntax and fixture tests prove no provider, capability, collection, build, import, retag, or Helm write occurs before packet validation

## 4. Documentation and Operational Evidence

- [ ] 4.1 Update `docs/architecture.md` with the shadow-only data flow, formal-source isolation, turnover-basis classification, and provider-free read boundary; verify links and terminology match the delta spec
- [ ] 4.2 Update `docs/runbooks.md` with offline render checks, read-only preflight, separately authorized off/on rollout, exact post-rollout verification, rollback, rate-limit response, and five-settled-date observation procedure
- [ ] 4.3 Update `docs/repository-guide.md` and the market-environment product specification where the code-document mapping or operator-visible quality semantics change; verify docs contract identifies every affected implementation path
- [ ] 4.4 Maintain `docs/exec-plans/active/activate-fuyao-core-shadow.md` after each stage with Status, Completion Evidence, Remaining Gaps, Next Step, explicit production authorizations, render checksums, and observation counts

## 5. Deterministic Verification

- [ ] 5.1 Run focused core acquisition, Fuyao adapter, shadow comparator, deployment manifest, packet validator, and deployment-script tests; record exact commands and pass counts in the active plan
- [ ] 5.2 Run Helm strict lint and offline templates for the reviewed base plus shadow-off/on overlays; verify the complete resource set contains no application CronJob/Job and the off/on semantic diff is exactly the approved shadow flag
- [ ] 5.3 Run the market-environment architecture gate, full relevant backend suite, OpenSpec strict validation, `git diff --check`, and `python scripts/check-docs-contract.py --mode=full`; record any unrun check or blocker explicitly

## 6. Separately Authorized Production Activation

- [ ] 6.1 After explicit authorization, perform a read-only production preflight that records the live/stored Helm revision, frozen image identity, Ready pods, Secret/PVC/Service identities, database target, all Fuyao dataset flags, scheduling absence, and current core task health without reading secret values or calling a provider
- [ ] 6.2 After separate explicit authorization, converge to the reviewed core-shadow-off render when required; verify the same frozen image, hooks disabled, formal core off, shadow off, approved revision v2, unchanged infrastructure, and zero provider or collection action during the rollout
- [ ] 6.3 After separate explicit authorization and the settlement boundary, apply the reviewed same-image core-shadow-on render; verify the only off/on semantic change is the shadow flag, formal core remains disabled, unrelated datasets remain unchanged, and health/read paths remain available
- [ ] 6.4 If rollout verification, provider pressure, or shadow isolation fails, apply the reviewed same-image shadow-off rollback after explicit authorization; verify subsequent core tasks issue no Fuyao shadow attempts and no snapshot, capability row, task history, Secret, or PVC is deleted

## 7. Observation Window and Handoff

- [ ] 7.1 For each naturally authorized settled core collection, capture the redacted bounded shadow summary and verify formal snapshot source/checksum remain authoritative; do not trigger an extra provider-backed collection without separate authorization
- [ ] 7.2 Accumulate at least five complete settled trading dates and produce a review packet containing dates, revisions, render checksums, counts, statuses, bounded per-index differences, turnover-basis attribution, permission/rate-limit outcomes, and incomplete-date reasons with no credentials or raw provider rows
- [ ] 7.3 Review the five-date packet against the delta spec; verify any unresolved mismatch, degraded/insufficient result, cross-date evidence, missing index, or unexplained turnover basis leaves `core.enabled=false` and is recorded as a blocker
- [ ] 7.4 Update the active plan and OpenSpec task evidence with the activation result and remaining observation/cutover gaps; do not propose or execute formal Fuyao cutover without a separately reviewed and authorized change
