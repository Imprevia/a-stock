## 1. Planning and documentation contract

- [x] 1.1 Create `docs/exec-plans/active/refactor-active-direction-research-workbench.md` with Stage, Status, Acceptance, Completion Evidence, Remaining Gaps and Next Step, register it in the active index, and verify `python scripts/check-docs-contract.py --mode=fast` recognizes the plan before code changes.
- [x] 1.2 Update `docs/product-specs/market-environment-dashboard.md` with the five-view page-06 behavior, Top-30/Top-10 compatibility, documented-only rule states, missing-module semantics and desktop/390px acceptance; verify every OpenSpec requirement is represented in product acceptance language.
- [x] 1.3 Update `docs/architecture.md`, `docs/repository-guide.md` and `docs/runbooks.md` with the additive `researchRows` payload, workbench materialization/read flow, provider-free boundary, no automatic backfill and rollback order; verify architecture and runbook contain no new scheduled or production-write path.

## 2. Preserve the validated Top-30 research sample

- [x] 2.1 Extend active-direction response/domain models with optional bounded `researchRows` and row lineage fields while preserving the existing `topStocks` shape; verify schema tests accept old Top-10 fixtures and new Top-30 fixtures.
- [x] 2.2 Update the primary and delayed active-direction builders to retain exactly the validated first 30 ordered rows, project the first 10 to `topStocks`, and keep invalid sample/field/order rejection unchanged; verify focused acquisition tests cover valid and invalid payloads.
- [x] 2.3 Update the approved TDX-derived path to retain its stable locally sorted Top 30 with ranking method, source revision and industry-mapping metadata while keeping Top 10 compatible; verify deterministic tie ordering and incomplete mapping tests pass.
- [x] 2.4 Update snapshot/materialization and compatibility adapters so new JSON keeps `researchRows` and old snapshots remain readable without it; verify no migration rewrites existing snapshots and regression tests preserve failed-retained/failed-missing behavior.

## 3. Build the provider-free workbench materialization

- [x] 3.1 Add typed workbench module, trace, row, rule-maturity, quality, lineage and validation contracts under the existing domain/application boundaries; verify serialization tests preserve nulls and reject unbounded or invalid identities.
- [x] 3.2 Implement the direction-overview and turnover-map fact composer from one exact-date evidence revision, keeping raw provider labels separate from date-effective canonical identities; verify unmatched identities remain observations and never become canonical candidates.
- [x] 3.3 Add bounded rank-history enrichment from stored exact-date `researchRows`, returning prior rank/new-entry/continuity only when proven and leaving unavailable 5/20-day denominators null; verify historical gaps and old Top-10 snapshots cannot produce false complete evidence.
- [x] 3.4 Implement selected-security raw evidence for the six core-recognition dimensions and abnormal-capital/upper-shadow/first-to-second-board views without calculating documented-only QTS composite scores or assigning roles; verify `score=null`, `implementationState=documented-only` and `calibrationState=needs-backtest` in tests.
- [x] 3.5 Use exact-date limit details and history only for proven first-board anchors and five-session candidates, keeping auction/intraday fields pending; verify strict first-to-second and broader five-session classes cannot be conflated.
- [x] 3.6 Add the optional fundamentals module input boundary and missing-state implementation, ensuring absent or stale financial facts do not imply safety; verify the initial no-approved-fundamentals fixture lists profitability, growth, cash-flow, leverage and valuation gaps.
- [x] 3.7 Produce exactly one prioritized next-session validation from proven evidence or evidence-recovery gaps, with explicit confirmation and invalidation text; verify an unsupported date yields no directional conclusion.
- [x] 3.8 Add optional `activeDirectionWorkbench` to aggregate materialization and its component revision vector with module-level failure isolation; verify a workbench failure neither erases valid active-direction data nor blocks unrelated aggregate components.

## 4. Expose the exact-date V2 read contract

- [x] 4.1 Add the provider-free workbench method to the typed read port, query facade, PostgreSQL repository and compatibility adapter; verify unknown dates, known-date missing components and exact-date reads use the existing response semantics.
- [x] 4.2 Add the exact resource under `/api/v2/market-environment/{as_of}/active-direction/workbench`, including links, ETag/revision preconditions and DTO/OpenAPI coverage; verify stale revisions fail before repository mixing and malformed/future dates keep current errors.
- [x] 4.3 Instrument focused API tests to prove the workbench GET performs zero provider calls, creates no collection/background task, writes no PostgreSQL row and never substitutes another date.
- [x] 4.4 Keep `/active-direction` pagination backed by legacy `topStocks` while the workbench consumes `researchRows`; verify existing consumers still receive at most 10 compatible rows and the new resource receives at most 30 research rows.

## 5. Refactor page 06 into the five-view workbench

- [x] 5.1 Add TypeScript contracts and a dedicated Pinia V2 workbench resource, update route metadata to prefetch it, and retain the legacy active-direction fallback for old aggregates; verify store tests cover ready, partial, missing and revision-conflict states.
- [x] 5.2 Replace the single table page with the fixed flow label, quality/lineage header and five keyboard-operable view controls while retaining `/dashboard/06` and its navigation title; verify the page test finds every view label and the exact selected date.
- [x] 5.3 Implement direction overview and the Top-30 turnover map with observation/canonical separation, source/ranking metadata, nullable history cells and row selection by canonical security identity; verify selecting a row propagates the same identity without a name join.
- [x] 5.4 Implement core-recognition and three candidate-pattern presentations with raw traces, rule maturity, missing inputs, vetoes, observation windows, confirmation and invalidation; verify no automatic leader/middle-force/catch-up role or buy/sell wording is rendered.
- [x] 5.5 Implement fundamentals and next-session validation presentations, including a useful explicit missing state when no approved financial facts exist; verify absence of red flags is not rendered as a positive result.
- [x] 5.6 Add scoped responsive styles so visible text, controls, legends, axes and tooltips are at least 14px, tabs and evidence stack at 390px, and wide tables scroll only inside their containers; verify desktop and 390px browser checks show no page-level overflow, overlap or clipping.

## 6. Verification and completion evidence

- [x] 6.1 Run focused backend tests for active-direction acquisition, materialization, V2 repositories/resources/contracts and zero-provider reads; record the exact command and result in the active plan.
- [x] 6.2 Run `npm run test` and `npm run build` in `apps/market-environment-dashboard/`; record results and any existing unrelated warnings in the active plan.
- [x] 6.3 Run `python -m src.trading_system.cli rules validate`, `python -m src.trading_system.cli rules coverage` and `python -m src.trading_system.cli docs sync-check`; verify QTS-04 IDs and coverage remain unchanged and no documented-only rule is reported executable.
- [x] 6.4 Run `openspec validate refactor-active-direction-research-workbench --strict`, `python -m pytest tests -q` and `python scripts/check-docs-contract.py --mode=full`; fix in-scope failures and record any confirmed pre-existing blocker precisely.
- [x] 6.5 Update the active plan Status, Completion Evidence, Remaining Gaps and Next Step with Top-30 compatibility evidence, module availability, desktop/390px inspection and all unrun external checks; verify the docs-contract full gate passes with the final plan state.

## 7. Evidence module repair

- [x] 7.1 Retain approved valuation fields from the existing exact-date active-direction snapshot and expose them as raw, unscored fundamentals evidence; preserve nulls and identify unavailable profitability, growth, cash-flow and leverage facts.
- [x] 7.2 Project existing exact-date limit security facts into the workbench candidate pools, including promoted/first-to-second anchors and intraday seal/opening evidence, without conflating them with auction evidence.
- [x] 7.3 Add field-level quality/lineage states and page presentations so available valuation and limit facts are no longer rendered as blanket `missing`; keep auction and unsupported financial facts explicitly pending/missing with recovery reasons.
- [x] 7.4 Add focused tests and update the active plan with the repaired evidence coverage, remaining source gaps and verification results.
