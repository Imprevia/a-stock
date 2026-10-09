## MODIFIED Requirements

### Requirement: Fuyao sector capability is fail-closed and auditable
The system SHALL call the Fuyao sector fallback only when
`MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED=1`, a reviewed capability report has been promoted into the runtime repository with status `eligible`, and the approved revision exactly matches that report. Capability evidence MUST be redacted and include endpoints, requested date, calendar proof, catalog/snapshot counts, field coverage, permission, and rate-limit outcomes without an API key. Enabling or disabling this fallback MUST preserve snapshots, task history, provider-free reads, and the configuration of unrelated providers and scheduling.

#### Scenario: Capability gate is not satisfied
- **WHEN** the switch is disabled, the report is missing/non-eligible, or the approved revision does not match
- **THEN** no Fuyao request is made and the existing Eastmoney failure-retention path is used

#### Scenario: Capability evidence is generated
- **WHEN** an authorized probe completes in an isolated after-hours environment
- **THEN** the report contains only redacted contract evidence and can be reviewed before an approved revision is configured; it does not write a formal sector snapshot

#### Scenario: Reviewed application image is staged before promotion
- **WHEN** the promotion CLI and evidence policy are ready for production use
- **THEN** one clean reviewed immutable image is deployed with Fuyao sectors disabled, the approved revision declared, both application CronJobs absent, and enrichment, shadow, Scrapling, and unrelated Fuyao datasets disabled before any production capability write

#### Scenario: Reviewed capability is promoted before activation
- **WHEN** an operator has reviewed an eligible `fuyao-market-v2` sectors report and explicitly promotes it
- **THEN** the runtime repository contains the exact approved report without collecting sectors or changing the Fuyao switch

#### Scenario: Fuyao sectors fallback is enabled
- **WHEN** the matching eligible report exists and a controlled config-only deployment enables only the Fuyao sectors switch
- **THEN** the deployment reuses the exact staged image without building, transferring, importing, or changing an image, runs no Helm hook or provider-backed Job, preserves all non-Deployment resources, and Eastmoney remains first while Scrapling, sector enrichment, shadow, unrelated Fuyao datasets, and scheduled collection remain disabled

#### Scenario: Fuyao sectors fallback is rolled back
- **WHEN** an operator disables the Fuyao sectors switch after a failed or degraded rollout
- **THEN** the same config-only path reuses the exact staged image and changes only the sectors enabled flag; subsequent Eastmoney failures use the normal same-date retained/missing behavior while the capability report, snapshots, task history, Secrets, Jobs, and persistent volumes remain intact

## ADDED Requirements

### Requirement: Config-only rollout is packet-bound and fail-closed
The system MUST freeze and compare the live and desired release packets before a config-only
enablement or rollback. It MUST reject the operation unless the release, namespace, chart,
image repository/tag, running image identity, Secret references, PVC identities, scheduling
state, replica topology, and all environment values except
`MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED` are unchanged. The operation MUST use the normal
Helm release, disable hooks, preserve the complete release resource set, and prove both
application CronJobs absent before and after the write.

#### Scenario: Reviewed enablement changes only the sectors flag
- **WHEN** the live packet matches the reviewed sectors-off baseline and the desired packet is the reviewed sectors-enabled profile
- **THEN** the pre-write diff contains exactly `MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED: 0 -> 1`, the same frozen image is retained, and the Deployment rollout may proceed

#### Scenario: Config-only packet contains unrelated drift
- **WHEN** the diff includes an image, Secret, PVC, schedule, revision, enrichment, shadow, Scrapling, unrelated provider, topology, service, database, or other environment change
- **THEN** the operation fails before Helm writes and the live release remains unchanged

### Requirement: Current-date provider writes are settlement-gated before I/O
The system MUST reject a Fuyao real probe unless its requested date is the current effective
Shanghai trading date, the date is a weekday, and the configured settlement time has been
reached. This validation MUST occur before provider/client construction and before JSON or
SQLite output creation, and MUST have no force bypass. The first production sectors collection
MUST use the existing settlement-gated one-dataset collection path.

#### Scenario: Real probe is requested before settlement
- **WHEN** the Shanghai time is 15:09, the requested date differs from the current effective market date, or the date is a weekend
- **THEN** the probe is rejected with zero provider requests and no JSON or SQLite artifact

#### Scenario: Real probe reaches the settlement boundary
- **WHEN** the Shanghai time is at or after 15:10 on the requested current effective weekday
- **THEN** the probe may construct its clients and proceed, subject to all capability evidence gates

#### Scenario: First production collection is sectors-only
- **WHEN** the authorized post-activation collection is triggered
- **THEN** exactly the `sectors` dataset is requested through the settlement-gated collection command and no force option or schedule activation is used
