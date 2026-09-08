## MODIFIED Requirements

### Requirement: Configurable after-market schedule
The system SHALL provide a scheduled collection job that is enabled by default for the market-environment deployment, defaults to 16:30 `Asia/Shanghai` on Monday through Friday, can be disabled or suspended, and can be assigned a different post-settlement schedule through deployment configuration. `marketEnvironment.timezone` SHALL remain `Asia/Shanghai`; controller timezone changes only the trigger mapping, never the business date or settlement zone. The scheduling flags `enabled`, `suspend`, `controllerTimeZoneVerified`, and `controllerCanaryVerified` MUST be typed booleans, and string lookalikes MUST be rejected. A custom production schedule MUST be one unambiguous weekday trigger in the numeric five-field form `M H * * 1-5`, and its Shanghai `H:M` MUST be strictly later than the configured settlement boundary. Every enabled schedule SHALL use an explicit timezone strategy. A native strategy SHALL emit `spec.timeZone: Asia/Shanghai` only for a target API server that accepts that field. A controller-timezone compatibility strategy SHALL omit `spec.timeZone` and MUST require a single active controller topology, reproducible controller-runtime timezone evidence, and a cron expression proven equivalent to the configured Shanghai schedule; the TrueNAS k3s 1.26 compatibility profile is limited to the default 16:30 schedule. It MUST remain suspended until an authorized no-provider scheduling canary observes the predicted controller trigger. The deployment SHALL reject an enabled schedule when its value types, business timezone, strategy, target capability, controller evidence, settlement boundary, cron equivalence, schedule shape, or required canary result is missing or inconsistent.

#### Scenario: Boolean value is supplied as a string
- **WHEN** any scheduling boolean is supplied as `"true"`, `"false"`, or another non-boolean value
- **THEN** deployment validation rejects the final merged values before environment loading, network access, image work, or target API access

#### Scenario: Business timezone is changed
- **WHEN** `marketEnvironment.timezone` is not exactly `Asia/Shanghai`, whether scheduled collection is enabled or disabled
- **THEN** deployment validation rejects the configuration before rendering or target access

#### Scenario: Default weekday run
- **WHEN** the selected native strategy is rendered for a target API server that accepts CronJob `spec.timeZone`
- **THEN** the CronJob contains `spec.timeZone: Asia/Shanghai` and schedules one collection Job at 16:30 Shanghai time on Monday through Friday

#### Scenario: Native schedule is customized
- **WHEN** an operator configures a native-strategy weekday schedule later than the Shanghai settlement boundary on a target API server that accepts CronJob `spec.timeZone`
- **THEN** the CronJob retains `spec.timeZone: Asia/Shanghai` and triggers at the configured Shanghai time

#### Scenario: Native schedule is not after settlement
- **WHEN** a custom native schedule is earlier than or equal to the configured Shanghai settlement boundary
- **THEN** deployment validation rejects the schedule before cluster submission

#### Scenario: Native schedule contains multiple trigger times
- **WHEN** a custom native schedule uses lists, ranges, steps, or another expression outside the single numeric `M H * * 1-5` form
- **THEN** deployment validation rejects the ambiguous production schedule before cluster submission

#### Scenario: Verified Kubernetes 1.26 controller-timezone schedule
- **WHEN** an operator selects controller-timezone compatibility for single-controller k3s 1.26, records verified controller-runtime timezone evidence, supplies a cron expression equivalent to 16:30 `Asia/Shanghai`, and observes the predicted trigger with an authorized no-provider canary
- **THEN** the rendered CronJob omits `spec.timeZone` and schedules one collection Job at the equivalent Shanghai time on Monday through Friday

#### Scenario: Controller trigger canary is not proven
- **WHEN** controller-timezone compatibility is configured but a no-provider canary has not produced a Job at the predicted controller time
- **THEN** the production scheduled-collection CronJob remains absent or suspended and no provider-backed validation Job is started

#### Scenario: Controller timezone is unverified
- **WHEN** scheduled collection is enabled in controller-timezone compatibility mode without verified controller-timezone evidence
- **THEN** deployment validation fails before any CronJob is submitted to the target cluster

#### Scenario: Schedule is not timezone-equivalent
- **WHEN** the configured controller-timezone cron expression is not proven equivalent to the configured Shanghai collection time
- **THEN** deployment validation fails rather than silently accepting a shifted trigger time

#### Scenario: Native timezone field is rejected by the target
- **WHEN** target API server validation rejects `spec.timeZone` for a native-strategy CronJob
- **THEN** scheduled collection remains disabled or suspended and the deployment does not fall back automatically to controller local time

#### Scenario: Scheduled collection is disabled
- **WHEN** an operator disables scheduled collection in Helm configuration
- **THEN** the rendered deployment contains no scheduled-collection CronJob while the Dashboard and manual CLI remain available

#### Scenario: Scheduled collection is suspended
- **WHEN** an operator sets the scheduled-collection CronJob to suspended
- **THEN** Kubernetes retains the CronJob definition but does not create new scheduled Jobs

## ADDED Requirements

### Requirement: Staged production activation
The production scheduled collection SHALL be activated in stages: remediated implementation at a new clean HEAD with independent GO, accepted offline Stage 3 evidence, read-only target preflight under the already recorded permission, a frozen exact packet, Gate B action authorization covering that packet, a non-persistent admission probe of only the suspended CronJob in the target namespace, a no-provider scheduling canary, a non-overwriting consistent SQLite backup, suspended application CronJob creation using the frozen image, one explicitly named provider-backed Job cloned from that CronJob, Gate B evidence acceptance, and final Gate C operation authorization with an explicit catch-up choice and a fresh live suspend-only diff. Passing or pre-authorizing an earlier stage MUST NOT satisfy a later production prerequisite, and a boolean deployment switch MUST NOT serve as authorization evidence.

#### Scenario: Planning artifacts are approved
- **WHEN** a user approves the OpenSpec planning artifacts
- **THEN** implementation may begin but no production resource or data may be changed under that approval

#### Scenario: Target preflight is incomplete
- **WHEN** the final clean HEAD/remote tracking, actual release and namespace, reliably parsed target version, current release values, controller timezone, immutable image, PVC identity/capacity/free space, security context, snapshot ownership, or rollback baseline has not been captured and validated without a write-class API request
- **THEN** the CronJob remains absent or suspended and no provider-backed validation Job is started

#### Scenario: Controller scheduling canary is authorized
- **WHEN** controller-timezone mode has passed the read-only preflight, the actual-version packet is frozen and reviewed, and Gate B action authorization explicitly covers its no-provider canary
- **THEN** a bounded temporary CronJob with no provider command, service-account token, or PVC produces exactly one observed Job at the predicted controller time before it is suspended and removed after evidence capture

#### Scenario: Suspended CronJob passes server validation
- **WHEN** offline checks pass and the target API server accepts exactly one `batch/v1` CronJob with `suspend: true`, the expected release-derived name, the target namespace, and the pre-recorded create or patch verb with `dryRun=All`
- **THEN** a release covered by the exact Gate B action authorization may create the CronJob with `suspend: true` from an immutable local packet snapshot, provided Helm-recorded and API-server live resources match the expected pre-release state

#### Scenario: Admission probe contains unreviewed scope
- **WHEN** a server-side dry-run input contains an active or disabled overlay, another kind, another namespace, more than one document, or values that differ from the frozen packet
- **THEN** the deployment entry point rejects it before invoking the target API

#### Scenario: Backup evidence is incomplete
- **WHEN** a non-overwriting SQLite backup, source PVC identity, capacity threshold, SHA-256, recovery-copy `PRAGMA quick_check`, or provider-free read evidence is missing
- **THEN** the suspended application release and provider-backed validation Job remain blocked

#### Scenario: One-time Job validates the runtime boundary
- **WHEN** an operator receives Gate B action authorization naming exactly one Job to clone from the suspended CronJob
- **THEN** the Job uses the Dashboard's reviewed immutable image and PVC, preserves the container security boundary, emits structured task results, releases collection leases, leaves SQLite integrity valid, and exposes exact-date results through provider-free Dashboard reads

#### Scenario: One-time Job returns partial
- **WHEN** the validation Job returns `partial` but storage, security, date, lease, and provider-call boundaries remain valid
- **THEN** successful sibling datasets remain stored, failed datasets are reported without an automatic full-batch retry, and recurring activation requires an explicit review of the partial result

#### Scenario: Recurring schedule is authorized
- **WHEN** the one-time Job evidence is accepted, any partial is explicitly disposed, final Gate C operation authorization explicitly selects `next-schedule` or `immediate catch-up`, the API-server live suspended release matches the frozen Gate B packet, and a fresh diff changes only `/spec/suspend: true -> false`
- **THEN** the operator may apply that exact suspend-only change and verify that the next authorized controller trigger corresponds to 16:30 `Asia/Shanghai`

### Requirement: Non-destructive scheduled-collection rollback
The production rollback path SHALL stop new scheduled work by suspending or disabling the CronJob, SHALL provide a bounded exact-Job termination procedure for hard-boundary failures, and SHALL preserve the Dashboard Deployment, Service exposure, manual-collection setting, PVC, snapshots, collection audit records, and previously successful data.

#### Scenario: Scheduled collection breaches an operational threshold
- **WHEN** the scheduled workload produces unexpected restarts, provider pressure, SQLite lock or integrity errors, lease loss, date mismatch, or unacceptable PVC growth
- **THEN** the operator suspends or disables scheduled collection before further scheduled Jobs start and preserves the existing data volume for diagnosis

#### Scenario: Scheduled collection is rolled back
- **WHEN** the operator applies the reviewed rollback configuration
- **THEN** no new CronJob work is created, the Dashboard continues reading prior local data, and the release is not uninstalled and its PVC is not deleted or replaced

#### Scenario: Active Job crosses a hard stop boundary
- **WHEN** a uniquely identified active scheduled Job has a wrong trigger date or time, violates the security or storage boundary, loses its lease, or threatens SQLite integrity
- **THEN** the operator first suspends future scheduling, terminates only that exact Job under the approved incident procedure, and verifies Pod termination, lease release or expiry, and SQLite integrity without deleting the PVC
