## ADDED Requirements

### Requirement: Fuyao v2 is the capability-gated formal first source for core indices
When Fuyao core is explicitly enabled with approved revision `fuyao-market-v2` and the runtime repository contains the exact matching `eligible` capability report, the system SHALL attempt Fuyao first for each of the five configured core indices. Each Fuyao result MUST prove canonical index identity, the requested exact date, at least 280 valid daily bars, and complete OHLC and turnover values before it can become formal snapshot evidence. The system MUST keep core shadow disabled and MUST NOT issue a separate cross-provider comparison request.

#### Scenario: Fuyao supplies all five exact-date indices
- **WHEN** the gate is enabled and Fuyao returns contract-valid history for all five indices
- **THEN** the core snapshot uses Fuyao as the formal source for all five indices and retains direct-turnover evidence with revision `fuyao-market-v2`

#### Scenario: Formal gate lacks an eligible exact revision
- **WHEN** core enablement is requested but the approved revision is missing, obsolete, absent from the runtime repository, checksum-conflicting, or not `eligible`
- **THEN** activation is rejected before formal Fuyao collection and no Fuyao result is written as a successful core snapshot

#### Scenario: Shadow remains disabled during formal collection
- **WHEN** Fuyao core is enabled as the formal first source
- **THEN** the system performs only the formal Fuyao attempt and configured fallback attempts, records no shadow comparison report, and keeps the shadow switch disabled

### Requirement: Fuyao core failure falls back per index without hiding the failure
If a Fuyao result for an individual index fails permission, rate-limit, transport, identity, history-length, OHLC/turnover, price-check, or exact-date validation, the system SHALL continue that index through the existing `mootdx -> Baidu -> Sina -> Tencent -> Eastmoney` fallback chain. A failure for one index MUST NOT prevent other indices from using successful Fuyao results. Any successful fallback MUST retain a visible Fuyao failure warning and MUST NOT relabel the fallback value as Fuyao evidence.

#### Scenario: One Fuyao index fails and fallback succeeds
- **WHEN** Fuyao succeeds for four indices but one index fails contract validation and a later provider returns exact-date data
- **THEN** the four successful indices retain Fuyao as their formal source, the fifth records its actual fallback source and Fuyao failure warning, and the core task reports partial/degraded quality rather than all-Fuyao success

#### Scenario: Fuyao and every fallback fail for one index
- **WHEN** one index has no valid Fuyao or fallback result but the other indices remain usable
- **THEN** the core task preserves the usable indices, applies only same-date retention when available, and exposes the unavailable index without cross-date substitution

#### Scenario: Fuyao returns a prior-session tail
- **WHEN** Fuyao history ends on a date earlier than the selected date
- **THEN** the Fuyao result is rejected as a date mismatch and the system continues the configured fallback chain without treating the prior-session row as selected-date evidence

### Requirement: Fuyao core capability approval is self-contained and does not require cross-provider comparison
A promotable Fuyao core capability report SHALL be redacted, checksum-valid, use provider `fuyao`, dataset `core`, and revision `fuyao-market-v2`, and prove the documented historical endpoint, all five canonical indices, complete OHLC/turnover coverage, exact requested-date tails, at least 280 valid bars per index, configured permission, and a positive bounded request budget. The report MUST NOT require or contain a shadow match, another provider's values, or a multi-day cross-provider comparison.

#### Scenario: Self-contained core report is eligible
- **WHEN** a reviewed report proves every Fuyao core endpoint, identity, field, date, history, permission, and request-budget condition without comparison evidence
- **THEN** capability promotion may accept the report for the exact provider/dataset/revision after normal redaction and checksum validation

#### Scenario: Core report omits one required fact
- **WHEN** the report lacks one index, complete turnover coverage, an exact-date tail, the 280-bar minimum, permission evidence, or bounded request-budget evidence
- **THEN** capability promotion rejects it with zero runtime capability writes and without exposing credentials or raw provider payloads

### Requirement: Formal Fuyao core activation is configuration-only and reversible
The deployment SHALL activate Fuyao core using a reviewed complete release with the same frozen image and hooks disabled. The reviewed off state SHALL declare revision `fuyao-market-v2` while keeping both formal core and shadow disabled; the enabled state SHALL differ only by changing the formal core enabled flag from disabled to enabled. The rollout and rollback MUST preserve Secret references, Services, PVCs, database settings, scheduling state, other Fuyao datasets, existing snapshots, capability reports, and task history.

#### Scenario: Formal core is enabled
- **WHEN** the exact eligible report exists and the reviewed config-only rollout is authorized
- **THEN** the same-image release enables only formal Fuyao core, keeps shadow disabled, executes no Helm hook or provider-backed deployment Job, and preserves every unrelated resource and setting

#### Scenario: Formal core is rolled back
- **WHEN** the operator disables formal Fuyao core after a rollout or collection failure
- **THEN** the same-image reviewed off release restores the existing provider chain as the first formal route without deleting the capability report, snapshots, task history, Secret, or PVC

#### Scenario: Enabled render contains unrelated drift
- **WHEN** the live-to-desired diff changes the image, shadow flag, Secret, PVC, Service, database, scheduling, another dataset, hook, or any setting other than the formal core enabled flag
- **THEN** the rollout is rejected before Helm writes or provider calls
