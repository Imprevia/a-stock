# Next Session Comparison Specification

## ADDED Requirements

### Requirement: Exact next real trading session
The service SHALL expose a read-only `GET /api/market-environment/next-session?as_of=YYYY-MM-DD` endpoint. It SHALL select the smallest trading session strictly greater than `as_of` from local `trading_sessions`, read only exact-date core index and materialized market breadth aggregates, and never use natural-day arithmetic, another date, or an external provider.

#### Scenario: Next session is available
- **WHEN** a strict next trading session and complete current/next aggregates exist
- **THEN** the response has `status=available`, consistent current/next dates, seven evidence values for both dates, and numeric deltas where computable

#### Scenario: Next session is not yet materialized
- **WHEN** the strict next session exists but its required snapshot or aggregate is missing
- **THEN** the response has `status=pending` or `status=insufficient`, names the missing data in warnings, and performs zero provider calls

#### Scenario: No strict next session exists
- **WHEN** no local trading session is strictly greater than `as_of`
- **THEN** the response has `status=insufficient`, `nextAsOf=null`, and a warning explaining that no next real session is available

### Requirement: Auditable deltas
The response SHALL preserve `requestedAsOf`, `currentAsOf`, `nextAsOf`, current and next evidence, and per-item deltas including direction, advance ratio, median return, MA20 counts, turnover ratio, and volume-backed direction counts. Missing values remain null with quality status and warning.

#### Scenario: Missing metric remains explicit
- **WHEN** one date lacks a turnover ratio while other evidence is present
- **THEN** the corresponding delta is `null`, the date-level evidence keeps its insufficient status, and the response warning identifies the missing metric.
