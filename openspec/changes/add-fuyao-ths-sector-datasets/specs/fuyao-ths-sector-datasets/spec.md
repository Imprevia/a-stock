## Purpose

定义 Fuyao THS 行业、概念、区域和特色指数的版本化目录、完整当日排名、板块量价日线、可恢复历史回填、当日内部宽度和本地查询契约，使 provider observation 可审计且不混入申万一级 canonical analysis。

## ADDED Requirements

### Requirement: THS catalog covers four versioned classifications
The system SHALL maintain versioned catalog relations for exactly `industry`, `cn_concept`, `region`, and `tszs`. Every catalog revision SHALL preserve tag, THS code, display name, provider timestamp, fetched timestamp, row count, canonical checksum, and capability revision. A THS code MAY belong to more than one classification; its market facts MUST be shared by code while every classification relation remains queryable.

#### Scenario: Four complete catalogs are imported
- **WHEN** every supported tag returns unique code/name rows with valid lineage
- **THEN** the system stores four classification relations under one revision and exposes their independent counts and checksums

#### Scenario: One code appears in two classifications
- **WHEN** the same THS code is present under two tags
- **THEN** one code identity is reused for market facts and both tag relations remain present without duplicate daily bars

#### Scenario: A catalog contains conflicting identities
- **WHEN** one tag repeats a code with conflicting names or two rows collide on the same classification key
- **THEN** that catalog revision is rejected or marked `insufficient` and is not published as complete

### Requirement: Industry ranking requires exact-date complete snapshots
The `industry-ranking` dataset SHALL fetch all four catalog revisions and the matching batched THS index snapshot, require 100% unique-code coverage, validate the Shanghai trading session and every provider timestamp, and rank each classification by `changePct` descending then `thscode` ascending. Missing fields, duplicate rows, mixed dates, or incomplete batches MUST NOT produce an `ok` ranking.

#### Scenario: Complete same-day snapshot is ranked
- **WHEN** every unique catalog code has one same-day snapshot row with the required ranking and market fields
- **THEN** all rows are persisted and each tag receives a deterministic complete ranking

#### Scenario: Snapshot coverage is incomplete
- **WHEN** any catalog code lacks a snapshot row or any snapshot row cannot be reconciled to the revision
- **THEN** the affected ranking is `insufficient`, its missing codes are reported, and no Top-N subset is presented as complete

#### Scenario: Snapshot timestamps disagree
- **WHEN** one batch maps to another Shanghai date or lacks a provable provider timestamp
- **THEN** publication is rejected and no row is relabeled as the requested date

### Requirement: Sector turnover preserves OHLC volume and turnover
The `sector-turnover` dataset SHALL store daily `open`, `high`, `low`, `close`, `volume`, and `turnover` as distinct nullable fields for every accepted THS code and trading date, together with source, capability revision, provider/fetch timestamps, checksum, and quality. It MUST NOT discard volume, use turnover as volume, adjust turnover with price factors, or fill missing numeric fields with zero.

#### Scenario: Daily snapshot contains complete market facts
- **WHEN** a catalog code has valid same-day OHLC, volume, and turnover
- **THEN** all six values are stored under the exact code/date key and are available to the local K-line query

#### Scenario: Volume is absent but turnover is present
- **WHEN** a row proves turnover but does not prove volume
- **THEN** turnover remains available, volume remains `null`, and field-level quality reports the gap

#### Scenario: The same code belongs to multiple tags
- **WHEN** a shared code has one accepted daily row
- **THEN** the row is stored once and is reachable through every current catalog relation for that code

### Requirement: Historical K-line backfill is bounded resumable and idempotent
Historical sector backfill SHALL operate on explicit THS codes and date windows ending no more than five years before the requested end date. A run MUST accept at most 60 unique codes by default, record a run plus per-code/per-window checkpoints, enforce the declared request budget, and resume only unresolved chunks. Verified existing rows MUST be retained; a different checksum or revision MUST create an auditable conflict instead of silently overwriting them.

#### Scenario: A bounded batch completes
- **WHEN** an authorized request contains no more than 60 codes and valid windows within five years
- **THEN** every completed code/window checkpoint and inserted, skipped, failed, and conflicting row count is recorded

#### Scenario: One code fails
- **WHEN** one code's provider request fails while other codes succeed
- **THEN** successful code rows remain committed, only the failed checkpoint is retryable, and the parent run is `partial`

#### Scenario: An interrupted run resumes
- **WHEN** the same run identity is retried after some code/windows completed
- **THEN** compatible completed checkpoints are skipped and only unresolved work consumes request budget

#### Scenario: Limits are exceeded
- **WHEN** a request exceeds 60 codes, the five-year bound, or the authorized request budget
- **THEN** it is rejected before provider I/O with a structured validation error

### Requirement: Member fact imports are verified and source-aware
Fuyao full-market daily K dumps, recent-10-day incremental dumps, and adjustment-factor dumps SHALL be imported only through explicit operations that verify declared schema, file checksum, exact dates, canonical security identities, duplicate keys, and capability revision. TDX exact-date after-market facts MAY fill same-day missing original facts as a degraded source. Every mixed-source result MUST retain field-level lineage; a missing Fuyao dump, adjustment factor, member, or required field MUST yield `partial` or `insufficient` rather than an invented fact.

#### Scenario: Fuyao dump and adjustment factors are valid
- **WHEN** the three imported inputs pass schema, checksum, date, identity, and duplicate validation
- **THEN** adjusted price facts and original volume/turnover facts are stored separately with Fuyao lineage

#### Scenario: TDX fills a same-day original fact
- **WHEN** a Fuyao original fact is missing and an exact-date TDX fact is valid for the same security/session
- **THEN** the result identifies TDX for those fields, remains degraded or partial as required, and does not claim all-Fuyao lineage

#### Scenario: Adjustment evidence is missing
- **WHEN** a member lacks the adjustment factor or adjusted close history required for MA20
- **THEN** that member is excluded from the MA20 denominator with a reason and no unadjusted substitute is used

### Requirement: Sector breadth is current-day and formula-complete
The `sector-breadth` dataset SHALL calculate only for the exact current completed Shanghai trading date, selecting the stable Top 10 from each `industry-ranking` classification plus valid user-selected THS codes. For each selected code it SHALL report total/current member counts, valid up/down/flat counts, `advanceRatio = up / validDirectionCount`, `advanceDeclineSpreadRatio = (up - down) / validDirectionCount`, median member `changePct`, `ma20Breadth = closeAboveMA20 / validMA20Count`, same-day limit-up/limit-down counts, stable Top turnover and Top gain member lists, `maxMemberTurnoverContribution = max(memberTurnover) / totalMemberTurnover`, and `diffusionRate = 1 - maxMemberTurnoverContribution`. Zero denominators SHALL remain `null` with a structured reason.

#### Scenario: Top 10 and user selections overlap
- **WHEN** one user-selected code already belongs to a classification Top 10
- **THEN** it is calculated once and its selection reasons include both origins

#### Scenario: Complete same-day member facts exist
- **WHEN** current membership, adjusted price history, same-day original facts, and limits facts are valid
- **THEN** all supported formulas and stable member rankings are published with numerator, denominator, and lineage evidence

#### Scenario: MA20 history is insufficient
- **WHEN** one or more members lack 20 valid adjusted closes
- **THEN** those members are excluded from the MA20 denominator, coverage is reported, and zero or a shorter moving average is not substituted

#### Scenario: Limits facts are unavailable
- **WHEN** same-day limit membership is missing or insufficient
- **THEN** limit-up and limit-down counts remain `null` or insufficient while other independently valid breadth metrics remain available

### Requirement: Historical breadth cannot use current membership
The system MUST NOT calculate or expose a historical `sector-breadth` result from current constituent membership. Only exact-date point-in-time membership could support a future historical breadth capability, which is outside this change.

#### Scenario: Historical breadth is requested
- **WHEN** a client requests `sector-breadth` for a date other than the current completed Shanghai session
- **THEN** the request is rejected or reported unsupported and no current membership is applied to that date

### Requirement: Local catalog and K-line queries are provider-free
The system SHALL provide local PostgreSQL queries for catalogs and one-code K-lines. Catalog queries SHALL support classification, name/code search, revision, and pagination. K-line queries SHALL require one THS code, support bounded start/end dates and pagination, return only stored coverage, and expose coverage and quality without starting provider I/O.

#### Scenario: Catalog search matches code and name
- **WHEN** a client supplies a classification and a code/name search term
- **THEN** matching local relations are returned with revision and pagination metadata and zero provider calls

#### Scenario: K-line coverage is shorter than requested
- **WHEN** the local database contains only part of the requested date range
- **THEN** only stored rows are returned with explicit first/last date and gaps; the GET does not trigger backfill

### Requirement: Provider and import writes are explicit and fail closed
Catalog synchronization, daily collection, historical backfill, and member dump import SHALL require explicit POST or CLI commands and the applicable after-market, authorization, request-budget, enabled-switch, and exact capability-revision gates. Presigned URLs, API keys, raw provider payloads, and sensitive response headers MUST NOT be persisted or emitted.

#### Scenario: A capability revision is absent or mismatched
- **WHEN** an explicit write command cannot resolve an eligible report for its exact provider/dataset/revision
- **THEN** it performs zero provider I/O and zero authoritative writes

#### Scenario: A presigned download is used
- **WHEN** an authorized dump import downloads from a temporary signed URL
- **THEN** logs and persisted lineage contain only redacted source identity, checksum, schema, dates, and revision, not the URL or credentials

### Requirement: THS observation is isolated from Shenwan canonical analysis
THS `industry`, `cn_concept`, `region`, and `tszs` identities SHALL remain provider observations. Unless an independently approved exact-date unique mapping exists, they MUST NOT populate Shenwan Level 1 identities, point-in-time membership, or `QTS-01-05-*` rule inputs. Shared Chapter 01 responses SHALL expose THS observation and Shenwan `sectorAnalysis` as separate fields with independent quality and lineage.

#### Scenario: THS industry name resembles a Shenwan industry
- **WHEN** a THS row has the same or similar display name as a Shenwan Level 1 industry
- **THEN** no identity mapping or rule input is inferred from the name

#### Scenario: Both observation and analysis exist
- **WHEN** same-date THS datasets and Shenwan sector analysis are locally available
- **THEN** the response exposes both without merging their identifiers, membership, quality, or source revisions
