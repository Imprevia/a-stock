## Purpose

提供一个以精确交易日事实为基础的盘后主动进攻方向研究工作台，把板块筛选、大成交额榜、核心辨识、候选模式、基本面风险与次日验证组织成可审计而非交易指令的证据链。

## ADDED Requirements

### Requirement: Workbench reads one exact-date local evidence revision
The system SHALL expose the active-direction research workbench as a provider-free exact-date resource pinned to one materialized evidence revision, and MUST NOT collect, backfill, write data, or substitute another date while serving a read request.

#### Scenario: Exact-date workbench is available
- **WHEN** a consumer requests a known market date with a current revision
- **THEN** the system returns workbench data, quality, lineage, and links from that exact date and revision without provider I/O

#### Scenario: Workbench inputs are absent for the selected date
- **WHEN** the selected date exists but one or more required local inputs are unavailable
- **THEN** the system returns the available modules plus explicit `missing` or `insufficient` module states and does not search another date

#### Scenario: Consumer pins a stale revision
- **WHEN** a consumer requests workbench data with a revision that no longer matches the selected date
- **THEN** the system fails with the existing revision-conflict contract before reading a mixed evidence set

### Requirement: Workbench presents five research views in a fixed evidence flow
The dashboard SHALL retain route `/dashboard/06` and the existing navigation title while presenting five views in this order: direction overview, turnover map, core recognition, candidate patterns, and fundamentals with validation.

#### Scenario: User opens the page
- **WHEN** the active-direction page finishes loading
- **THEN** the page shows the five view controls and identifies the flow as direction discovery, capacity validation, core recognition, pattern observation, risk filtering, and next-session validation

#### Scenario: User selects a security from the turnover map
- **WHEN** the user selects an available Top-30 security
- **THEN** the core, candidate, and fundamentals views use the same security identity and pinned evidence revision without inferring identity from its display name

### Requirement: Direction overview separates observed sectors from qualified candidates
The direction overview SHALL report at most three direction candidates using documented `QTS-04-01-*` evidence for relative strength, turnover change, breadth, persistence, and recovery, and SHALL keep provider observations distinct from canonical sector identities.

#### Scenario: Canonical direction evidence is complete enough to compare
- **WHEN** an exact-date canonical identity and the required evidence traces are available
- **THEN** the overview shows candidate score, stage, coverage, triggered rules, vetoes, confirmation, invalidation, and lineage

#### Scenario: Only provider observation is available
- **WHEN** active-direction rows contain industry or concept labels without a unique date-effective canonical mapping
- **THEN** the page labels them as observations, does not promote them to canonical direction candidates, and identifies the mapping gap

#### Scenario: Candidate width is too concentrated
- **WHEN** a direction has high turnover concentration but insufficient breadth evidence
- **THEN** the system exposes the crowding or narrow-width veto instead of presenting the direction as broadly confirmed

### Requirement: Turnover map exposes the validated Top-30 research sample
The turnover map SHALL expose the validated Top-30 ordered sample with rank, security identity, amount, return, close position, mapped direction, source, ranking method, and row quality; history-derived values SHALL be nullable and independently quality-tagged.

#### Scenario: Top-30 and history evidence are available
- **WHEN** the selected date has a validated Top-30 sample and enough prior exact-date observations
- **THEN** each eligible row can show prior rank, new-entry state, 5-day and 20-day amount comparison, consecutive-rank evidence, price result, and sector resonance

#### Scenario: Current-day Top-30 is available without sufficient history
- **WHEN** the sample is valid but a row lacks enough prior observations
- **THEN** current rank, amount, return, close position, and source remain visible while history-derived cells display missing status rather than zero

#### Scenario: Ranking is locally derived
- **WHEN** the Top-30 sample comes from the approved TDX-derived fallback
- **THEN** the view displays `fallback-derived`, the local ranking method, source revision, industry-mapping revision and coverage, and all retained warnings

### Requirement: Core recognition reports six evidence traces without assigning roles
For a selected security, the workbench SHALL report separate traces for market position, sector leadership effect, persistence, capacity and tradability, divergence repair, and space breakout using `QTS-04-03-*` identifiers.

#### Scenario: Four or more traces are strong
- **WHEN** the documented candidate threshold is met with sufficient coverage and no veto
- **THEN** the system labels the security as a core candidate and still marks the assessment `needs-backtest`

#### Scenario: Height is present without leadership effect
- **WHEN** a security has strong height or return evidence but weak or missing sector-leadership evidence
- **THEN** the system describes an isolated high-position observation and does not label it a leader, capacity core, follower, or catch-up security

#### Scenario: Trace input is missing
- **WHEN** any six-trace input cannot be proven from local exact-date facts
- **THEN** the affected trace is `missing` or `insufficient` with its missing input listed and is not replaced by a front-end estimate

### Requirement: Candidate patterns remain observation pools rather than trade signals
The candidate view SHALL separate abnormal-capital, long-upper-shadow, and first-to-second-board observation pools and SHALL provide per-candidate evidence, classification, observation window, vetoes, confirmation, and invalidation.

#### Scenario: Abnormal-capital evidence is available
- **WHEN** at least two independent evidence groups among price and volume, structure, relative strength, and event or sector context support a security
- **THEN** the system may place it in an A or B observation class while preserving contrary evidence and liquidity exclusions

#### Scenario: Long-upper-shadow candidate is detected
- **WHEN** objective prior-high, wick, volume, price-position, and follow-up inputs are available
- **THEN** the system reports the `QTS-04-05-*` traces and the one-to-three-session confirmation window without calling the pattern accumulation, washing, or distribution as a fact

#### Scenario: First-to-second-board candidates are classified
- **WHEN** limit facts prove a first board or a limit-up anchor within five trading sessions
- **THEN** strict next-session first-to-second candidates and broader five-session strong candidates are shown as different classes with their own anchors and expiry conditions

#### Scenario: Auction or intraday facts are not locally available
- **WHEN** the selected candidate lacks auction or intraday confirmation evidence
- **THEN** those inputs appear only as next-session items to verify and cannot be treated as satisfied conditions

### Requirement: Fundamentals are an industry-relative risk and research overlay
The fundamentals view SHALL organize available local facts into profitability quality, growth stability, cash-flow quality, leverage risk, and relative valuation under `QTS-04-07-*`, and MUST NOT generate a trading signal or apply one universal threshold across industries.

#### Scenario: Comparable financial facts are available
- **WHEN** a selected security has dated financial facts, a valid industry identity, and comparable history
- **THEN** the view shows period, source, industry and historical comparisons, supporting and opposing evidence, red flags, score coverage, and unanswered questions

#### Scenario: Financial data is absent or stale
- **WHEN** current approved local financial facts or comparable peers are unavailable
- **THEN** the fundamentals module is `missing` or `insufficient`, names the unavailable facts, and does not infer safety from absence of evidence

#### Scenario: Hard financial or compliance exclusion is proven
- **WHEN** local evidence proves a delisting risk, non-standard audit opinion, major violation, missing required financial statements, or material going-concern uncertainty
- **THEN** the candidate exposes a veto independently of technical-pattern evidence

### Requirement: Every assessment exposes rule maturity and one next-session validation
The workbench SHALL expose rule ID, rule version, implementation state, calibration state, coverage, missing inputs, triggered rules, vetoes, confirmation and invalidation, and SHALL produce exactly one prioritized next-session validation item for the selected direction or security when a validation can be formulated.

#### Scenario: Documented rules have complete inputs
- **WHEN** all inputs for a `QTS-04-*` assessment are present
- **THEN** the result remains labeled `documented-only` and `needs-backtest` until the trading-rule evidence contract proves a validated calibration

#### Scenario: Critical inputs are missing
- **WHEN** coverage is below the documented minimum or a risk-veto input is unavailable
- **THEN** confidence is capped or set to `insufficient`, missing values remain null, and the validation prioritizes restoring the critical evidence

#### Scenario: No candidate can be supported
- **WHEN** no direction or security has enough exact-date evidence
- **THEN** the page returns no directional conclusion and its single validation item describes evidence recovery rather than market direction

### Requirement: Workbench remains readable and truthful across supported viewports
The dashboard SHALL render every visible label, control, legend, axis, and tooltip at no less than 14px and SHALL avoid page-level horizontal overflow, overlap, and clipping at desktop and 390px widths; wide tables MAY scroll within their own container.

#### Scenario: Desktop view renders all five views
- **WHEN** the page is rendered at a supported desktop width
- **THEN** view controls, quality states, evidence, warnings, and selected-security context remain readable and keyboard operable

#### Scenario: Mobile view renders all five views
- **WHEN** the page is rendered at 390px width with complete, partial, or missing evidence
- **THEN** controls and evidence stack without page-level horizontal overflow, overlap, clipped text, or sub-14px visible text

