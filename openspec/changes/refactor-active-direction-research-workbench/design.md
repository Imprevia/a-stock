## Context

See `proposal.md` for motivation. The current collector validates at least 30 turnover-ranked rows but `_build_active_direction` persists only the first 10 as `topStocks`; the V2 list endpoint reads that array directly. The page consequently has current-day amount, return, industry label and close position, but no durable Top-30 sample, stock-rank history, QTS-04 trace, financial facts or intraday confirmation.

The repository already has useful local evidence in separate boundaries: THS provider observations and canonical Shenwan analysis on page 05, detailed limit facts and promotion evidence on page 03, events on page 07, and exact-date PostgreSQL snapshots/materialized aggregates. Those facts cannot be joined by display name or recomputed in the browser. Ordinary reads must remain provider-free, exact-date and pinned to one opaque materialization revision.

All QTS-04 rules are currently `documented-only` and `needs-backtest`. This design may expose raw facts and a future rule-evidence seam, but it does not silently turn those rules into executable or validated rules. Missing historical, financial, auction or intraday inputs remain visible gaps.

## Goals / Non-Goals

**Goals:**

- Preserve a validated Top-30 active-direction research sample without breaking existing Top-10 consumers.
- Materialize a bounded, exact-date workbench payload from local evidence with five stable presentation views.
- Keep observation facts, canonical identities, rule evidence, quality, lineage and missing inputs separate.
- Make the first release useful with current-day and existing cross-page facts while truthfully representing modules whose inputs are not yet approved or available.
- Provide a stable contract into which future executable QTS-04 evidence can be projected without another page redesign.

**Non-Goals:**

- Onboard a new market, fundamental, auction or minute-data provider in this change.
- Mark any QTS-04 rule executable or validated, change its ID, threshold, weight or calibration status, or add an ad hoc dashboard evaluator.
- Infer canonical sector membership or security identity from names.
- Add live monitoring, order execution, portfolio sizing, alerts, automatic refresh or application-owned scheduling.
- Automatically backfill old snapshots or production data. Historical rebuild remains an explicit, separately authorized maintenance action.

## Decisions

### 1. Preserve `researchRows` alongside legacy `topStocks`

The active-direction payload will retain the validated ordered first 30 rows in a new optional `researchRows` field. `topStocks` remains the first 10 rows projected into its existing compatible shape. Each research row is bounded and may include rank, canonical security identity, code/name, raw direction label, OHLC when supplied by the validated source, change percentage, amount, close position, source lineage and row-quality gaps.

This reuses the collector's existing Top-30 validation and prevents the materializer from attempting to reconstruct discarded rows. Adding optional JSON fields avoids rewriting old snapshots or requiring a destructive schema migration.

Alternative considered: change the existing `/active-direction` list to return 30 rows from `topStocks`. Rejected because existing consumers and tests rely on the Top-10 compatibility projection and old snapshots cannot supply 30 rows.

### 2. Add a dedicated exact-date workbench resource

The V2 surface will add an exact resource under the active-direction namespace, conceptually `GET /api/v2/market-environment/{as_of}/active-direction/workbench`. It returns one bounded payload rather than making the browser join multiple endpoints. Existing `/active-direction` pagination remains the compatibility list.

The payload is an optional `activeDirectionWorkbench` component of the same exact-date materialized aggregate and component revision vector. It contains:

- `directionOverview`: observed groups, optional canonical candidates, trace availability and lineage;
- `turnoverMap`: the bounded Top-30 research rows plus nullable historical fields;
- `securityEvidence`: bounded detail keyed by canonical security identity for rows in the sample;
- `candidatePools`: abnormal-capital, upper-shadow and first-to-second-board observations;
- `fundamentals`: available local facts or an explicit missing module;
- `validation`: exactly one prioritized next-session check when it can be formulated;
- module-level quality, missing inputs, warnings and rule maturity.

```text
exact-date local snapshots/facts
        |
        +--> activeDirection researchRows (Top 30)
        +--> sector observation/canonical analysis
        +--> limits facts and history
        +--> events
        +--> optional approved history/fundamentals
        |
        v
provider-free workbench materializer
        |
        v
activeDirectionWorkbench + component revision
        |
        v
V2 exact resource --> Pinia --> five dashboard views
```

Alternative considered: let page 06 load page 03/05/07 endpoints and compute a view model in TypeScript. Rejected because it could mix revisions, duplicate backend rules and identity joins, and violate the no-front-end-threshold-calculation boundary.

### 3. Materialize facts first; consume only registered rule evidence

The domain workbench composer will normalize existing facts into typed traces with value, window, source, coverage and missing reason. It will not calculate QTS-04 composite scores, A/B classifications or role labels unless an evidence bundle from the trading-rule platform explicitly identifies that rule as executable for the same snapshot revision.

For the current `documented-only` state, each rule group returns:

- stable rule IDs and human-facing intent;
- `implementationState=documented-only` and `calibrationState=needs-backtest`;
- available raw observations;
- `score=null`, no automatic role, and explicit missing/executable-evidence reasons;
- confirmation/invalidation prompts derived only from proven facts or documented as pending verification.

This preserves the repository rule registry as the machine-execution authority. A later change can implement QTS-04 in `trading-rules/` and the deterministic evaluator, then populate the same seam with evidence and update coverage/tests/evidence references.

Alternative considered: copy the Markdown thresholds into the market-environment service. Rejected because it creates a second rule engine and would falsely turn `documented-only` rules into executable behavior.

### 4. Use canonical identities and date-effective mappings only

All cross-dataset association uses normalized security identity and, for sectors, a versioned mapping effective on the requested date. Raw Eastmoney/TDX industry labels remain observations. THS provider identities remain separate from Shenwan canonical identities unless an approved mapping proves the link.

An unmatched row remains visible in the turnover map but cannot contribute to a canonical direction candidate or sector-resonance trace. Names are display text only.

Alternative considered: join industry and security names for broader coverage. Rejected because aliases, duplicate names and taxonomy differences would create unauditable false matches.

### 5. Derive only what existing local history can prove

After `researchRows` begins to be retained, exact-date snapshots can provide Top-30 rank continuity and new-entry observations across stored sessions. Values that require a full stock-history universe—such as a true 20-day amount baseline when a security was absent from prior Top-30 samples—remain null unless an approved local history fact supplies the denominator.

Limit detail may support first-board date, open count, first/last limit time, turnover and five-session anchor observations. Auction and live intraday confirmation remain unsatisfied next-session inputs. OHLC-dependent upper-shadow evidence is calculated only when research rows or another approved local fact contain the required OHLC and objective prior-high window.

Fundamentals use an optional local input port and start as `missing` when no approved dated facts and peer taxonomy exist. This preserves the full five-view contract without inventing a financial provider or treating absent red flags as safety.

Alternative considered: add new provider collection and historical backfill to make every module immediately complete. Rejected because source approval, data contracts, scheduling, storage and production writes materially exceed a page refactor and require a separate proposal and authorization.

### 6. Keep workbench materialization additive and failure-isolated

`activeDirectionWorkbench` is optional in the aggregate schema. Materialization failures or missing siblings produce module-level `partial`, `missing` or `insufficient` states and warnings; they do not erase a valid `activeDirection` snapshot, block unrelated datasets, or downgrade old Top-10 reads. A successful workbench component participates in the public opaque revision so subsequent reads cannot mix it with another aggregate version.

Old exact-date aggregates without the component remain readable. The V2 workbench endpoint returns an explicit missing envelope for a known date rather than calling a provider or synthesizing from a different date.

Alternative considered: persist a new normalized table for each module immediately. Rejected for the first release because the sample is bounded, JSON materialization already owns cross-dataset presentation, and no new provider-backed fact family is introduced.

### 7. Use one page-level selection model with five lazy presentation views

Page 06 will follow the compact tab pattern already used by page 05. The turnover map owns `selectedSecurityId`; the other views read that identity from page state. Switching views does not trigger provider calls. The route preloads the workbench exact resource; the existing Top-10 active-direction resource remains a compatibility fallback only when the workbench component is absent.

The page always shows date, revision/quality, rule maturity and data gaps before any interpretation. Wide tables scroll internally, mobile tabs wrap or form a two-column grid, and every status has text in addition to color.

Alternative considered: seven tabs matching the seven source documents. Rejected because documents 04–06 are three candidate lenses over the same selected security and because a five-step research flow reduces duplication while preserving source traceability.

### 8. Verification is split by contract layer

Backend tests cover source validation, Top-30 retention, Top-10 compatibility, materialization states, canonical identity boundaries, revision conflict and zero provider calls for GET. Frontend tests cover all five views, selection propagation, complete/partial/missing evidence, rule-maturity labels and fallback behavior. Browser checks cover desktop and 390px layout, minimum text size and internal table scrolling.

Repository gates additionally run the relevant market-environment pytest set, full pytest, frontend Vitest/build, trading-rule validate/coverage/docs sync-check and full docs contract. No real provider smoke, production migration, backfill or deployment is part of ordinary verification.

## Risks / Trade-offs

- [Many modules initially show incomplete evidence] -> Lead with available current-day facts, list exact missing inputs, and avoid empty decorative scores; follow-up data onboarding can fill the stable contract.
- [New snapshots have Top 30 while old snapshots have only Top 10] -> Keep both fields optional, expose coverage/available count, and never label ten old rows as a complete Top-30 research sample.
- [The workbench could accidentally become a second rule engine] -> Accept composite scores and classifications only from registered trading-rule evidence; add tests that documented-only rules keep `score=null`.
- [Cross-dataset revisions or identities could be mixed] -> Materialize once from one exact-date revision vector and require canonical IDs plus date-effective mappings.
- [Aggregate JSON grows] -> Bound the sample to 30 securities, bound evidence arrays, avoid embedding long price histories, and keep detail facts compact.
- [Page complexity harms mobile usability] -> Use five lazy views, a persistent selected-security summary, internal table scrolling and explicit 390px browser acceptance.
- [Relevant store and docs files already contain unrelated working-tree edits] -> During apply, inspect diffs before each edit, make additive localized changes, and never overwrite or normalize unrelated work.

## Migration Plan

1. Create and register the required active exec plan; update product/architecture contracts before code.
2. Add optional `researchRows` and workbench DTO/domain contracts, then update collectors/materialization while preserving `topStocks`.
3. Add provider-free read port, repository/query/router support and compatibility fixtures; deployable reads remain backward compatible when the component is absent.
4. Update the front-end types/store/router and replace page 06 with the five-view UI after backend contract tests pass.
5. Run deterministic backend/frontend/docs/rules gates and record incomplete modules and unrun external checks in the active plan.
6. Deploy backend before frontend if released separately. Existing snapshots need no migration; optional explicit historical rebuild is a separately approved operation.

Rollback reverses the frontend first, then the additive workbench endpoint/materializer. The legacy `topStocks` field, existing `/active-direction` endpoint, snapshots, PostgreSQL data and collection tasks remain intact. Do not delete `researchRows` from already written JSON or remove database history during rollback.
