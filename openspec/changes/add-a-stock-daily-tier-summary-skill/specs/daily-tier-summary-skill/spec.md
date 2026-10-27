## Purpose

为盘后研究 Agent 提供精确交易日、质量受控且可重复的高位、中位、低位亏钱效应总结，并在输出当日结构判断前验证上一交易日预设条件是否兑现。

## ADDED Requirements

### Requirement: Natural-language dates resolve to a completed trading session
The Skill SHALL interpret relative dates in Asia/Shanghai and SHALL resolve “今天” or “昨天” to an explicitly identified completed trading session. When the literal calendar date is a weekend or market holiday, the response MUST state that the date was closed and identify the latest completed trading session used for analysis.

#### Scenario: Today is a completed trading day
- **WHEN** the user asks for today's summary after the session has completed and exact-date evidence exists
- **THEN** the Skill analyzes that trading date and names it in the result

#### Scenario: Yesterday was a non-trading day
- **WHEN** the user asks for yesterday's summary and yesterday was a weekend or market holiday
- **THEN** the Skill states that yesterday was closed and analyzes the latest completed trading session without presenting it as yesterday's market data

#### Scenario: Completed session cannot be proven
- **WHEN** neither a trusted trading calendar nor source date evidence can prove the target completed session
- **THEN** the Skill returns `insufficient` and does not substitute data from another date

### Requirement: Exact-date read-only evidence is preferred and quality is preserved
The Skill SHALL prefer the repository's exact-date, provider-free market-data API or local snapshots and SHALL consume all required pages under the corresponding snapshot revision. External market data MAY be read only for an explicitly requested completed-session summary when local evidence is unavailable, and any request-date-only evidence or date inconsistency MUST be reflected in the quality status. The Skill MUST NOT trigger collection jobs, mutate application storage, or relabel another date's evidence as the target date.

#### Scenario: Local exact-date evidence is complete
- **WHEN** local limit-up, failed-limit-up, and limit-down pools for both adjacent trading sessions are complete and revision-consistent
- **THEN** the Skill uses those pools without contacting an external provider

#### Scenario: External fallback has request-date-only evidence
- **WHEN** local evidence is unavailable and an authorized external read returns the requested pools without an independently matching payload date
- **THEN** the Skill marks the source as degraded, records the date-evidence limitation, and does not describe the result as fully verified

#### Scenario: Source contradicts the requested date
- **WHEN** a source explicitly identifies a trading date different from the requested date
- **THEN** the Skill rejects that source for the summary and returns `insufficient` unless another exact-date source is available

### Requirement: Securities and consecutive-board tiers are normalized deterministically
The Skill SHALL deduplicate rows by normalized exchange-qualified security identity before calculating any count. It SHALL use verified local `streak_days` when available and SHALL use Eastmoney `lbc` only as the external consecutive-board fallback. It MUST NOT use `zttj.days` as the consecutive-board count. A valid streak of four or more SHALL be high tier, two or three SHALL be middle tier, and one SHALL be low tier.

#### Scenario: Provider returns duplicate security rows
- **WHEN** the same normalized security appears more than once in a pool
- **THEN** the Skill counts that security once and reports the duplicate-data warning

#### Scenario: Pattern days differ from consecutive boards
- **WHEN** an external row contains `lbc=2` and `zttj.days=8`
- **THEN** the Skill classifies the security as middle tier using `lbc=2`

#### Scenario: Consecutive-board field is missing
- **WHEN** a limit-up member has neither verified `streak_days` nor valid `lbc`
- **THEN** the Skill excludes that member from tier counts, retains it in the aggregate pool count, and lowers tier-data quality rather than inferring a tier

### Requirement: Adjacent-session tier outcomes and failed-sample repair are calculated from frozen samples
For each tier, the Skill SHALL freeze membership from the previous trading session and classify each member's current-session outcome as continued limit-up, failed limit-up, limit-down, or outside the three observed pools. It SHALL separately report current-session high, middle, and low tier counts. Failed-sample repair SHALL equal the normalized intersection of the previous failed-limit-up pool and the current closed-limit-up pool divided by the previous failed-limit-up sample count.

#### Scenario: Previous high-tier samples split across outcomes
- **WHEN** five previous high-tier securities include three current limit-ups, one current failed limit-up, and one current limit-down
- **THEN** the high-tier conclusion reports all five samples and the `3/1/1/0` outcome distribution without reclassifying them by current streak

#### Scenario: Failed samples are repaired
- **WHEN** two of twenty previous failed-limit-up securities close at limit-up in the current session
- **THEN** the Skill reports a repair ratio of `2/20=10.0%`

#### Scenario: Failed-sample denominator is zero
- **WHEN** the complete previous failed-limit-up pool contains zero securities
- **THEN** the Skill reports the repair ratio as `null` or `insufficient` and does not present `0%`

### Requirement: Previous verification conditions are evaluated without hindsight
When a traceable previous-session verification plan is present in the conversation or supplied structured input, the Skill SHALL evaluate its named layer, confirmation conditions, and invalidation conditions against current evidence before producing the new summary. It MUST NOT invent, loosen, or retrospectively replace the previous conditions. If no traceable plan exists, the Skill SHALL say so explicitly.

#### Scenario: Confirmation conditions all pass
- **WHEN** every recorded confirmation condition is satisfied and no recorded invalidation condition is satisfied
- **THEN** the Skill reports the previous verification as confirmed and cites the observed counts

#### Scenario: Invalidation condition passes
- **WHEN** at least one recorded invalidation condition is satisfied and the confirmation set is not simultaneously satisfied
- **THEN** the Skill reports the previous verification as invalidated and cites the triggering condition

#### Scenario: Conditions are inconclusive or conflicting
- **WHEN** neither condition set is satisfied, or both condition sets are satisfied because the recorded plan overlaps
- **THEN** the Skill reports an inconclusive or conflicting verification result instead of forcing success or failure

#### Scenario: No previous plan is available
- **WHEN** the conversation and supplied inputs contain no traceable previous verification plan
- **THEN** the Skill reports that the previous verification result is unavailable and continues only with the current evidence

### Requirement: Structural labels remain descriptive and evidence-backed
The Skill SHALL choose at most one of `扩散`, `抱团`, `低位试错`, `修复`, or `混合` from the observed tier outcomes, pool changes, and repair evidence. It SHALL treat the labels as descriptive research output under `needs-backtest`, cite the supporting counts, and MUST NOT emit an unvalidated 0–100 score or an automatic trading recommendation.

#### Scenario: High tier holds while lower tiers weaken
- **WHEN** high-tier continuation remains materially stronger while middle and low tier continuation deteriorate
- **THEN** the Skill may label the structure `抱团` and cites the tier outcome contrast

#### Scenario: Signals conflict
- **WHEN** tier outcomes, limit-down changes, failed-limit-up changes, and repair evidence point in different directions
- **THEN** the Skill labels the structure `混合` rather than selecting a stronger directional label

#### Scenario: Evidence coverage is insufficient
- **WHEN** a required adjacent pool or tier field does not meet the documented quality boundary
- **THEN** the Skill reports `数据不足` for the affected conclusion and does not infer a safer state from missing data

### Requirement: Summary output follows the fixed review card
The Skill SHALL return concise Chinese output containing the previous verification result, the three tier conclusions with sample counts, failed-sample repair with numerator and denominator, the primary risk layer, one structural label, and exactly one layer to verify in the next trading session with measurable confirmation and invalidation conditions.

#### Scenario: Complete evidence is available
- **WHEN** both adjacent sessions and the previous verification plan are complete
- **THEN** the response contains the previous verification paragraph followed by the fixed three-line review card with explicit counts and ratios

#### Scenario: One layer is insufficient
- **WHEN** one layer lacks valid tier evidence but other evidence is valid
- **THEN** the response preserves the valid conclusions, marks only the affected layer as insufficient, and does not replace its values with zero

#### Scenario: Next-session verification is emitted
- **WHEN** at least one layer has adequate current evidence
- **THEN** the Skill selects one layer only and expresses both confirmation and invalidation as observable next-session counts or ratios based on the frozen current sample
