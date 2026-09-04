## Purpose

Defines the dashboard capability for Section 01-01 (index, trend position, and turnover): five-state index synchronization, rule-metric exposure including 250-day rolling percentiles, the five-index combination matrix with the four-question market conclusion, post-market summary sentence generation, and layered missing-data reasons.

## ADDED Requirements

### Requirement: Five-state index synchronization classification

The system SHALL classify daily index synchronization into exactly one of five states: `synchronized_rally` (most major indices clearly advancing), `broad_weakness` (most major indices clearly declining), `weight_shelter` (the weight group — SSE Composite and CSI 300 — clearly advancing while the growth group — ChiNext and CSI 500 — is weak), `growth_lead` (the growth group clearly advancing while the weight group is weak), or `undetermined_divergence`. Classification SHALL follow a fixed precedence — synchronized states take priority over divergence-pattern states — and all numeric thresholds SHALL be recorded as empirical initial values pending backtest. When no pattern's conditions are met, the system SHALL output `undetermined_divergence` instead of guessing.

#### Scenario: Weight shelter is identified

- **WHEN** SSE Composite and CSI 300 daily change are at or above the advance threshold while ChiNext and CSI 500 daily change fall below zero
- **THEN** the synchronization state is `weight_shelter` and the evidence names each index's contribution

#### Scenario: Synchronized state takes precedence over divergence pattern

- **WHEN** at least four of five indices advance beyond the threshold on the same day
- **THEN** the synchronization state is `synchronized_rally` even if the remaining index is weak

#### Scenario: No pattern matched stays undetermined

- **WHEN** indices mix without satisfying any synchronized or divergence-pattern condition
- **THEN** the synchronization state is `undetermined_divergence` with observed values shown as evidence

### Requirement: Rule metrics computed and exposed

The system SHALL compute, per index, the MA20-slope 250-day rolling percentile and the volume-price advance-efficiency 250-day rolling percentile, and, at market level, the bullish moving-average alignment ratio across the five major indices. Index kline retrieval depth SHALL cover the 250-day calibration window (at least 280 bars) across the provider fallback chain. When fewer than 250 but at least 60 valid observations exist, the system SHALL emit the metric with reduced confidence; with fewer than 60 valid observations it SHALL emit an insufficient marker instead of a value.

#### Scenario: Full history yields percentile values

- **WHEN** an index has at least 280 bars of history from the provider
- **THEN** the MA20-slope percentile and advance-efficiency percentile are emitted for that index

#### Scenario: Short history reduces confidence

- **WHEN** an index has between 60 and 279 valid observations
- **THEN** the metrics are emitted where computable and flagged with reduced confidence

#### Scenario: Insufficient history yields no value

- **WHEN** an index has fewer than 60 valid observations
- **THEN** the metrics are emitted as insufficient and no percentile value is fabricated

### Requirement: Five-index combination matrix presentation

The Section 01 page's fourth part SHALL present a matrix of the five indices against the six defined combinations. Each matrix cell SHALL show whether that index's daily evidence matched that combination; a matched cell SHALL display the state tone with key numeric evidence. Selecting a matrix row SHALL expand that index's full match evidence including the trading-mode hint. The market-stage conclusion SHALL be derived transparently from matrix column aggregation — at least three indices matching the same combination — and the four-question conclusion strip (real strength, market stage, capital acceptance, trading mode) SHALL remain visible above the matrix with traceable evidence. Indices matching no combination SHALL be shown explicitly as unmatched without fallback classification.

#### Scenario: Majority match establishes the market stage

- **WHEN** at least three of five indices match the same combination
- **THEN** the market-stage conclusion names that combination's state and the matrix highlights the matched column

#### Scenario: Row selection expands index evidence

- **WHEN** the user selects a matrix row
- **THEN** that index's combination evidence and trading-mode hint are displayed in full

#### Scenario: No match stays explicit

- **WHEN** an index matches none of the six combinations
- **THEN** its matrix row displays an explicit unmatched state rather than a nearest-fit guess

### Requirement: Post-market summary sentence generation

The system SHALL generate a daily post-market summary sentence composed of the synchronization state, the close's position relative to MA20, the 60-day range position band, the day's turnover versus its 5-day average, whether price advanced after volume, and the resulting environment leaning. Each component the inputs support SHALL appear in the sentence; any component whose input is missing or insufficient SHALL be rendered as an explicit data-insufficient segment, and the system SHALL NOT fabricate a component value.

#### Scenario: Complete inputs produce a complete sentence

- **WHEN** all component inputs are available for the trading day
- **THEN** the generated sentence covers all six components in the source document's template order

#### Scenario: Missing component is marked in place

- **WHEN** market breadth or turnover inputs are unavailable for the day
- **THEN** the corresponding sentence segment reads as data-insufficient while the remaining segments stay intact

### Requirement: Missing-data reason layering

Whenever an index-level or market-level metric is null, the system SHALL attach one reason code from the closed set: `insufficient-history`, `missing-today`, `provider-failed`, or `not-computable`. The dashboard SHALL render distinct missing-state text per reason code. Risk-relevant inputs that are missing SHALL retain their risk notice rather than being treated as safe.

#### Scenario: Insufficient history is distinguished from provider failure

- **WHEN** one index lacks 60-day history and another index's provider request failed
- **THEN** the two null metrics carry `insufficient-history` and `provider-failed` respectively and render different missing-state text

#### Scenario: Not-computable metric keeps its warning

- **WHEN** a range position cannot be computed because the window high equals the window low
- **THEN** the metric is null with reason `not-computable` and the dashboard shows the existing degenerate-window warning
