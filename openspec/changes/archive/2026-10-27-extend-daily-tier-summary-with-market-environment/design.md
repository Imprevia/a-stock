## Context

See `proposal.md` for motivation. The existing Skill reads exact-date v2 limits resources for two adjacent sessions, normalizes pool membership, computes frozen-tier outcomes, evaluates a conversation-local previous plan, and renders a four-line card. The market-environment service already computes five-state index synchronization, contextual confirmation, MA20 positions, market breadth, turnover confirmation, `marketEvidence`, and a review sentence. Production v2 `overview`, `indices`, `breadth`, and `limits` resources share the materialized aggregate revision for an exact date.

Two constraints shape the extension. First, the environment and tier sections must describe the same current trading session; the sample supplied during discovery demonstrated how plausible numbers from `2026-10-22 -> 2026-10-23` could otherwise be pasted beside `2026-10-26` index evidence. Second, `marketEvidence.directionPattern` can be locally insufficient even when `summary.synchronizationAssessment.patternCode` and the raw index rows remain available, so the consumer needs an explicit evidence precedence without inventing a new market algorithm.

## Goals / Non-Goals

**Goals:**

- Extend the existing deterministic result with a market-environment block sourced from exact-date v2 reads.
- Pin all current-session reads to one revision and fail closed on date or revision mismatch.
- Render the user-confirmed line order with named index groups and auditable values.
- Preserve the tier verification and add a separate environment verification selected from documented Section 01 rules.
- Keep missing environment evidence local to the affected lines whenever a safe combined review remains possible.

**Non-Goals:**

- Change index synchronization, MA20, breadth, turnover, or confidence formulas in the backend.
- Add API routes, persistence, collection behavior, runtime state, or trading-rule YAML.
- Reclassify aggregate limit-up counts as high/middle/low when consecutive-board facts are missing.
- Turn either verification item into a prediction, position instruction, or automatic trade signal.

## Decisions

### 1. Extend the existing script result instead of adding a second summarizer

Add a `marketEnvironment` object to the existing structured JSON and let the current renderer consume both domains. The object carries the current date and revision, named direction groups, named MA20 groups, breadth values and label, turnover values, consistency state, environment conclusion, confidence, evidence gaps, and the environment next-session verification.

This keeps one source for date checks and output ordering. A separate environment script was considered but rejected because combining two independently resolved dates or revisions would recreate the main correctness hazard.

### 2. Use one current-session revision across four provider-free resources

The local adapter first reads v2 `overview`, records its `asOf` and `snapshotRevision`, and supplies that revision to `indices`, `breadth`, `limits`, and every limits pool page for the current session. The previous session keeps its own limits revision because it is a different materialized aggregate. Every response is checked against its requested date and pinned revision before calculation.

The existing limits-only read will be adapted rather than replaced. Fixture input gains an optional environment section carrying the same normalized fields, date, revision, and quality so offline tests do not need a live API.

Alternative considered: read the legacy aggregate endpoint once. Rejected because the Skill already targets the bounded v2 contract and v2 exposes revision-consistent resources without loading unrelated chapter data.

### 3. Prefer canonical assessment, then raw index evidence, without trusting a stale convenience field

Environment normalization uses this precedence:

1. `overview.data.summary.synchronizationAssessment.patternCode`, label, conclusion, and confidence when present;
2. the five raw index `changePct` values to reproduce the already documented five-state observation only when the assessment is absent;
3. `marketEvidence` for counts and numeric summary values when present, cross-checked against normalized index and breadth rows.

`marketEvidence.directionPattern` is not a hard prerequisite because existing materializations can expose it as `missing-today` while the assessment and raw rows are valid. Conflicting non-null canonical fields fail the environment conclusion instead of choosing whichever arrived first.

Alternative considered: trust `reviewSentence.fullSentence`. Rejected because it is display text, does not guarantee named index groups, and cannot safely drive structured verification.

### 4. Treat named groups as deterministic rendering facts

The five expected display names retain the canonical order: 上证指数、深证成指、创业板指、沪深300、中证500. Returns above zero are rising, below zero are falling, and exactly zero are flat. MA20 grouping compares the same row's close with MA20; equality is rendered on the upper/non-broken side to match the existing `close >= ma20` calculation. Missing rows or comparisons are named under data-insufficient.

When only one MA20 group is populated, render only that group, as in `MA20下方：...`. When positions are mixed, render `MA20上方：...；MA20下方：...` on the same required line. Counts may accompany the facts elsewhere but never replace the names.

### 5. Reuse breadth labels and documented environment interpretation

The breadth line uses v2 breadth `widthLabel`, `widthLabelReason`, and `indexConsistent`; the script computes consistency only when those fields are absent, using the documented positive boundary (`advanceRatio >= 55%` and median return `> 0`), negative boundary (`advanceRatio <= 45%` and median return `< 0`), and observed index direction. It does not synthesize a new breadth label when the canonical label is present.

The final environment conclusion follows the Section 01 category order: data insufficient; broad-strength candidate; index/stock divergence; broad-weakness candidate; otherwise undetermined/rotation. Qualifiers such as `弱势分化、保持观察` may summarize negative breadth and MA20 context, but cannot upgrade `undetermined_divergence` to broad weakness unless the documented four-of-five direction gate is met. Confidence comes from `synchronizationAssessment` when available and is capped by missing or conflicting required evidence.

### 6. Keep two explicit verification namespaces

The existing `previousPlan` and `nextSessionVerification` remain tier-only. Add `previousEnvironmentPlan` only when a traceable prior environment sentence exists, plus `marketEnvironment.nextSessionVerification` for today's environment. The final prose has:

- one tier line such as `下一交易日只验证低位层` with confirmation and invalidation conditions;
- one final environment line selected by the documented A1-A5 priority: missing input, contradiction, neutral dimension, default breadth persistence, or growth-turnover exception.

The environment line selects one observation concept. A paired breadth condition (`上涨占比` plus `全A涨跌幅中位数`) counts as one concept because the documented breadth state requires both fields.

Alternative considered: merge both into one global next-session check. Rejected because tier continuity and whole-market participation test different hypotheses and the user explicitly requested both.

### 7. Render the full card from structured values

The renderer follows the specification's fixed order and contains no literal `___` placeholders. It formats ratios and percentages consistently, preserves source precision where meaningful, and emits `数据不足（原因）` for a missing line. Tier prose remains evidence-rich rather than returning only labels; the exact adjectives may vary as long as their counts and selected structural label are stable.

Tests assert values, order, dates, revisions, names, and thresholds rather than matching every generated adjective. A synthetic case modeled on the discovery example covers one rising/four falling, all five below MA20, negative breadth, neutral turnover confirmation, a failed high-tier prior plan, low-tier expansion, and two distinct verification lines.

## Risks / Trade-offs

- [Some historical aggregates have incomplete `marketEvidence` convenience fields] -> Prefer `synchronizationAssessment` and raw index/breadth resources; mark only unresolved conflicts insufficient.
- [Four v2 reads can observe a rebuild boundary] -> Pin the overview revision on every subsequent current-session read and fail closed on HTTP 409 or revision mismatch.
- [A descriptive qualifier can look like a new trading state] -> Keep canonical pattern/category fields in JSON, mark qualifiers as display wording, and retain `needs-backtest`/non-predictive language.
- [Two verification lines may be mistaken for duplicate instructions] -> Name one with an explicit tier and reserve the final unqualified line for the environment field; document both namespaces in the Skill.
- [Limits data may have aggregate counts but missing valid streak membership] -> Preserve aggregate pool facts while marking tier conclusions and tier verification insufficient.
- [Fallback or partial data may lower overall confidence] -> Propagate per-domain quality and cap only conclusions that depend on the degraded fields rather than zero-filling.

## Migration Plan

1. Create and index a new active execution plan before implementation edits.
2. Extend the Skill references and structured fixture contract, then add environment normalization and revision-pinned v2 reads to the deterministic script.
3. Update rendering and synthetic tests for the full card, cross-date rejection, revision mismatch, partial evidence, and the two verification namespaces.
4. Run the Skill validator, focused pytest, OpenSpec strict validation, diff checks, and the full docs-contract gate.
5. Roll back by reverting only the Skill package, its tests/fixtures, and documentation entries; no database or deployment migration is required.
