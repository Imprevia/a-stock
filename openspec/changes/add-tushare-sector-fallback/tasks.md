## 1. Specifications, Plan, and Baseline

- [ ] 1.1 Create/update the active exec plan, product specification, `docs/architecture.md`, `docs/runbooks.md`, and `docs/status.md` with the fixed four-source order, official API boundaries, token handling, default-off behavior, permission blocker, and rollback; verify `python scripts/check-docs-contract.py --mode=fast`.
- [ ] 1.2 Confirm the Fuyao promotion change is implemented or available as a prerequisite and preserve its generic capability-promotion command; verify this change adds no duplicate promotion path or production write.
- [ ] 1.3 Freeze deterministic Eastmoney -> Fuyao sectors fixtures, provider-free GET/status behavior, same-date retention, and public `SectorRow`/snapshot compatibility before inserting Tushare; verify the existing focused regression suite passes.

## 2. Shared Transport Security

- [ ] 2.1 Extend JSON-body sensitive-key extraction and provider error-echo redaction for nested `token`, `secret`, `password`, `cookie`, and `authorization` values; verify full/partial token echoes, URL/query credential values, and raw-body absence from diagnostics.
- [ ] 2.2 Verify authenticated POSTs use the existing host budget, retry, cooldown, and single-flight policy, isolate account identities by authentication-scope digest, do not blindly retry 401/403/business permission errors, and default to `cache_seconds=0`; verify focused transport tests.

## 3. Tushare Client, Configuration, and Capability Probe

- [ ] 3.1 Add default-off Tushare sectors configuration, approved revision `tushare-ths-sectors-v1`, Secret token loading, and capability policy; verify disabled, missing token, missing report, non-eligible, and revision-mismatch cases skip before network I/O.
- [ ] 3.2 Implement the official JSON POST client for `ths_index`, `ths_daily`, and `moneyflow_ind_ths`, including bounded `code`/`msg` parsing, pagination, malformed fields/items, permission denial, rate limits, missing pages, duplicate identities, and no complete-response exception leakage.
- [ ] 3.3 Add offline fixtures and an explicit `--allow-real` after-hours probe that writes only an isolated store and redacted JSON; verify exact-date rows, all three API permissions, identity coverage, field units, pagination, rate-limit evidence, and `ineligible` output when any permission or semantic contract is unproven.

## 4. Sectors Adapter and Fallback Routing

- [ ] 4.1 Implement `sectors-tushare-ths`, joining unique catalog/daily/flow identities and rejecting missing, orphan, duplicate, mixed-date, and cross-date rows; verify requested and actual `trade_date` are equal and no date relabeling occurs.
- [ ] 4.2 Implement stable ranking and field authority: `code`, `name`, `changePct`, verified ten-thousand-yuan-to-yuan `mainNet`, and only a validated official leader name; verify `amount`, `mainNetPct`, `upCount`, and `downCount` remain null with warnings, and `company_num`/volume are never substituted.
- [ ] 4.3 Insert Tushare between Eastmoney delayed and Fuyao in the acquisition plan; verify delayed success short-circuits both fallbacks, Tushare success short-circuits Fuyao, gate failure performs zero Tushare I/O and continues to Fuyao, Tushare failure preserves warnings and continues, and all-source failure retains existing failed-retained/failed-missing semantics.
- [ ] 4.4 Verify same-date commit, aggregate materialization, provider-free GET/status/chapter reads, and unchanged enrichment/shadow behavior with Tushare disabled and enabled fixtures.

## 5. Deployment and Documentation

- [ ] 5.1 Add Helm Tushare existing Secret/key reference, `enabled=false`, empty approved revision, and Deployment/CronJob env wiring; verify token values are never rendered, schedules remain absent/suspended, Scrapling and enrichment remain disabled, and defaults do not change Fuyao behavior.
- [ ] 5.2 Run Helm lint/template and manifest tests for baseline and a controlled Tushare overlay; verify only the Tushare sectors switch/revision/Secret reference changes and rollback disables that switch without deleting evidence.
- [ ] 5.3 Synchronize architecture, runbook, product spec, status, and active-plan records with the implementation and current permission blocker; verify docs-contract fast after edits.

## 6. Verification and Authorized Operations

- [ ] 6.1 Run focused transport/config/client/probe/adapter/collection/Helm/security tests and then `python -m pytest tests -q`, frontend `npm run test` and `npm run build`, `python -m src.trading_system.cli rules validate`, `python -m src.trading_system.cli rules coverage`, `python -m src.trading_system.cli docs sync-check`, strict OpenSpec validation for this change and its Fuyao prerequisite, and `python scripts/check-docs-contract.py --mode=full`; record exact results.
- [ ] 6.2 After explicit authorization and only after all three Tushare permissions are granted, run the real probe, review its redacted `eligible` report, promote it through the generic capability command, deploy the Secret reference/revision, and collect exactly one current-date sectors dataset; otherwise record the permission blocker and keep Tushare disabled.
- [ ] 6.3 If authorized rollout or collection fails, deploy only the Tushare-off configuration and verify capability reports, task history, snapshots, and PVCs remain intact; update active-plan `Status`, `Completion Evidence`, `Remaining Gaps`, and `Next Step`.
