## ADDED Requirements

### Requirement: Fuyao core shadow mode is non-destructive and independently reversible
The system SHALL support a `core` shadow-only mode in which the existing approved provider chain remains the sole formal source while Fuyao `fuyao-market-v2` is queried only for comparison. Shadow execution MUST NOT replace or supplement formal index values, write a Fuyao result as the successful core snapshot, change the materialized aggregate's formal source, or enable Fuyao formal cutover. Enabling and disabling the mode MUST preserve the image, Secret reference, Service, PVC, database configuration, scheduling state, other dataset switches, and existing snapshots.

#### Scenario: Shadow-only collection succeeds
- **WHEN** core shadow is enabled, formal Fuyao cutover remains disabled, and a settled exact-date core collection obtains comparable formal and Fuyao results
- **THEN** the formal provider result remains authoritative, the redacted shadow comparison is recorded as observation metadata, and no Fuyao value is published as the formal snapshot

#### Scenario: Fuyao shadow fails
- **WHEN** Fuyao shadow encounters a permission, rate-limit, transport, field, history-length, identity, price-check, or date-validation failure
- **THEN** the formal provider result and same-date retention behavior remain unchanged, the shadow outcome is recorded as `degraded` or `insufficient`, and the core task does not fail solely because shadow failed

#### Scenario: Shadow mode is rolled back
- **WHEN** the operator disables core shadow after a failed rollout or unacceptable provider behavior
- **THEN** subsequent core collections issue no Fuyao shadow request and preserve all formal provider, snapshot, aggregate, Secret, PVC, Service, scheduling, and database state

### Requirement: Core shadow evidence is exact-date, bounded, and redacted
Each core shadow observation SHALL compare all five configured indices by canonical identity and SHALL record the requested date, formal and shadow revisions, comparable counts, identity gaps, OHLC, change percentage, turnover differences, tolerances, and bounded difference classifications. A trading date MUST NOT count as complete evidence unless both sides prove the same settled exact date, Fuyao supplies at least 280 valid OHLC/turnover bars for each compared index, and current-date collection has the required independent Tencent quote check. Reports MUST exclude credentials, raw provider envelopes, request headers, and unbounded row payloads.

#### Scenario: Complete exact-date observation
- **WHEN** formal and Fuyao results prove the same settled date for all five indices and each Fuyao series satisfies the history and field contract
- **THEN** the observation records five comparable identities with redacted field-level differences and the date is eligible for the continuous observation window

#### Scenario: One index lacks valid shadow evidence
- **WHEN** any Fuyao index is missing, cross-date, shorter than 280 valid bars, lacks OHLC or turnover, or fails the independent current-date quote check
- **THEN** the observation remains `insufficient` or `degraded`, identifies the affected index and reason, and does not count as a complete observation date

#### Scenario: Sensitive provider detail appears in an error
- **WHEN** an upstream error includes credential-like or request-specific sensitive text
- **THEN** stored and displayed shadow evidence contains only bounded redacted error classification and safe provider evidence

### Requirement: Formal Fuyao core cutover requires a separate continuous-evidence decision
Activating core shadow SHALL NOT approve or activate formal Fuyao core collection. A formal-cutover review MUST use at least five complete settled trading dates, preserve each day's outcome including mismatches, and separately assess date integrity, identity coverage, OHLC agreement, turnover basis, permission stability, rate limiting, and fallback behavior. Any unresolved `mismatch`, `degraded`, `insufficient`, cross-date evidence, missing index, or unexplained turnover basis SHALL keep formal cutover disabled and MUST NOT be converted automatically into an eligible production decision.

#### Scenario: Five complete dates pass the review policy
- **WHEN** at least five complete settled trading dates are available and every required field and provider-basis difference satisfies the documented review policy
- **THEN** the evidence may be presented for a separately authorized formal-cutover change without altering the current deployment automatically

#### Scenario: Observation window contains unresolved differences
- **WHEN** any date has an unresolved value mismatch, provider-basis ambiguity, degraded or insufficient result, cross-date evidence, or incomplete five-index coverage
- **THEN** formal Fuyao core collection remains disabled and the review records the blocking difference instead of treating the window as successful

#### Scenario: Shadow activation finishes before the observation window
- **WHEN** shadow-only configuration is deployed successfully but fewer than five complete settled trading dates have been observed
- **THEN** the activation may remain operational, but the change reports the observation gap and no formal-cutover approval is inferred
