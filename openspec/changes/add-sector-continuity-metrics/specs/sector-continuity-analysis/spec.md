## Purpose

为盘后研究提供仅基于申万一级行业、可审计且可降级的主线持续性分析，统一生成五项规则指标、候选阶段、抱团风险和一条下一交易日验证项，并防止缺失数据或概念重叠造成虚假结论。

## ADDED Requirements

### Requirement: Analysis uses one point-in-time Shenwan industry scope
The system SHALL calculate this capability only from the Shenwan Level 1 taxonomy and memberships effective on the analysis date. Each ordinary A-share MUST contribute to at most one industry, and industry turnover numerators and the all-market denominator MUST use the same trading date, universe policy, and original turnover convention. Concepts, themes, or other overlapping classifications MUST NOT enter candidate ranking, concentration, or `QTS-01-05-*` metrics.

#### Scenario: A stock belongs to multiple external concepts
- **WHEN** a stock belongs to multiple external concepts but one effective Shenwan Level 1 industry on the analysis date
- **THEN** its turnover contributes once to the Shenwan industry and concept membership does not affect any chapter 05 metric

#### Scenario: Membership is duplicated or mixes taxonomy levels
- **WHEN** a stock has multiple active Shenwan assignments or an input mixes industry levels
- **THEN** the affected metric is `insufficient`, the conflict is exposed, and turnover is not double-counted

#### Scenario: Concept analysis is requested
- **WHEN** a caller requests concept- or theme-sector continuity through this capability
- **THEN** the system returns `unsupported-scope` and does not relabel Shenwan results as concept results

### Requirement: Analysis deterministically produces QTS-01-05-01 through QTS-01-05-05
The system SHALL preserve the existing rule IDs, windows, weights, and empirical thresholds and SHALL emit raw values, canonical rule inputs, scores, sample dates, formulas, and calculation version for all five rules.

`QTS-01-05-01` SHALL calculate 5-day and 20-day cumulative industry return minus the same-window `ordinary-a-share-equal-weight-v1` benchmark return, map each to its rolling percentile, and use the lower percentile as `sector.relative_strength_percentile` only when both windows are valid. `QTS-01-05-02` SHALL count the last five valid sessions in which the industry's turnover ranks in the top 20 percent of the complete same-level cross-section. For `N` valid industries, the selected count SHALL be `max(1, ceil(0.20 * N))`; industries SHALL be ordered by original turnover descending and stable industry ID ascending, and ties MUST NOT expand the selected count. `QTS-01-05-03` SHALL calculate effective members with front-adjusted `close > MA20` divided by members with a valid MA20 and map it to `sector.above_ma20_ratio_percentile`.

For `QTS-01-05-04`, an industry session with a negative close-to-close return SHALL be a disagreement event. Only events with two complete subsequent sessions SHALL be mature; an event is recovered when either later close regains at least 50 percent of the decline from the pre-event close to the event close. Recovered mature events divided by mature events over the latest 20 sessions SHALL be mapped to `sector.disagreement_recovery_percentile`. `QTS-01-05-05` SHALL order Shenwan Level 1 industries by same-date original turnover descending and stable industry ID ascending, select the first `min(5, N)` without expanding ties, divide their unique turnover by the same-universe all-market turnover, and map the result to `sector.top5_turnover_concentration_percentile`.

Except for the fixed 0-to-5-day turnover-persistence bands, percentile rules SHALL retain the documented bands `<=P20=0`, `P20-P40=25`, `P40-P60=50`, `P60-P80=75`, and `>P80=100`. Publishing this capability MUST NOT upgrade any rule from `needs-backtest` to `validated`.

#### Scenario: Five rule inputs are complete
- **WHEN** an industry has valid relative-strength windows, turnover ranks, MA20 breadth, mature disagreement events, and concentration history
- **THEN** the result contains five non-null traces and a weighted total using 25/20/20/20/15 percent weights

#### Scenario: Short-term strength exceeds medium-term strength
- **WHEN** the 5-day relative-strength percentile is above P80 and the 20-day percentile is between P40 and P60
- **THEN** the canonical relative-strength input uses the lower 20-day percentile and both window values remain visible in the trace

#### Scenario: Only one relative-strength window is valid
- **WHEN** either the 5-day or 20-day relative-strength window is incomplete
- **THEN** `sector.relative_strength_percentile` and its score are `null`, both window states remain visible, and the valid window is not used alone

#### Scenario: No mature disagreement event exists
- **WHEN** the 20-session window has no negative-return event or its events lack two subsequent complete sessions
- **THEN** the disagreement ratio, percentile, and score are `null` with a zero-denominator or event-not-matured reason rather than zero

### Requirement: Rolling history enforces 60-observation and 250-observation quality thresholds
For each rolling-percentile metric, the system SHALL report valid observations, `requiredObservations=60`, `windowDays=250`, actual date range, and gaps. The percentile sample SHALL include the current `asOf` observation and at most the preceding 249 valid observations. Percentile rank SHALL be `(count(sample < value) + 0.5 * count(sample = value)) / sampleSize`, so tied values receive the same deterministic midrank. At least 250 valid observations SHALL use the latest 250 observations with normal history quality. Sixty to 249 valid observations MAY produce a percentile but MUST be `reduced-confidence` with confidence no higher than medium. Fewer than 60 valid observations MUST produce `null` percentile and score with `insufficient` quality.

Required 5-day or 20-day raw windows MUST be complete independently. The system MUST NOT fill a window with calendar days, suspension zeroes, other-date snapshots, or current constituents.

#### Scenario: Full percentile history exists
- **WHEN** a metric has at least 250 valid observations ending on `asOf`
- **THEN** the latest 250 valid observations are used and full history quality is reported

#### Scenario: Partial percentile history exists
- **WHEN** a metric has between 60 and 249 valid observations
- **THEN** a reduced-confidence percentile may be emitted with actual observations and missing history exposed

#### Scenario: Minimum history is not met
- **WHEN** a metric has fewer than 60 valid observations
- **THEN** its percentile and rule score are `null` and current cross-sectional rank is not substituted

### Requirement: Candidate industries and stage labels use fixed deterministic precedence
The system SHALL output at most three candidates drawn only from canonical Shenwan industries with exact-date point-in-time identity and ordered by total score descending, relative-strength score descending, turnover-persistence score descending, and stable industry ID ascending. Unlinked provider observations MAY remain visible as observation evidence but MUST NOT populate `candidateIndustry`. A mainline candidate MUST have `QTS-01-05-01`, `QTS-01-05-02`, and `QTS-01-05-03` scores each at least 60. Each candidate SHALL receive exactly one stage under this precedence: `insufficient`, `high-level-crowding`, `mainline-confirmed`, `mainline-candidate`, `one-day-pulse`, then `rotation-or-ebb`.

`mainline-confirmed` SHALL require the candidate condition, total score at least 70 for at least three consecutive valid sessions, no crowding veto, and successful recovery when a mature disagreement event exists during that streak. `one-day-pulse` SHALL use an analysis-only diagnostic that ranks the as-of one-session industry excess return across the complete Shenwan Level 1 cross-section using return descending and stable industry ID ascending; it does not create a sixth `QTS-01-05-*` rule input. High concentration alone MUST NOT promote an industry to candidate or confirmed status.

#### Scenario: Core evidence is jointly sufficient
- **WHEN** relative strength, turnover persistence, and breadth scores are each at least 60 for fewer than three valid sessions
- **THEN** the stage is `mainline-candidate` and the current streak is exposed

#### Scenario: Confirmation streak is complete
- **WHEN** the candidate condition and total score of at least 70 persist for at least three valid sessions without a veto and any mature disagreement is recovered
- **THEN** the stage is `mainline-confirmed`

#### Scenario: One-day leadership lacks breadth or turnover persistence
- **WHEN** an industry's as-of one-session excess return is in the deterministic top quintile but it fails at least one core candidate score
- **THEN** it is `one-day-pulse` rather than a mainline candidate

### Requirement: High concentration with low breadth triggers a crowding veto
When top-five turnover concentration exceeds its P80 and a candidate industry's breadth is below its P40, the system SHALL set that candidate's crowding risk, retain the concentration trace, record the documented veto reason, and assign `high-level-crowding` before considering mainline confirmation. The market-level canonical `risk.sector_crowding_without_breadth` value SHALL reflect only the first deterministically ranked candidate; if no first candidate exists it SHALL be `null`. Missing concentration or candidate breadth SHALL leave an explicit unresolved crowding-risk warning and SHALL prevent high confidence.

#### Scenario: Concentration is high and breadth is low
- **WHEN** top-five concentration is above P80 and the first candidate's breadth is below P40
- **THEN** the crowding veto applies and the candidate cannot be `mainline-confirmed` even if its total score is at least 70

#### Scenario: Concentration is high with adequate breadth
- **WHEN** concentration is above P80 but candidate breadth is at or above P40
- **THEN** the crowding veto does not apply and both values are shown as evidence

#### Scenario: A veto input is missing
- **WHEN** concentration or candidate breadth cannot be calculated
- **THEN** crowding risk remains unresolved and confidence cannot be high

### Requirement: Internal structure exposes facts without assigning unverified roles
For each candidate, the system SHALL expose exact-date facts that can be proven from market data and point-in-time membership, including effective member count, advancing/declining/flat counts, limit-up and limit-down counts when available, top securities by turnover and return, single-security turnover contribution, and diffusion ratios. It MUST NOT automatically assign `leader`, `middle army`, `catch-up`, or equivalent roles without a separately versioned rule and evidence contract.

#### Scenario: One stock dominates industry turnover
- **WHEN** one stock contributes most of a candidate industry's turnover
- **THEN** its rank and contribution are displayed without automatically labeling it as a leader or middle army

#### Scenario: Multiple stocks participate
- **WHEN** multiple members rise, trade actively, and stand above MA20
- **THEN** the participation facts and diffusion ratios are displayed without inventing a catch-up hierarchy

### Requirement: Analysis emits exactly one next-session validation item
The system SHALL emit exactly one structured validation record. When a deterministically ranked canonical candidate exists, the record SHALL contain that first candidate's industry, stage, persistence evidence, breadth evidence, turnover evidence, internal-structure facts, validation target, confirmation condition, and invalidation condition. When no canonical candidate exists, the record SHALL use `candidateIndustry=null`, stage `insufficient`, identify the critical data or identity input that must recover, and contain no directional market claim. It SHALL render the record in the documented review-card format.

Validation priority SHALL be: restore a critical missing input; test breadth recovery for a crowding veto; test whether a pending disagreement recovers at least 50 percent within two sessions; test whether all three core candidate scores remain at least 60 after the next disagreement; otherwise test whether the first ranked canonical Shenwan observation can make all three core scores reach 60. Confirmation and invalidation MUST contain explicit values, percentiles, or score thresholds, and other candidates MUST NOT emit parallel validation items.

#### Scenario: Multiple candidates exist
- **WHEN** three industries enter the candidate list
- **THEN** only the first industry under deterministic ordering receives a validation record

#### Scenario: Crowding risk has precedence
- **WHEN** the first candidate reaches the total-score threshold but triggers the crowding veto
- **THEN** the validation target is breadth recovery to at least P40 rather than further turnover concentration

#### Scenario: Critical history or membership is missing
- **WHEN** the first canonical industry lacks point-in-time membership, MA20, or turnover history
- **THEN** the single validation item concerns restoration of that input, the stage remains `insufficient`, and no directional confirmation is fabricated

#### Scenario: No canonical candidate can be formed
- **WHEN** industry facts are absent, all identities conflict, or no provider observation maps to an exact-date canonical Shenwan identity
- **THEN** exactly one `insufficient` validation record is emitted with `candidateIndustry=null` and a critical-input recovery target

### Requirement: Chapter 05 presentation preserves observation and analysis boundaries
The dashboard SHALL present the five rule traces, history quality, candidate stages, crowding risk, internal-structure facts, and the single next-session validation record when analysis is available. It SHALL retain the existing exact-date provider ranking table and its quality warnings as a separately labeled observation section. It MUST NOT derive a missing analysis metric or candidate from an unlinked ranking row.

The fixed review-card rendering SHALL remain copyable in the documented format. All visible text, chart labels, table labels, tooltips, and control labels SHALL be at least 14 pixels. At a 390-pixel viewport, the page MUST NOT have page-level horizontal overflow, overlap, or truncation; a wide table MAY scroll within its own container.

#### Scenario: Analysis and provider ranking are both available
- **WHEN** the selected exact date has a compatible continuity result and a provider ranking observation
- **THEN** the page displays the analysis evidence and unique validation separately from the current observation table and its lineage

#### Scenario: Only a provider ranking is available
- **WHEN** the selected exact date has ranking rows but no compatible continuity analysis
- **THEN** the page keeps the observation table, displays the analysis gaps as `insufficient`, and does not fabricate the five metrics or a canonical candidate

#### Scenario: Chapter 05 is viewed on a narrow screen
- **WHEN** the page is rendered at 390 pixels wide
- **THEN** all analysis and observation content remains readable without page-level horizontal overflow or text smaller than 14 pixels

### Requirement: Missing and invalid inputs remain null with auditable degradation
For every metric, the system SHALL emit quality state, missing reason, and affected rule. Zero denominators, unknown membership, insufficient history, date mismatch, unknown adjustment state, or provider failure MUST produce `null` value and score rather than zero, another date's data, current membership, a limit-up list, or unverified narrative.

Overall effective metric coverage of at least 90 percent is required for high confidence; 70–89 percent limits confidence to medium, 50–69 percent limits it to low, and below 50 percent MUST be `insufficient`. Reweighted totals MUST preserve original missing rules and both original and normalized weights. Missing risk inputs MUST remain warnings rather than being treated as safe.

#### Scenario: Breadth denominator is zero
- **WHEN** no member has a valid MA20 on the analysis date
- **THEN** breadth ratio, percentile, and score are `null` with `zero-denominator` rather than displayed as zero percent

#### Scenario: Four of five metrics are valid
- **WHEN** one rule is unavailable and four are valid
- **THEN** the result preserves four traces, records the missing rule, limits confidence by coverage, and exposes weight normalization

#### Scenario: Only another date has a successful result
- **WHEN** the requested date lacks industry facts but another date has a successful analysis
- **THEN** the requested result is `insufficient` and the older result is not used to fill current metrics or validation text

### Requirement: Output retains rule, data, and calculation evidence
Every result SHALL include `asOf`, taxonomy level and version, membership data version, market-data version, adjustment version, calculation version, rule version, five rule traces, history coverage, candidate ordering, stage, vetoes, internal-structure facts, one validation record, confidence, coverage, and missing inputs. Identical exact-date facts and versions MUST produce identical metrics, ordering, stage, vetoes, validation text, and canonical result.

#### Scenario: Equivalent evidence is replayed
- **WHEN** identical exact-date facts, taxonomy, rule, and calculation versions are analyzed more than once
- **THEN** the metrics, ordering, stages, vetoes, validation record, and normalized result are identical

#### Scenario: A calculation convention changes
- **WHEN** relative-strength aggregation or disagreement-event definition changes
- **THEN** a new calculation version is required and prior historical evidence is not silently rewritten
