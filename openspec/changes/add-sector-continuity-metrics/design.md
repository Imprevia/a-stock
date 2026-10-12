## Context

See [proposal.md](./proposal.md) for motivation and the capability specs for externally observable behavior.

The market-environment runtime currently manages five stable collection datasets: `core`, `breadth`, `limits`, `sectors`, and `activeDirection`. The `sectors` dataset is a latest-only provider ranking whose rows retain provider codes, names, same-day values, and collection quality. `SectorEvidence` exposes only `rows`, `state`, and `quality`; it does not contain point-in-time Shenwan identities, history, or chapter 05 rule metrics. Normal dashboard reads and collection-status reads are provider-free and must stay that way.

The repository already has useful building blocks but not a complete continuity chain:

- the TDX daily-package path can prove exact-date ordinary-A-share OHLC, previous close, volume, and original amount with universe audit evidence;
- provider capability reports, unified transport policy, PostgreSQL repositories/unit-of-work, exact-date materialization, and independent collection-task retention already exist;
- chapter 05 rule IDs, canonical metric names, weights, evaluators, fixtures, and `needs-backtest` state already exist in `trading-rules/`;
- `create_after_market_snapshot` currently connects only the index slice and explicitly reports chapter 01 extended data as not connected;
- `trading-rules/schemas/snapshot.schema.json` is a closed schema (`additionalProperties: false`), and its `providerQuality.status` describes provider outcomes rather than derived-analysis quality.

The attached free-data-source survey is a candidate-source catalog, not a verified provider contract. It identifies potentially useful sources such as the TDX package, mootdx, Baostock, and public Shenwan classification material, but it also states that limits and policies require independent verification. In particular, it does not prove complete historical Shenwan stock membership, a Shanghai/Shenzhen/Beijing-wide front-adjusted series, production throughput for roughly 5,000 securities over 272 sessions, or the right to automate, retain, and redistribute each underlying dataset.

Other active sector fallback and enrichment changes may alter current-day provider acquisition. This design therefore adds a separate canonical analysis path and does not change their fallback order, provider identity, or latest-only contract.

## Goals / Non-Goals

**Goals:**

- Add a replayable, exact-date Shenwan Level 1 data model and a deterministic analysis pipeline without creating look-ahead bias.
- Reuse the audited TDX package for original daily amount while independently gating classification, membership, adjustment, and benchmark capabilities.
- Keep provider observations, derived-analysis quality, and backfill task state separately visible and auditable.
- Preserve the five-dataset collection contract and provider-free GET paths while adding an explicit operator backfill workflow.
- Add chapter 05 analysis as an optional, backward-compatible `sectors` response extension and bridge only proven same-date metrics into a versioned canonical trading snapshot.
- Make every calculation reproducible from immutable source, classification, membership, universe, adjustment, benchmark, calculation, and rule revisions.

**Non-Goals:**

- Supporting concept/theme continuity or allowing one security to contribute to multiple analysis sectors.
- Inferring historical Shenwan membership from current provider names, current constituents, or fuzzy mappings.
- Automatically assigning “leader”, “institutional core”, or “catch-up” roles.
- Turning historical backfill into a sixth normal collection dataset, a GET side effect, a startup action, or an enabled schedule.
- Selecting a provider merely because the attached survey describes it as free; production promotion requires separate capability and data-rights evidence.
- Running real provider probes, production backfills, deployments, database mutations outside implementation migrations, or schedule activation as part of ordinary implementation verification.

## Decisions

### 1. Keep provider observations and canonical Shenwan analysis as separate identities

The existing `sectors.rows` remain provider observations with their original provider taxonomy, identifiers, date evidence, fallback lineage, and enrichment metadata. A provider row may reference a canonical Shenwan identity only through an approved, versioned, exact-date mapping; the mapping never replaces the provider identity.

The analysis path accepts only canonical Shenwan Level 1 identities and point-in-time membership. It does not consume an Eastmoney, Fuyao, THS, HTML, concept, or normalized-name identity as if it were Shenwan. Ambiguous or missing mappings remain unlinked and reduce coverage.

This separation preserves current-day visibility when historical analysis is insufficient and prevents provider taxonomy changes from rewriting analysis history.

**Alternative considered:** normalize all provider sector names into one shared sector table. This was rejected because names are not stable identifiers, taxonomies overlap, and the same label does not prove historical membership or exact-date equivalence.

### 2. Store immutable point-in-time facts and versioned derived results in PostgreSQL

Add repository ports and PostgreSQL implementations for six logical record families:

1. taxonomy revisions and Shenwan Level 1 identities, including effective intervals and source checksums;
2. security-to-industry membership intervals with canonical security identity, inclusive `validFrom`, exclusive `validTo`, source revision, and evidence checksum;
3. exact-date security facts that keep original OHLC/amount and front-adjusted price facts in separate versioned fields;
4. exact-date `ordinary-a-share-equal-weight-v1` benchmark facts with ordered session evidence and series revision;
5. industry daily aggregates with metric-specific eligible counts, exclusions, universe version, input checksums, and calculation version;
6. sector continuity results and backfill runs/date attempts, including metric traces, candidates, unique validation item, missing inputs, compatible retained result, and per-date outcome.

Authoritative uniqueness is based on business identity plus all revisions that affect meaning, rather than date alone. Re-importing identical evidence is idempotent. Different checksums or revisions create an auditable conflict or new version; they do not silently overwrite historical evidence.

These repositories join the existing application-owned port/unit-of-work boundary. PostgreSQL remains the production store; test fixtures may use in-memory or isolated test adapters, and SQLite must not become a silent production fallback.

**Alternative considered:** store the whole history inside the existing `sectors` snapshot JSON. This was rejected because interval membership, per-security facts, per-date retries, uniqueness, and deterministic reprocessing need queryable identities and transactional constraints.

### 3. Gate each input capability independently and treat the attachment as discovery evidence only

Capability reports are keyed by dataset, source, and revision rather than approving a provider globally. At minimum, use separate capabilities for:

- `shenwan-taxonomy`;
- `shenwan-point-in-time-membership`;
- `stock-adjusted-price`;
- `tdx-original-daily-facts`;
- `benchmark-history`.

Each report records exact-date proof, historical range, market/universe coverage, identity rules, pagination and duplicate checks, field semantics and units, revision/checksum, request budget, permission/rate-limit outcomes, data-rights review, negative cases, and redacted evidence. Front-adjustment probes must include known corporate-action samples; checking only an API parameter name is insufficient. Classification probes must prove stock-level effective intervals, not only an industry-name change table.

The initial source strategy is:

- reuse the existing audited TDX daily package for original daily facts and the all-market amount denominator;
- allow Baostock, mootdx/ex-right data, or another adapter to provide adjusted-price candidates only for markets and dates their approved report proves;
- ingest Shenwan taxonomy and membership from a versioned operator-controlled import or approved adapter after data-rights and completeness review;
- derive the fixed `ordinary-a-share-equal-weight-v1` benchmark from the same eligible front-adjusted ordinary-A-share universe and freeze its identity in the calculation revision.

Baostock's lack of Beijing Stock Exchange coverage, mootdx's raw/unadjusted ambiguity, or an incomplete membership source cannot be hidden by combining labels. Amount-only evidence may continue to support amount metrics while price/MA20 metrics remain null. A capability revision change invalidates prior approval until reviewed.

Real probes require an explicit authorization flag, after-hours execution, isolated storage, and redacted reports; they never write formal market snapshots. CI and pull-request validation use fixed offline fixtures only.

**Alternative considered:** make one free library the source of every input. This was rejected because no surveyed source proves the required taxonomy, membership, full-market adjustment, amount, benchmark, throughput, and usage-rights contract by itself.

### 4. Run historical work through a dedicated resumable backfill application service

Historical preparation is an explicit CLI/application command, not part of `SUPPORTED_COLLECTION_DATASETS`. A request resolves any explicit finite trading-session range from the authoritative calendar, defaults the initial warm-up to 272 sessions, permits smaller repair or larger research ranges, pins all source and calculation revisions, and creates a parent run with per-date stages:

1. resolve taxonomy and point-in-time membership;
2. acquire or load security, adjustment, and benchmark facts;
3. audit exact-date and universe coverage;
4. build immutable industry daily aggregates;
5. compute continuity metrics and materialize the same-date result.

Every stage commits through a narrow unit-of-work boundary. Successful compatible dates are skipped on resume; failed, missing, insufficient, or conflicting dates stay retryable. One date cannot roll back other dates. A new data, classification, adjustment, benchmark, or calculation revision produces a new result identity.

The existing full collection action still creates exactly five tasks. Dashboard GETs, section reads, status reads, startup, and default-disabled scheduling cannot create a backfill run. Backfill status is exposed as related sector-analysis readiness, not as a sixth collection row.

**Alternative considered:** extend the existing latest-only `sectors` collector to loop over history. This was rejected because it would weaken its date-capability guard, mix provider observations with canonical facts, and make normal collection unexpectedly expensive.

### 5. Put formulas in pure domain analysis and persist their complete traces

Implement point-in-time aggregation and chapter 05 calculations as pure functions over normalized facts. Provider adapters only acquire and normalize; repositories only persist; HTTP/CLI layers only translate contracts. The calculation revision freezes the benchmark, relative-strength combination rule, disagreement-event definition, percentile method, tie-breaking, thresholds, and candidate/stage precedence defined by the specs.

The persisted result contains raw numerators/denominators, eligible/excluded counts, sample dates, 5-day and 20-day sub-results, rolling-observation counts, deterministic midrank percentiles, canonical rule input, score, original and normalized weights, vetoes, and missing reasons. Industry return and the fixed all-A benchmark use equal-weight valid front-adjusted close-to-close member returns. Internal structure contains only measurable facts such as amount rank, return rank, limit counts, contribution ratio, and diffusion ratio.

Percentiles are based on valid historical observations, not calendar-day padding. Sixty to 249 observations produce at most reduced confidence; fewer than 60 keep the affected percentile and score null. Zero denominators, immature disagreement events, membership conflicts, adjustment gaps, benchmark gaps, and amount gaps remain explicit. Identical normalized inputs and revisions must produce identical serialized analysis output.

**Alternative considered:** recompute formulas independently in the dashboard and trading-rule builder. This was rejected because it would create divergent definitions and make evidence hashing irreproducible.

### 6. Extend `SectorEvidence` additively with an optional analysis object

Keep the existing `rows`, `state`, and `quality` fields unchanged and add optional `analysis`. The object carries:

- `asOf`, analysis status, confidence, coverage, missing inputs, and latest attempt;
- source/data/classification/membership/universe/adjustment/benchmark/calculation versions and evidence references;
- history requirements, valid observations, date ranges, and gaps;
- five metric traces and rule evidence;
- at most three deterministically ordered candidates, their stage, risk/veto, and internal-structure facts;
- exactly one structured next-session validation item when the contract permits one.

Provider observation quality remains in `sectors.quality`; derived quality lives in `sectors.analysis.quality`; execution status lives in the backfill/analysis attempt object. Their enums are not reused interchangeably.

The chapter 05 page renders the analysis panels first when present and retains the existing provider ranking table as a separately labeled exact-date provider observation when that date was actually proven. When analysis is absent or insufficient, it displays the exact gaps and never derives the five metrics from ranking rows. The data-management page displays history/readiness and retry eligibility without changing “collect all”. All visible text and mobile layout continue to satisfy the repository's 14px and 390px constraints.

**Alternative considered:** replace the current provider ranking payload with Shenwan results. This was rejected because it would break existing consumers and erase independent observation evidence.

### 7. Introduce canonical trading snapshot v2 while continuing to replay v1 fixtures

The current closed snapshot schema cannot carry structured metric provenance. Add a canonical snapshot v2 that retains existing fields and adds a closed `metricProvenance` object keyed by canonical metric name. A sector provenance entry includes source dataset, actual date, analysis quality, history and constituent coverage, data/classification/membership/universe/adjustment/benchmark/calculation versions, and evidence references.

The validator/evaluator continues accepting immutable v1 snapshots for existing fixtures and historical replay. The production builder emits v2 after this bridge is enabled. In v2, any present chapter 05 metric requires compatible same-date provenance; incompatible or observation-only input is omitted or null and follows the existing missing-data policy. Snapshot hashing includes normalized provenance as well as values, so a revision change creates a distinct snapshot identity even when a displayed number is unchanged.

The builder reads the local materialized market-environment result and never calls a provider or recomputes sector formulas. The first four scalar metrics come from the first deterministically ranked canonical Shenwan industry, while concentration remains market-wide; no candidate leaves the first four null. Only upstream immutable evidence references enter the snapshot hash, never the identifier of the evidence bundle being generated. Rule IDs, input names, evaluator names, weights, YAML paths, and calibration state remain stable.

**Alternative considered:** keep schema v1 and put provenance in warning strings. This was rejected because warnings are not typed, complete, or reliably included in compatibility checks and deterministic evidence identity.

### 8. Keep rollout fail-closed and preserve evidence on rollback

Feature gates separately control source adapters, historical backfill execution, analysis materialization, API exposure, and trading-snapshot bridging. All remain disabled until their prerequisites and offline tests pass. Scheduled collection remains `enabled=false` and `suspend=true`; this change does not activate a CronJob.

Rollback disables analysis materialization and snapshot bridging, stops or prevents new backfill runs, and returns the API/UI to observation-only behavior. It does not delete taxonomy revisions, facts, aggregates, results, capability reports, or backfill history. Existing five-dataset collection and same-date provider observation retention continue unchanged.

## Risks / Trade-offs

- **[Historical Shenwan membership is incomplete or not licensed for the intended use]** → Keep membership as an independently approved capability, support versioned operator import, expose unmapped/conflicting coverage, and leave dependent outputs `insufficient` until evidence and data rights are approved.
- **[No single adjusted-price source covers Shanghai, Shenzhen, Beijing, delisted stocks, and corporate actions consistently]** → Preserve raw amount separately, approve adjusted-price capability per market/date, test known corporate actions, and degrade only price-dependent metrics instead of claiming full-A completeness.
- **[A 272-session full-market backfill is slow or rate-limited]** → Use bounded date batches, persisted per-date progress, idempotent resumes, request budgets, provider-specific concurrency limits, and offline throughput tests before any authorized production run.
- **[Provider schemas, limits, permissions, or terms change]** → Bind approval to exact revisions/checksums, reuse unified transport controls for HTTP, add bounded controls for TCP/import paths, and require a new report before promotion.
- **[Point-in-time identities conflict across renames, mergers, code migrations, or Beijing `920xxx` changes]** → Use canonical security IDs and effective intervals, retain conflicts rather than guessing, and include identity/universe revisions in aggregate checksums.
- **[Analysis versions multiply storage and operational complexity]** → Keep immutable versioned facts/results, index the exact lookup keys, expose one selected compatible revision, and provide retention policy only after evidence requirements are established; never delete evidence as an implicit rollback.
- **[Current active sector fallback/enrichment work changes nearby contracts]** → Implement the analysis as additive repositories and `SectorEvidence.analysis`, re-read active changes before apply, and avoid modifying fallback order or provider row identity.
- **[Snapshot v2 breaks v1-only consumers]** → Accept both versions during migration, keep frozen v1 fixtures, add explicit v1/v2 contract tests, and switch only the production builder after evaluator compatibility is proven.
- **[Empirical thresholds appear authoritative after production data arrives]** → Preserve `needs-backtest`, show threshold provenance, and require the existing calibration/backtest workflow before any status promotion.

## Migration Plan

1. Create/update the required active exec plan and first update product, architecture, repository-guide, runbook, status, quantitative chapter 05, rule coverage, and evidence documentation so the documented contracts precede code.
2. Add fixed offline fixtures and capability-report schemas for taxonomy, membership, adjusted prices, TDX original facts, and benchmark history. Record data-license/terms review separately from client-library licenses.
3. Add additive PostgreSQL migrations, repository ports, unit-of-work wiring, and exact-date integrity constraints. Verify migration and rollback against isolated databases without touching production data.
4. Implement provider-neutral import/acquisition adapters and capability gates. Keep all real adapters disabled; run only offline success, partial, permission, rate-limit, malformed, mixed-date, duplicate, and corporate-action tests.
5. Implement pure aggregation and chapter 05 analysis with deterministic fixture tests for look-ahead, history thresholds, conflict handling, candidate ordering, crowding veto, unique validation text, and null semantics.
6. Add the explicit resumable backfill CLI/application command and provider-free status projection. Verify bounded fixture runs and interruption/resume; do not attach it to GET, startup, “collect all”, or scheduling.
7. Add optional `SectorEvidence.analysis`, materialization, HTTP contracts, dashboard types, chapter 05 panels, and data-management readiness display. Preserve observation-only compatibility and mobile/accessibility constraints.
8. Add snapshot v2 validation, v1 replay compatibility, same-date market-environment bridge, structured provenance hashing, and observation-only/partial-input rule tests.
9. Run focused and full offline verification, OpenSpec strict validation, rule validation/coverage/docs sync, frontend tests/build, architecture checks, and the full docs contract.
10. Treat real capability probes, any non-fixture backfill, production migration/deployment, and schedule activation as separately authorized operations. If authorized later, start with a small date range, inspect coverage/checksums, then expand to 60 and finally 272 sessions.

Rollback disables the new gates and snapshot bridge first, waits for in-flight bounded work to settle or become retryable, and serves the existing observation-only response. Schema additions and historical evidence remain in place for audit and future resume; no rollback step deletes production data.
