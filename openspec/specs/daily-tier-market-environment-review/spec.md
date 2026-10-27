# daily-tier-market-environment-review Specification

## Purpose

为每日高、中、低位复盘补充同一精确交易日的指数方向、趋势位置、市场宽度和成交确认，使 Agent 能按固定中文格式输出可审计的环境与分层联合结论，并分别给出下一交易日的分层验证项和环境验证项。

## Requirements

### Requirement: Environment and tier evidence share one exact trading date
The Skill SHALL combine market-environment evidence, previous-plan verification, tier outcomes, pool changes, and failed-sample repair only when every current-session resource identifies the same completed trading date. Local v2 resources used for the current session MUST share one pinned `snapshotRevision`; previous-session tier resources MAY use their own pinned revision. The Skill MUST NOT combine index or breadth evidence from one date with tier evidence from another date.

#### Scenario: Current resources share date and revision
- **WHEN** overview, indices, breadth, and limits identify the requested completed session and return one common current-session revision
- **THEN** the Skill may produce one combined market-environment and tier review for that date

#### Scenario: Current resource date differs
- **WHEN** any current-session resource explicitly identifies a date different from the requested session
- **THEN** the Skill marks the combined review insufficient and does not substitute or relabel that resource

#### Scenario: Current revisions differ
- **WHEN** current-session v2 resources return different snapshot revisions or a revision changes while pages are being read
- **THEN** the Skill rejects the inconsistent read and does not emit a combined conclusion from mixed revisions

### Requirement: Named index direction and MA20 position lead the review
The review SHALL begin by naming the five major indices grouped by observed daily direction, followed by the indices grouped above and below MA20. A positive return SHALL be rendered as rising, a negative return as falling, and a zero return as flat. An index with a missing return or MA20 comparison MUST be named as data-insufficient instead of being assigned to another group. The first two lines MUST contain index names rather than counts alone.

#### Scenario: One index rises and four fall
- **WHEN** only the SSE Composite rises while Shenzhen Component, ChiNext, CSI 300, and CSI 500 fall
- **THEN** the first line names the SSE Composite as rising and names the other four indices as falling

#### Scenario: All five indices are below MA20
- **WHEN** all five valid closes are below their same-day MA20 values
- **THEN** the second line starts with `MA20下方` and names all five indices

#### Scenario: MA20 positions are mixed
- **WHEN** at least one valid index is above MA20 and at least one valid index is below MA20
- **THEN** the second line contains separate named `MA20上方` and `MA20下方` groups without omitting either group

### Requirement: Breadth and turnover lines expose canonical evidence
After the two named index lines, the Skill SHALL output, in order, the full-market advance ratio, the full-A median return, the median five-index 5-day turnover ratio, the volume-backed advance and decline counts, the canonical breadth label, and whether breadth is consistent with or diverges from index direction. Values SHALL preserve their source semantics; missing values MUST render as data-insufficient and MUST NOT be replaced with zero.

#### Scenario: Negative breadth agrees with mostly falling indices
- **WHEN** the advance ratio is at most 45 percent, the median return is below zero, and more valid indices fall than rise
- **THEN** the review renders the canonical negative width label and states that the core breadth evidence is consistent with the indices

#### Scenario: Negative breadth contradicts rising indices
- **WHEN** the canonical index direction is positive while the advance ratio is at most 45 percent and the median return is below zero
- **THEN** the review states that breadth diverges from the indices without rewriting the observed index pattern

#### Scenario: Turnover evidence is unavailable
- **WHEN** the five-index turnover median or volume-backed counts are unavailable
- **THEN** only the affected turnover line is data-insufficient while valid direction, MA20, and breadth lines remain present

### Requirement: Previous verification and tier conclusions remain evidence-rich
The combined card SHALL retain previous-plan verification, high/middle/low frozen-sample conclusions, failed-sample repair, the primary risk layer, and one descriptive tier structure. Each conclusion SHALL cite the observed numerator, denominator, outcome counts, or pool changes that support it. Previous conditions MUST be evaluated as originally recorded and MUST NOT be reconstructed after observing the current session.

#### Scenario: Previous high-tier plan fails
- **WHEN** a traceable high-tier invalidation condition is satisfied by the current frozen-sample outcomes
- **THEN** the previous verification line identifies failure, cites the original threshold, and cites the current high-tier observations

#### Scenario: Tier evidence supports low-tier trial behavior
- **WHEN** high and middle tiers are weak while current first-board supply expands and repair evidence does not establish broad recovery
- **THEN** the tier conclusion may describe low-tier trial behavior and cites the relevant frozen-sample and pool-change counts

#### Scenario: Tier membership is insufficient
- **WHEN** valid consecutive-board fields are absent for a required tier sample
- **THEN** the affected tier is reported as data-insufficient and aggregate pool counts are not presented as verified tier counts

### Requirement: Tier and environment verification loops remain separate
The combined review SHALL contain one tier verification line and one environment verification line. The tier line SHALL select exactly one valid high, middle, or low current-session sample and express measurable confirmation and invalidation thresholds against that frozen sample. The environment line SHALL select exactly one documented breadth, MA20, or turnover field according to the Section 01 verification priority and express its measurable threshold and expected direction. Neither line SHALL absorb, replace, or silently omit the other.

#### Scenario: Low tier is the selected structural question
- **WHEN** the low tier has valid current samples and is selected as the unresolved structural layer
- **THEN** the card contains one `下一交易日只验证低位层` line with explicit confirmation and invalidation counts

#### Scenario: Breadth is the selected environment question
- **WHEN** current breadth is the first contradictory or unresolved environment dimension
- **THEN** the final line selects only advance ratio plus full-A median return and includes their numeric confirmation or invalidation boundary

#### Scenario: One verification domain is insufficient
- **WHEN** tier evidence is insufficient but environment evidence is complete, or the reverse
- **THEN** the insufficient verification line states that no condition can be determined while the other valid verification line remains intact

### Requirement: Combined review follows the confirmed line order
The Skill SHALL render the combined review in this order: named index direction; named MA20 groups; advance ratio; full-A median return; median five-index 5-day turnover ratio; volume-backed advance/decline counts; breadth label; breadth-versus-index relation; previous verification; tier conclusions; primary risk layer and tier structure; one tier verification; overall environment conclusion; confidence; and one environment verification. The environment conclusion SHALL use the documented Section 01 states or a qualified wording derived from them, and confidence SHALL describe evidence completeness and consistency rather than future return probability.

#### Scenario: Complete combined review
- **WHEN** current environment evidence, adjacent-session tier evidence, and a prior verification plan are complete
- **THEN** all required lines appear once in the specified order with their source values and no unresolved placeholder text

#### Scenario: Undetermined direction has negative context
- **WHEN** the five-index pattern is undetermined, breadth is negative, all five indices are below MA20, and turnover does not confirm volume-backed decline
- **THEN** the overall conclusion uses qualified weak-divergence observation wording rather than upgrading the day to confirmed broad weakness

#### Scenario: Confidence remains non-predictive
- **WHEN** the card reports low, medium, high, or insufficient confidence
- **THEN** the confidence refers to current evidence coverage and agreement and is not described as a probability of next-session gains or losses
