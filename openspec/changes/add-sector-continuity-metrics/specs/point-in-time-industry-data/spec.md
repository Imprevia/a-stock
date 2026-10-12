## Purpose

定义申万一级行业研究所需的时点分类、成员关系、个股与基准日线、行业日聚合和历史覆盖契约，确保任一历史日期均可按明确版本、精确交易日和无前视偏差的数据重放。

## ADDED Requirements

### Requirement: Industry taxonomy is explicit, versioned, and limited to Shenwan Level 1
The system SHALL identify every supported industry by a stable industry ID, display name, taxonomy family, taxonomy level, taxonomy version, source revision, and effective interval. The initial capability MUST support only Shenwan Level 1 industries. Concept sectors, themes, provider-specific ad hoc groups, and overlapping concept memberships MUST NOT be admitted as Shenwan industry facts.

#### Scenario: Shenwan Level 1 taxonomy is loaded
- **WHEN** a taxonomy revision contains valid Shenwan Level 1 industry identities and effective intervals
- **THEN** the system exposes those identities with `taxonomyFamily=shenwan`, `taxonomyLevel=1`, the exact taxonomy version, source revision, and effective dates

#### Scenario: Concept-sector data is supplied
- **WHEN** an input identifies a concept, theme, or other non-Shenwan grouping as an industry member set
- **THEN** the system rejects or isolates that input outside this capability and does not include it in industry returns, turnover, breadth, concentration, or market-total calculations

#### Scenario: Taxonomy identity changes across revisions
- **WHEN** an industry is renamed, split, merged, added, or retired in a later taxonomy revision
- **THEN** the system preserves the earlier version and effective interval and does not rewrite the historical industry identity in place

### Requirement: Industry membership is resolved point in time
Each stock-to-industry membership SHALL identify the canonical security, Shenwan industry ID, taxonomy version, inclusive `validFrom`, exclusive `validTo` or an explicit open end, source revision, and evidence checksum. For a requested trading date, the system MUST select only the membership whose effective interval contains that date and MUST NOT substitute the security's current membership for a historical date.

#### Scenario: A stock changes industry
- **WHEN** a security belongs to industry A before an effective change date and industry B from that date onward
- **THEN** a calculation before the change uses industry A and a calculation on or after the change uses industry B

#### Scenario: Historical membership is unavailable
- **WHEN** no membership interval covers a security on the requested trading date
- **THEN** the security remains unmapped for that date, the missing membership is counted in quality evidence, and the system does not infer an industry from a later mapping, name similarity, or provider ranking

#### Scenario: Membership intervals conflict
- **WHEN** one security has multiple active Shenwan Level 1 memberships for the same trading date and taxonomy version
- **THEN** the system classifies the membership as conflicting, excludes it from authoritative industry aggregation, and does not silently choose one industry

### Requirement: Stock daily facts preserve adjusted prices and raw turnover separately
For every eligible security and trading date, the system SHALL preserve front-adjusted price facts separately from original daily turnover facts. Price-based returns and moving averages MUST use a declared front-adjusted price series and adjustment revision. Turnover and turnover concentration MUST use the original same-date amount in yuan and MUST NOT be adjusted, rescaled by a price adjustment factor, or replaced with volume.

#### Scenario: A corporate action affects the price series
- **WHEN** a security has a corporate action inside the requested history window
- **THEN** price-based calculations use the versioned front-adjusted series while the original amount for every session remains unchanged

#### Scenario: Adjusted price is missing but raw amount exists
- **WHEN** a security has a valid same-date original amount but no valid front-adjusted price
- **THEN** the amount may contribute only to amount-based aggregates, the security is excluded from price- and MA20-based denominators, and the missing adjusted-price fact is reported

#### Scenario: Raw amount is missing
- **WHEN** a security has a valid front-adjusted close but its same-date original amount is absent or invalid
- **THEN** the system keeps the amount as missing, excludes it from turnover aggregates, and does not replace it with zero, volume, another date's amount, or an adjusted amount

### Requirement: TDX daily-package facts are exact-date and universe-audited
A TDX daily-package candidate SHALL be authoritative for original same-date OHLC, previous close, volume, and amount only when its requested date, package source date, and every accepted row date equal the target trading date. The candidate MUST have unique canonical security identities, pass the declared ordinary-A-share universe policy, and record package checksum, source revision, market counts, retained count, excluded count, unclassified count, and exclusion reasons.

#### Scenario: Complete exact-date TDX package is accepted
- **WHEN** the TDX package proves the requested trading date, contains unique valid rows, and passes the declared Shanghai, Shenzhen, and Beijing ordinary-A-share universe checks applicable to that date
- **THEN** the system stores its original daily facts with the exact date, package checksum, source revision, and universe-policy evidence

#### Scenario: TDX package date differs
- **WHEN** the requested date, package source date, or any accepted row date differs from the target trading date
- **THEN** the system rejects the candidate for that date and does not relabel, copy, or cache it as an exact-date success

#### Scenario: TDX universe is incomplete or ambiguous
- **WHEN** required market coverage is incomplete, canonical identities are duplicated, or the package contains unclassified identities beyond the declared policy
- **THEN** the system marks the daily input `insufficient` or failed, retains the audited counts and reasons, and does not publish a complete industry aggregate for that date

### Requirement: Benchmark facts use the same exact trading sessions
Every relative-strength series SHALL use the versioned benchmark identity `ordinary-a-share-equal-weight-v1`, calculated as the arithmetic mean of valid front-adjusted close-to-close returns for the same exact-date ordinary-A-share universe used by the industry aggregates. Every industry return SHALL be the arithmetic mean of valid front-adjusted close-to-close returns for that industry's effective members. Both series SHALL retain eligible and excluded counts, source revisions, adjustment revisions, universe version, and exact trading dates. An industry return and its benchmark return MUST cover the same ordered trading sessions and MUST end on the requested `asOf` date; callers MUST NOT select an alternative benchmark ad hoc.

#### Scenario: Sector and benchmark windows align
- **WHEN** a sector and its declared benchmark both contain valid facts for the same required trading sessions ending on `asOf`
- **THEN** the system may publish the relative-return input with the benchmark identity and version used

#### Scenario: Benchmark session is missing or mismatched
- **WHEN** the benchmark lacks a required trading session, ends on another date, or uses an undeclared series revision
- **THEN** the affected relative-strength input remains unavailable or `insufficient` and the system does not use another date, another benchmark, or zero return as a substitute

#### Scenario: A member return is unavailable
- **WHEN** an industry member lacks a valid front-adjusted close-to-close return for a session
- **THEN** that member is excluded from the industry-return denominator with its reason recorded, and no market-cap, turnover, zero-return, or current-date substitute is used

### Requirement: Industry daily aggregates use one same-date point-in-time universe
For each industry and trading date, the system SHALL aggregate only securities that simultaneously have a valid same-date stock fact, an effective Shenwan Level 1 membership for that date, and eligibility under the declared ordinary-A-share universe policy. The aggregate MUST expose the taxonomy version, membership revision, universe-policy version, price-adjustment revision, calculation version, total member count, eligible counts by metric, excluded counts and reasons, industry return, original turnover, and breadth inputs.

The all-market turnover denominator used by industry concentration MUST use the same trading date and ordinary-A-share universe policy. Each security amount MUST contribute at most once to the mutually exclusive Shenwan Level 1 aggregation.

#### Scenario: Same-date industry aggregate is produced
- **WHEN** stock facts, memberships, taxonomy, and universe evidence are valid for the requested date
- **THEN** the system publishes a reproducible industry aggregate whose counts, amounts, versions, and checksum reconcile to those exact-date inputs

#### Scenario: Benchmark is unavailable while other facts are valid
- **WHEN** same-date membership, amount, and adjusted-price facts are available but the benchmark series cannot prove a required session
- **THEN** turnover, breadth, concentration, and internal-structure facts remain eligible while only relative-strength outputs are `insufficient`

#### Scenario: One security has conflicting active industry assignments
- **WHEN** a security would contribute to more than one Shenwan Level 1 industry on the same date
- **THEN** its amount is not double-counted, the conflict is recorded, and affected aggregate quality is downgraded

#### Scenario: Market denominator uses different coverage
- **WHEN** the proposed all-market amount uses another date or a different universe policy from the industry numerators
- **THEN** the concentration input is rejected as incompatible and remains `insufficient`

### Requirement: Historical backfill is bounded, resumable, and quality-aware
A historical backfill request SHALL declare an `asOf` trading date and an explicit finite trading-session range or count. The initial warm-up default MUST be the 272 trading sessions ending on `asOf`, while operators MAY request smaller repair ranges or larger research ranges explicitly. The system SHALL resolve every range from the authoritative trading calendar, report every requested, completed, missing, skipped, and failed date, and preserve exact-date gaps without adjacent-date substitution.

Repeating the same request MUST retain verified identical facts and resume unresolved dates without duplicate authoritative records. Full 250-observation calibration readiness SHALL require enough complete history for the metric window and at least 250 valid observations; 60 to 249 valid observations MAY support reduced-confidence percentiles, while fewer than 60 MUST remain `insufficient`.

#### Scenario: Default historical backfill completes
- **WHEN** an operator requests the default backfill ending on a valid `asOf` date
- **THEN** the system targets 272 ordered trading sessions, records per-date outcomes, and reports the exact valid-observation count available to every derived metric

#### Scenario: A bounded repair range is requested
- **WHEN** an operator requests one or more explicitly bounded unresolved trading sessions
- **THEN** the system processes only that calendar-resolved repair range and does not require the request itself to contain 270 or more sessions

#### Scenario: Sixty to 249 valid observations are available
- **WHEN** a metric has at least 60 but fewer than 250 valid observations after its required warm-up window
- **THEN** the history is marked partial, the metric may produce a reduced-confidence percentile, and the missing observations remain explicit

#### Scenario: Fewer than 60 valid observations are available
- **WHEN** a metric has fewer than 60 valid observations
- **THEN** that metric's rolling percentile remains unavailable and `insufficient`, even if other metrics have sufficient history

#### Scenario: Interrupted backfill is resumed
- **WHEN** a prior backfill stopped after committing a subset of exact-date facts and the same bounded request is retried
- **THEN** the system verifies and retains matching completed dates, retries unresolved dates, and reports the resumed outcome without duplicating facts

#### Scenario: Existing date has different evidence
- **WHEN** a backfill encounters an already stored date whose checksum or source revision differs from the incoming evidence
- **THEN** the system preserves an auditable revision conflict and does not silently overwrite the earlier authoritative version

### Requirement: Data quality and lineage are complete and fail closed
Every taxonomy, membership, stock fact, benchmark fact, and industry aggregate SHALL expose its requested date or effective interval, proven actual date, source, source revision, schema version, applicable domain versions, observation counts, field availability, checksum, fetch or import time, quality status, and warnings. Critical date, identity, membership, price, amount, benchmark, or version gaps MUST produce `degraded`, `insufficient`, `missing`, or failed quality rather than `ok`.

#### Scenario: Complete lineage is inspected
- **WHEN** an operator or downstream evaluator reads an industry aggregate
- **THEN** it can identify the exact taxonomy, membership, universe, price-adjustment, benchmark, source, and calculation versions and verify their dates and checksums without reading provider-specific payloads

#### Scenario: Critical lineage is missing
- **WHEN** an input lacks a provable actual date, source revision, required domain version, or evidence checksum
- **THEN** the system does not mark the input or dependent aggregate `ok` and lists the missing lineage in structured quality evidence

#### Scenario: Numeric fact is absent
- **WHEN** a required numeric field is null, non-finite, or otherwise invalid
- **THEN** the system preserves it as missing, updates eligible and excluded counts, and does not coerce it to zero

### Requirement: New industry input sources are capability-gated and fail closed
The system SHALL perform external or imported Shenwan taxonomy, point-in-time membership, adjusted-price, TDX original-fact, and benchmark acquisition only under a separately approved capability report for the exact dataset, source, and revision. A report SHALL prove date semantics, field meaning, market and historical coverage, identity rules, pagination and duplicate handling, permission and rate-limit outcomes, evidence checksum, and reviewed data-use rights. A disabled, absent, stale, conflicting, `unverified`, or `ineligible` report MUST cause zero provider I/O and zero authoritative fact writes.

Real capability probes MUST require explicit operator authorization, run in an isolated after-hours path, redact credentials and sensitive payloads, and write only probe evidence. They MUST NOT publish a formal market snapshot, industry fact, aggregate, or continuity result. Pull-request and CI validation SHALL use fixed offline fixtures.

#### Scenario: Capability report is not approved
- **WHEN** a source switch is disabled or its dataset/source/revision report is absent, stale, conflicting, `unverified`, or `ineligible`
- **THEN** the system performs no source request or authoritative write and reports the affected input as unavailable

#### Scenario: An isolated real probe succeeds
- **WHEN** an authorized after-hours probe proves the declared contract
- **THEN** it emits a redacted capability report for review without writing production facts or automatically enabling the source

#### Scenario: A source proves only partial market coverage
- **WHEN** an adjusted-price source proves Shanghai and Shenzhen history but not Beijing coverage
- **THEN** only the proven market/date scope is eligible, the full-A coverage gap remains explicit, and dependent price metrics are degraded or `insufficient`

### Requirement: Historical materialization prevents look-ahead and is deterministic
A materialization for `asOf=D` MUST use no market price, turnover, benchmark fact, taxonomy interval, or membership interval effective after D. It MUST resolve every input from explicitly recorded versions and SHALL produce the same normalized facts, aggregates, quality state, and checksums when replayed with the same inputs and calculation version.

#### Scenario: Later membership exists
- **WHEN** a replay for date D can access both the membership effective on D and a later membership revision effective after D
- **THEN** only the membership effective on D participates in the replay

#### Scenario: Future market fact is present
- **WHEN** the local store also contains stock, industry, or benchmark facts dated after D
- **THEN** those future facts do not affect the aggregate, coverage, rolling window, or quality result for D

#### Scenario: Fixed evidence is replayed
- **WHEN** the same exact-date inputs, taxonomy and membership revisions, benchmark version, universe policy, adjustment revision, and calculation version are replayed
- **THEN** the system produces identical normalized outputs and evidence checksums
