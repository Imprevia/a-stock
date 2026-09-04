## Context

The active `index-combination-rework` change adds five-state index synchronization, but the current service still uses a single synchronization label when composing the four-question market overview. This loses the distinction between an observed index relationship and the evidence required to interpret that relationship. In particular, growth leadership shares the synchronized-rally strength branch, weight shelter falls into generic divergence, and broad weakness can select risk control before turnover and trend damage are jointly confirmed.

The repository already has the required same-day inputs: five index changes, moving averages, 5-day turnover ratios, volume-price states, index combination evidence, and exact-date breadth snapshots. It also stores core index history, which can identify the actual previous trading date without introducing a holiday-calendar dependency. Normal market-environment GET paths are required to remain local snapshot reads.

## Goals / Non-Goals

**Goals:**

- Separate direction-pattern observation from contextual market interpretation.
- Produce distinct, auditable conclusions for synchronized rally, weight shelter, growth leadership, broad weakness, and undetermined divergence.
- Use breadth, trend position, and turnover as explicit confirmation dimensions with independent statuses and numeric evidence.
- Compare breadth with the exact previous trading day when the corresponding local snapshot exists.
- Add an additive API object and a dedicated Section 01 view without breaking current response consumers.
- Prevent missing or conflicting risk evidence from being silently treated as confirmation.

**Non-Goals:**

- Do not change the existing five-state direction thresholds or precedence.
- Do not change the six index-combination definitions, rule IDs, scoring weights, or golden trading-rule traces.
- Do not infer named defending industries from index direction alone.
- Do not add provider calls to normal GET paths, backfill missing historical breadth, or add a trading-calendar dependency.
- Do not turn the assessment into an automated trading instruction.

## Decisions

### D1: Use a two-stage model

`syncPattern` remains a fact-like classification derived only from the five daily index changes. A new `synchronizationAssessment` interprets that pattern using confirmation evidence.

```text
five index changes -> syncPattern
                         |
                         +--> breadth confirmation
                         +--> trend confirmation
                         +--> turnover confirmation
                                      |
                                      v
                         synchronizationAssessment
```

This prevents later evidence from rewriting what the indices actually did and allows a pattern to be confirmed, contradicted, unconfirmed, or insufficient. Replacing `syncPattern` with a richer state machine was rejected because it would change an existing trading-rule input and blur observation with interpretation.

### D2: Return three independently auditable confirmation dimensions

The assessment contains `breadth`, `trend`, and `turnover` dimensions. Each dimension returns `status`, the numeric inputs used, dated evidence where applicable, and a reason when it is unavailable.

- **Breadth:** current `advanceRatio` and `medianReturn`; positive means `advanceRatio >= 0.55` and `medianReturn > 0`, negative means `advanceRatio <= 0.45` and `medianReturn < 0`, otherwise mixed. If exact previous-day breadth exists, return both deltas; both deltas above zero mean improving and both below zero mean worsening.
- **Trend:** count valid indices above and below MA20. At least three below MA20 confirms broad trend damage; at least three above MA20 confirms broad positive positioning. Mixed counts remain neutral.
- **Turnover:** use existing index `amountRatio5`, daily change, and `volumePriceState`. Growth confirmation uses the median ratio of ChiNext and CSI 500. Systemic-decline confirmation requires at least three indices with `volumePriceState == "放量下跌"` or the equivalent existing condition of negative change at or below the decline threshold with `amountRatio5 >= 1.2`.

The design reuses existing documented thresholds rather than introducing a second threshold family. A single synthetic market-turnover number was rejected because summing overlapping index amounts would double-count securities and imply a precision the current data does not support.

### D3: Map patterns to conclusions through explicit gates

The service uses a pure calculation function with the pattern and three dimensions as inputs. It returns a closed assessment status and stable conclusion code.

| Pattern | Confirmed gate | Confirmed conclusion code |
|---|---|---|
| `synchronized_rally` | positive breadth; improving prior-day breadth raises confidence | `broad-strength-confirmed` |
| `weight_shelter` | negative breadth | `weight-shelter-confirmed` |
| `growth_lead` | positive breadth and growth-group median `amountRatio5 >= 1.0` | `growth-lead-confirmed` |
| `broad_weakness` | negative breadth, at least 3 below MA20, at least 3 volume-backed declines | `systemic-decline-confirmed` |
| `undetermined_divergence` | no confirmation gate | `undetermined-divergence` |

Unconfirmed and contradictory outcomes use pattern-specific codes such as `index-strength-breadth-divergence`, `weight-lead-unconfirmed`, `growth-lead-unconfirmed`, and `broad-weakness-unconfirmed`. `status=insufficient` is used when a required dimension cannot be evaluated. Conclusion text is derived from the code and may be refined without changing the machine contract.

For synchronized rally, prior-day improvement is corroborating evidence rather than a hard gate because a first locally collected day can still have valid current breadth. Its absence caps confidence at `medium`. For broad weakness, all three risk confirmations are hard gates because the source text only calls the decline systemic when volume, key moving averages, and breadth deteriorate together.

### D4: Treat "weight shelter" as a pattern name, not proof of weak stocks

The existing code `weight_shelter` is retained for compatibility, but user-facing interpretation first says that weight indices lead. Only negative breadth permits the stronger conclusion that index strength coexists with weak individual stocks. Named sector attribution is included only if same-date sector evidence explicitly supports it; otherwise the assessment states that the cause is unverified.

Renaming the existing code to `weight_lead` was rejected because it would change the `QTS-01-01-06` input mapping and existing API consumers. The contextual assessment supplies the missing semantic restraint.

### D5: Resolve the previous trading date from core history

The service derives the previous trading date from the latest valid index-history date strictly before the response `asOf`. It then performs an exact `SnapshotStore.get("breadth", previous_date)` lookup. If the snapshot is missing, corrupt, or belongs to another date, the comparison dimension is insufficient. It does not search further backward and does not invoke the provider.

Using the nearest stored earlier breadth snapshot was rejected because gaps in collection could turn a multi-day comparison into a false "previous day" claim. Adding an exchange holiday calendar was rejected as unnecessary for this change because core history already records actual market dates.

Materialized aggregate rebuilds calculate the assessment from the same-date core and breadth data plus the optional exact previous snapshot. Rebuilding a newer date after an older breadth snapshot is collected may refresh the newer aggregate through the existing rebuild path; this proposal does not require automatic backfill of every later aggregate.

### D6: Add an explicit API contract

`Summary` gains optional `synchronizationAssessment` so stored responses and older clients remain valid. The object shape is:

```yaml
patternCode: synchronized_rally | broad_weakness | weight_shelter | growth_lead | undetermined_divergence
patternLabel: string
status: confirmed | unconfirmed | contradicted | insufficient
conclusionCode: string
conclusion: string
confidence: high | medium | low | insufficient
dimensions:
  breadth: { status, currentAsOf, previousAsOf, advanceRatio, medianReturn, advanceRatioDelta, medianReturnDelta, evidence, reason }
  trend: { status, aboveMa20Count, belowMa20Count, validCount, evidence, reason }
  turnover: { status, medianAmountRatio5, growthMedianAmountRatio5, volumeBackedAdvanceCount, volumeBackedDeclineCount, validCount, evidence, reason }
evidence: []
risks: []
```

Dimension status uses `confirming`, `neutral`, `contradicting`, or `insufficient`; the top-level status expresses the pattern-specific result. Numeric fields remain nullable and are never filled with zero for missing data.

The existing `combinationOverview.strength` may consume the new conclusion text, but the new assessment remains the authoritative synchronization explanation. Existing stage and capital-acceptance calculations remain based on the six-combination matrix and volume-price aggregation.

### D7: Present synchronization before the six-combination matrix

Section 01 adds an unframed synchronization assessment band before the current four-question and matrix section. It contains:

- the raw five-state pattern and top-level confirmation badge;
- a concise conclusion and confidence;
- three stable-width confirmation items for breadth, trend, and turnover;
- expandable evidence and risk notices when a dimension is contradictory or insufficient.

The five index changes remain visible as evidence so the result does not become a black box. On mobile, the confirmation items stack vertically; no nested cards or page-level horizontal scrolling are introduced. The six-combination matrix remains responsible for per-index stage/position/volume combinations and is not reused as a substitute for cross-index synchronization.

### D8: Test scenario semantics, not only field presence

Calculation tests use table-driven fixtures for every pattern with confirmed, unconfirmed, contradicted, and insufficient variants where meaningful. Service tests verify exact previous-date lookup and zero provider calls. API tests validate the full object and nullable dimension inputs. Vue tests assert the rendered conclusions and contradictory/missing dimension states for synchronized rally, weight shelter, growth leadership, and systemic decline at desktop and mobile-compatible markup.

## Risks / Trade-offs

- [The previous breadth snapshot may not exist] -> Keep current breadth usable, mark the comparison insufficient, cap confidence, and never substitute another date.
- [Five-state names already imply interpretation] -> Preserve codes for compatibility but make confirmation status and conclusion visually dominant.
- [Per-index turnover is not total-market turnover] -> Describe it as index turnover confirmation, expose the aggregation inputs, and avoid inventing a double-counted total.
- [Hard systemic-decline gates may produce fewer warnings] -> Retain a broad-weakness risk notice even when systemic decline is unconfirmed; only the stronger conclusion requires all gates.
- [Materialized responses can predate a newly added prior-day snapshot] -> Reuse the existing rebuild mechanism and document that historical backfill is explicit, not automatic.
- [New assessment text could diverge from rule documentation] -> Keep stable conclusion codes and scenario tests tied to the product spec and quantified document wording.

## Migration Plan

1. Update the product spec, architecture, runbook, and active execution plan before code changes.
2. Add pure calculation types and tests, then extend schemas with the optional object.
3. Add exact previous-date breadth lookup and service assembly without provider calls.
4. Add the Section 01 presentation and frontend contract tests.
5. Rebuild exact-date materialized aggregates through existing collection or rebuild commands as needed; do not mutate older snapshots.
6. Validate Python tests, frontend tests/build, docs-contract full gate, and strict OpenSpec validation.

Rollback removes the optional field and UI band. Existing snapshots, `syncPattern`, rules, and combination outputs require no data migration and remain readable.

## Open Questions

- Whether a later calibrated version should replace the current fixed breadth boundaries with rolling percentiles remains outside this change and requires historical backtesting.
- Whether same-date sector evidence should become a fourth formal confirmation dimension can be evaluated later; this change only prevents unsupported named-sector attribution.
