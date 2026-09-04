## ADDED Requirements

### Requirement: Direction pattern and contextual assessment remain separate
The system SHALL preserve the existing five-state `syncPattern` as the observed relationship among the five indices and SHALL produce a separate `synchronizationAssessment` that evaluates whether market breadth, trend position, and turnover confirm, contradict, or cannot confirm that pattern. The assessment SHALL expose a closed status set of `confirmed`, `unconfirmed`, `contradicted`, and `insufficient`, and SHALL retain the original index-change evidence without rewriting the observed pattern.

#### Scenario: Raw pattern survives contradictory breadth
- **WHEN** at least four indices meet the synchronized-rally threshold but current market breadth is materially weak
- **THEN** `syncPattern.code` remains `synchronized_rally` and `synchronizationAssessment.status` is `contradicted`

#### Scenario: Missing confirmation does not erase the pattern
- **WHEN** the five index changes support `growth_lead` but breadth or turnover confirmation is unavailable
- **THEN** the system returns the `growth_lead` pattern and an `insufficient` assessment rather than replacing it with generic divergence

### Requirement: Synchronized rally is validated by market participation
For `synchronized_rally`, the system SHALL distinguish broad strength from index-only strength. Current breadth SHALL be positive only when the valid advance ratio is at least 55 percent and the median return is above zero. When an exact previous-trading-day breadth snapshot is available, increasing advance ratio and increasing median return SHALL be reported as improving participation; missing prior-day breadth SHALL lower confidence but SHALL NOT fabricate a comparison.

#### Scenario: Synchronized rally with improving breadth is credible
- **WHEN** the direction pattern is `synchronized_rally`, current breadth is positive, and both advance ratio and median return improve from the exact previous trading day
- **THEN** the assessment is `confirmed`, the conclusion identifies broad risk-appetite improvement, and the evidence includes both dates and both breadth deltas

#### Scenario: Synchronized rally conflicts with weak breadth
- **WHEN** the direction pattern is `synchronized_rally`, the advance ratio is at most 45 percent, and the median return is below zero
- **THEN** the assessment is `contradicted` and the conclusion states that index strength is not confirmed by most stocks

#### Scenario: Prior breadth is unavailable
- **WHEN** current breadth confirms `synchronized_rally` but no exact snapshot exists for the previous trading date
- **THEN** the assessment may remain `confirmed` with confidence no higher than `medium`, and the prior-day breadth dimension is marked `insufficient`

### Requirement: Weight shelter requires weak individual-stock participation
For `weight_shelter`, the system SHALL describe the raw direction as weight-index leadership and SHALL only conclude that individual stocks are weak or that shelter behavior is confirmed when market breadth is negative. The system MUST NOT name banks, insurers, petroleum companies, or another defending industry unless same-date sector evidence explicitly supports that claim.

#### Scenario: Weight shelter is confirmed by weak breadth
- **WHEN** the direction pattern is `weight_shelter`, the advance ratio is at most 45 percent, and the median return is below zero
- **THEN** the assessment is `confirmed` and states that weight indices are strong while most stocks are weak, without defining the whole market as broadly strong

#### Scenario: Weight leadership is not automatically shelter
- **WHEN** the direction pattern is `weight_shelter` but current breadth is positive
- **THEN** the assessment is `contradicted` or `unconfirmed`, the conclusion uses weight leadership rather than confirmed shelter, and it does not claim weak individual-stock participation

#### Scenario: Sector cause remains unverified
- **WHEN** weight shelter is confirmed but same-date sector evidence is missing
- **THEN** the assessment may state that weight defense is possible but MUST NOT attribute it to a named industry

### Requirement: Growth leadership requires breadth and turnover confirmation
For `growth_lead`, the system SHALL interpret the pattern as relative strength in growth and mid-cap indices and SHALL require both non-negative market participation and supporting growth-group turnover before concluding that thematic opportunities are broadly supported. Growth-group turnover SHALL be confirmed when both growth-group indices have valid 5-day turnover ratios and their median ratio is at least 1.0; a median below 0.8 SHALL contradict turnover support.

#### Scenario: Growth leadership is confirmed
- **WHEN** the direction pattern is `growth_lead`, current breadth is positive, and the growth-group median 5-day turnover ratio is at least 1.0
- **THEN** the assessment is `confirmed` and states that growth and mid-cap risk appetite is stronger, while retaining the trading-system disclaimer that this is evidence rather than an investment instruction

#### Scenario: Growth leadership lacks turnover support
- **WHEN** the direction pattern is `growth_lead`, breadth is not negative, and the growth-group median 5-day turnover ratio is below 0.8
- **THEN** the assessment is `contradicted` and states that the relative strength lacks transaction support

#### Scenario: Growth leadership has mixed validation
- **WHEN** the direction pattern is `growth_lead` and breadth or turnover is available but does not meet either the confirming or contradicting boundary
- **THEN** the assessment is `unconfirmed` and lists the unresolved confirmation dimension

### Requirement: Systemic decline requires synchronized risk confirmation
For `broad_weakness`, the system SHALL distinguish a broad index pullback from a confirmed systemic decline. A systemic decline SHALL require all three confirmation dimensions: negative current breadth, at least three valid indices closing below MA20, and at least three valid indices showing volume-backed decline through the existing `volumePriceState` or equivalent documented amount-ratio condition. The existing four-of-five direction threshold SHALL remain the broad-weakness pattern, while five-of-five weakness SHALL be exposed as stronger evidence.

#### Scenario: Systemic decline is confirmed
- **WHEN** the pattern is `broad_weakness`, current breadth is negative, at least three indices close below MA20, and at least three indices show volume-backed decline
- **THEN** the assessment is `confirmed`, the conclusion identifies systemic risk-appetite deterioration, and risk-control mode is justified by each confirmation dimension

#### Scenario: Broad weakness is not yet systemic
- **WHEN** the pattern is `broad_weakness` but one or more required systemic-decline dimensions are present and do not meet their confirmation boundary
- **THEN** the assessment is `unconfirmed` or `contradicted` and the system MUST NOT label the decline systemic solely from index changes

#### Scenario: Risk input is missing
- **WHEN** the pattern is `broad_weakness` and a required systemic-decline dimension is unavailable
- **THEN** the assessment is `insufficient`, the missing dimension is named, and the risk notice is retained rather than treating the missing input as safe

### Requirement: Synchronization assessment API is auditable and additive
The API SHALL expose `summary.synchronizationAssessment` as an additive object containing the pattern code and label, assessment status, stable conclusion code, human-readable conclusion, confidence, three confirmation dimensions, evidence, and risk notices. Each dimension SHALL expose its own status and the numeric inputs used. Existing `summary.syncPattern`, `summary.synchronization`, index fields, combination matrix data, and trading-rule outputs MUST retain their meanings.

#### Scenario: Complete assessment is traceable
- **WHEN** all direction, breadth, trend, and turnover inputs are available
- **THEN** each assessment conclusion can be reproduced from the numeric dimension inputs returned in the same response

#### Scenario: Older consumers remain compatible
- **WHEN** a consumer ignores the new `synchronizationAssessment` field
- **THEN** all previously documented response fields continue to validate and behave as before

### Requirement: Previous breadth comparison is exact-date and read-only
The service SHALL derive the previous trading date from valid core index history and SHALL read breadth only from the exact snapshot for that date. Normal market-environment GET requests MUST NOT call an external provider to obtain missing prior-day breadth, and the system MUST NOT substitute an older snapshot for the required comparison date.

#### Scenario: Exact previous snapshot is used
- **WHEN** core history identifies the previous trading date and a breadth snapshot exists for that exact date
- **THEN** the assessment uses that snapshot and returns its date in the breadth evidence

#### Scenario: Older snapshot is not substituted
- **WHEN** the exact previous-trading-day breadth snapshot is absent but an older breadth snapshot exists
- **THEN** prior-day change is marked unavailable and the older snapshot is not used for improvement or deterioration claims

#### Scenario: Read path remains provider-free
- **WHEN** an assessment is requested and prior-day breadth is missing locally
- **THEN** the request completes with insufficient comparison evidence and performs no provider call

### Requirement: Dashboard presents the confirmation chain
The Section 01 dashboard SHALL display a dedicated synchronization assessment that shows the five-index direction pattern, assessment status, conclusion, confidence, and separate breadth, trend, and turnover confirmations. The display SHALL expose the contributing values and missing or contradictory dimensions without requiring the user to infer synchronization from the six-combination matrix.

#### Scenario: Confirmed weight shelter is visible
- **WHEN** the API returns confirmed weight shelter
- **THEN** the page visibly distinguishes weight-index strength from weak individual-stock breadth and shows the supporting advance ratio and median return

#### Scenario: Conflicting evidence is visible
- **WHEN** a direction pattern is contradicted by a confirmation dimension
- **THEN** the page identifies the contradicting dimension and does not render the pattern as fully confirmed strength or weakness

#### Scenario: Responsive assessment remains readable
- **WHEN** the Section 01 page is viewed at desktop width or a 390-pixel mobile viewport
- **THEN** the direction pattern, three confirmation dimensions, conclusion, and risk notice remain readable without page-level horizontal overflow or overlapping text
