## ADDED Requirements

### Requirement: Sector collection uses a fixed independent-provider fallback order
The system SHALL attempt sector sources in the order Eastmoney `push2`, Eastmoney
`push2delay`, approved Tushare THS, and approved Fuyao THS. A disabled or unsatisfied
capability gate MUST cause zero I/O for that provider and MUST NOT prevent the next eligible
fallback from running. Ordered attempt evidence and warnings SHALL identify gated, attempted,
and failed sources without exposing credentials.

#### Scenario: Eastmoney delayed source succeeds
- **WHEN** the primary Eastmoney source fails and the delayed source returns a valid candidate
- **THEN** neither Tushare nor Fuyao is called and the delayed candidate remains authoritative

#### Scenario: Approved Tushare succeeds after both Eastmoney sources fail
- **WHEN** both Eastmoney sources fail, Tushare is enabled, its matching report is `eligible`, and Tushare returns valid exact-date rows
- **THEN** the collection returns the Tushare candidate with ordered Eastmoney failures, Tushare source/revision, field availability, and fallback quality, and does not call Fuyao

#### Scenario: Tushare is gated or invalid and Fuyao succeeds
- **WHEN** both Eastmoney sources fail and Tushare is disabled, unapproved, or returns an invalid candidate while Fuyao satisfies its existing gate
- **THEN** no unauthorized Tushare request is emitted, or the classified Tushare failure is retained, and collection continues to Fuyao with preceding warnings

### Requirement: Tushare THS sectors prove the requested exact date
The system SHALL call the official Tushare Pro `ths_index`, `ths_daily`, and
`moneyflow_ind_ths` APIs, join responses by unique documented industry identity, and require
every date-bearing row used by the candidate to contain a `trade_date` equal to the requested
Shanghai trading date. A catalog response without a date MUST NOT prove the candidate date.
Missing pages, duplicate identities, orphan daily rows, malformed dates, mixed dates, or
permission-denied required APIs MUST reject the Tushare candidate and allow the next fallback.

#### Scenario: Complete exact-date responses are returned
- **WHEN** the catalog has unique identities, daily rows and any used flow rows have the requested `trade_date`, and all required pages are present
- **THEN** rows are normalized, sorted by change percentage descending and code ascending, assigned stable ranks, and returned with matching requested and actual dates

#### Scenario: Provider returns a different or mixed date
- **WHEN** any daily or money-flow row used by the candidate has a missing, malformed, different, or mixed `trade_date`
- **THEN** the Tushare candidate is rejected as a date mismatch and no other date is relabeled as requested data

#### Scenario: Required API permission is denied
- **WHEN** Tushare denies permission for `ths_index`, `ths_daily`, or `moneyflow_ind_ths`
- **THEN** the attempt is classified as non-retryable with bounded redacted code/message evidence and collection may continue to Fuyao

### Requirement: Tushare field mappings preserve provider authority and missing values
The system SHALL map `ts_code` and `name` to sector identity and `ths_daily.pct_change` to
`changePct`. It SHALL map `moneyflow_ind_ths.net_amount` to `mainNet` in yuan only after
the official unit is verified as ten-thousand yuan, and SHALL map a non-empty official leader
name only after its field semantics are verified. `amount`, `mainNetPct`, `upCount`, and
`downCount` MUST remain `null`; volume, market value, `company_num`, stock-count fields, or
unverified flow columns MUST NOT be used as substitutes. Missing optional flow/leader rows MAY
leave their fields null with degraded field-availability warnings.

#### Scenario: Verified fields are present
- **WHEN** an industry has valid catalog identity, exact-date percentage, documented flow unit, and a validated leader name
- **THEN** the normalized row exposes code, name, change percentage, yuan-normalized main net flow, and leader without changing `SectorRow`

#### Scenario: Unsupported fields are requested downstream
- **WHEN** a Tushare candidate is materialized through the existing API
- **THEN** amount, main net percentage, advancing count, and declining count remain null with structured warnings rather than zero or an approximate value

### Requirement: Tushare sectors are fail-closed and capability-gated
The system SHALL call Tushare sectors only when
`MARKET_ENVIRONMENT_TUSHARE_SECTORS_ENABLED=1`, a stored `eligible` report exists for
provider `tushare`, dataset `sectors`, and the report revision exactly matches
`MARKET_ENVIRONMENT_TUSHARE_SECTORS_APPROVED_REVISION`. Probe evidence MUST cover all three
API permissions, exact-date rows, identity coverage, field units, pagination, and rate-limit
outcomes without the token or a raw credential-bearing request body.

#### Scenario: Tushare is disabled or unapproved
- **WHEN** the switch is disabled, the report is missing/non-eligible, or the approved revision differs
- **THEN** no Tushare request is made and the plan proceeds to the existing Fuyao gate

#### Scenario: Authorized probe lacks one API permission
- **WHEN** an isolated after-hours probe can call only a subset of the three required APIs
- **THEN** it emits a redacted `ineligible` report, writes no formal sector snapshot, and cannot authorize runtime collection
