## Context

See `proposal.md` for motivation. The repository already exposes exact-date limits summaries, paginated limit-up/failed-limit-up/limit-down pools, risk-tier counts, and failure-repair evidence through provider-free reads. The daily conversational workflow additionally needs previous-tier sample outcomes, prior-plan verification, natural-language date handling, and a stable response format.

The current ad hoc analysis has two correctness hazards: provider rows can repeat, and Eastmoney `zttj.days` describes a multi-day limit pattern rather than the consecutive-board count represented by `lbc`. The Skill must also respect repository boundaries: ordinary reads do not start collection, historical dates are never backfilled from another date, real provider access is read-only and explicit, and runtime market snapshots are not committed.

## Goals / Non-Goals

**Goals:**

- Give another Codex instance enough focused instruction to produce the same evidence-backed daily review without rediscovering the workflow.
- Put normalization, cross-session calculations, quality propagation, and verification-plan evaluation in a deterministic script.
- Keep prose rendering short and stable while exposing the exact counts needed to audit each conclusion.
- Make offline fixtures cover the failures observed in the conversation, especially `lbc` versus `zttj.days` and duplicate rows.

**Non-Goals:**

- Add or change a market-data API, database schema, collection job, dashboard page, trading rule, or production schedule.
- Promote QTS-01-04 rules from `needs-backtest`, compute a risk score, or produce buy/sell advice.
- Persist conversation state or daily market snapshots in the repository.
- Treat an external provider's latest response as valid historical evidence when its date contradicts the request.

## Decisions

### 1. Use one domain Skill with a deterministic analysis script

Create one repo-local Skill, `a-stock-daily-tier-summary`, with two natural-language entry points (“今天” and “昨天”) rather than separate date-specific skills. Keep orchestration and response rules in `SKILL.md`; place calculation in `scripts/analyze_tier_summary.py`; place detailed field/source contracts in `references/data-contract.md` and structural interpretation guidance in `references/methodology.md`.

The script emits structured JSON rather than final prose. This makes tier counts, cross-session statuses, repair ratios, quality, and verification results testable while allowing the Skill to render the user's fixed Chinese format.

Alternative considered: instructions-only arithmetic in `SKILL.md`. Rejected because repeated hand-written scripts caused field drift, duplicate counting, and inconsistent thresholds.

### 2. Normalize all sources into one exact-date pool model

The script accepts normalized current and previous session inputs containing source, requested date, actual date evidence, revision/checksum evidence, quality, and three security pools. Local v2 API is the primary adapter:

- read the exact-date limits resource and all pages of each required pool;
- pin each date's own snapshot revision while paging;
- perform no provider calls or writes through GET endpoints.

An Eastmoney adapter is an explicit fallback for completed-session requests when local evidence is unavailable. It records request-parameter date evidence and `qdate` separately; an explicit contradiction fails closed, while request-date-only evidence remains degraded. Network behavior uses bounded timeouts, a descriptive user agent, and no credentials.

Alternative considered: direct Eastmoney as the default. Rejected because it weakens exact-date and provenance guarantees already supplied by the repository.

### 3. Freeze previous tiers and use only verified consecutive-board fields

Tier membership is assigned from the previous session's limit-up pool before current outcomes are examined. Local `streak_days` has priority. Eastmoney fallback uses integer `lbc >= 1`; `zttj.days` and `zttj.ct` are retained only as optional pattern metadata and never influence tier membership.

Normalized identity is exchange plus security code. Duplicate identities within a pool collapse deterministically and add a quality warning. Conflicting duplicates fail the affected row or pool rather than choosing an arbitrary value.

The script computes:

- previous high/middle/low sample sizes;
- current outcome counts (`continued_limit_up`, `failed_limit_up`, `limit_down`, `outside_observed_pools`) for each frozen tier;
- current high/middle/low limit-up counts;
- pool-count changes;
- failed-sample repair numerator, denominator, and nullable ratio.

Alternative considered: assign outcomes using the current streak. Rejected because it introduces hindsight and changes the sample under evaluation.

### 4. Keep previous-plan verification conversation-local and structured

`SKILL.md` extracts the most recent traceable “下一交易日只验证…” statement from conversation context into optional structured input for the script. The script evaluates explicit count/ratio predicates against current evidence and returns one of `confirmed`, `invalidated`, `inconclusive`, `conflicting`, or `unavailable` with observed values.

The Skill does not create a state database or append runtime files. A future automation may supply the same structured verification object explicitly without changing the calculation contract.

Alternative considered: persist the last plan under the repository. Rejected because daily state is a runtime artifact and would create hidden writes during a reporting request.

### 5. Separate facts from descriptive classification

The deterministic JSON exposes facts first. `references/methodology.md` maps those facts to the five wording labels from the source document:

- `扩散`: at least two layers weaken and risk reaches or includes the high tier;
- `抱团`: high-tier retention remains clearly stronger while middle/low feedback is weak;
- `低位试错`: high and middle remain weak while new low-tier supply expands without confirmed continuation;
- `修复`: limit-down/failed pressure contracts and failed samples show observable repair;
- `混合`: signals conflict, remain borderline, or do not satisfy a stronger description.

These are descriptive gates, not QTS scores. The implementation must expose the evidence used and default to `混合` or `数据不足` when the stronger label is not supported. Any numeric presentation thresholds used to make wording consistent are documented as unvalidated defaults and are not written into trading-rule YAML.

### 6. Select one next-session layer without producing a trade signal

The Skill chooses the layer with the clearest unresolved structural question and adequate sample size. Confirmation and invalidation are frozen against today's named sample and expressed as integer counts or ratios. They describe what would validate the market-structure hypothesis, not an order, position size, or expected return.

When no layer has adequate evidence, the Skill emits no fabricated condition and states that the next verification is pending data.

### 7. Test with synthetic fixtures and validate the Skill package

Offline tests use small synthetic pool fixtures and never fetch providers. Required cases include:

- `lbc=2` with `zttj.days=8` remains middle tier;
- duplicate rows count once and conflicting duplicates degrade quality;
- weekend/holiday target resolution identifies the latest completed session explicitly;
- exact-date contradiction fails closed;
- zero failed-sample denominator returns null/insufficient;
- previous-plan confirmation, invalidation, inconclusive, and conflict states;
- partial layer evidence preserves unaffected conclusions.

The implementation also runs the bundled Skill validator and a fixture-based end-to-end invocation that checks structured values, not exact generated wording.

## Risks / Trade-offs

- [External provider cannot prove historical payload dates independently] -> Prefer local exact-date snapshots; mark request-date-only fallback degraded and reject explicit contradictions.
- [The current local pool endpoint may filter incomplete facts] -> Preserve its quality metadata and return insufficient rather than silently switching to a less strict source.
- [“Outside observed pools” can include ordinary trading, suspension, or unavailable evidence] -> Label it neutrally and never equate it with a specific loss without price/return facts.
- [Descriptive labels can look like validated signals] -> Include `needs-backtest` boundaries in the Skill and prohibit scores or trading advice.
- [Conversation history may not contain the previous plan] -> Return `unavailable`; do not persist hidden state or reconstruct the plan after seeing outcomes.
- [Natural-language date resolution can race the market close] -> Use Asia/Shanghai, require a completed session, and state the analyzed date explicitly.

## Migration Plan

1. Create and index the active execution plan required by repository gates before implementation edits.
2. Add the repo-local Skill package, deterministic script, references, and synthetic tests without changing runtime services.
3. Validate with synthetic fixtures, the Skill quick validator, focused pytest, OpenSpec validation, and the full docs-contract gate.
4. Exercise one manual read-only summary against available local exact-date data; external smoke remains optional and requires an explicit completed-session request.
5. Roll back by removing only the new Skill package, its tests, and corresponding documentation/plan entries; no database or production migration is involved.
