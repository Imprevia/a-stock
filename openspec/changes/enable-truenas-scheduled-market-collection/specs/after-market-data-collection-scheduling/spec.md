## MODIFIED Requirements

### Requirement: Configurable after-market schedule
The system SHALL provide a scheduled collection job that is enabled by default for the market-environment deployment, defaults to 16:30 `Asia/Shanghai` on Monday through Friday, can be disabled or suspended, and can be assigned a different post-settlement schedule through deployment configuration. A custom production schedule MUST be one unambiguous weekday trigger in the numeric five-field form `M H * * 1-5`, and its Shanghai `H:M` MUST be strictly later than the configured settlement boundary. Every enabled schedule SHALL use an explicit timezone strategy. A native strategy SHALL emit `spec.timeZone: Asia/Shanghai` only for a target API server that accepts that field. A controller-timezone compatibility strategy SHALL omit `spec.timeZone` and MUST require a single active controller topology, reproducible controller-runtime timezone evidence, and a cron expression proven equivalent to the configured Shanghai schedule; the TrueNAS k3s 1.26 compatibility profile is limited to the default 16:30 schedule. It MUST remain suspended until an authorized no-provider scheduling canary observes the predicted controller trigger. The deployment SHALL reject an enabled schedule when its strategy, target capability, controller evidence, settlement boundary, cron equivalence, schedule shape, or required canary result is missing or inconsistent.

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
The production scheduled collection SHALL be activated in stages: reviewed implementation, read-only target preflight, an explicitly authorized non-persistent admission probe and no-provider scheduling canary, suspended application CronJob creation, one explicitly approved provider-backed Job cloned from that CronJob, and a separate authorization to resume the recurring schedule. Passing an earlier stage MUST NOT authorize a later production stage.

#### Scenario: Planning artifacts are approved
- **WHEN** a user approves the OpenSpec planning artifacts
- **THEN** implementation may begin but no production resource or data may be changed under that approval

#### Scenario: Target preflight is incomplete
- **WHEN** the current release values, target API capability, controller timezone, immutable image, PVC identity, security context, or rollback baseline has not been captured and validated
- **THEN** the CronJob remains absent or suspended and no provider-backed validation Job is started

#### Scenario: Controller scheduling canary is authorized
- **WHEN** controller-timezone mode has passed the read-only preflight and production validation is explicitly authorized
- **THEN** a bounded temporary CronJob with no provider command, service-account token, or PVC produces exactly one observed Job at the predicted controller time before it is suspended and removed after evidence capture

#### Scenario: Suspended CronJob passes server validation
- **WHEN** offline checks pass and the target API server accepts the selected timezone strategy through server-side validation
- **THEN** an explicitly authorized release may create the CronJob with `suspend: true` without starting a scheduled Job

#### Scenario: One-time Job validates the runtime boundary
- **WHEN** an operator receives explicit authorization to clone one Job from the suspended CronJob
- **THEN** the Job uses the Dashboard's reviewed immutable image and PVC, preserves the container security boundary, emits structured task results, releases collection leases, leaves SQLite integrity valid, and exposes exact-date results through provider-free Dashboard reads

#### Scenario: One-time Job returns partial
- **WHEN** the validation Job returns `partial` but storage, security, date, lease, and provider-call boundaries remain valid
- **THEN** successful sibling datasets remain stored, failed datasets are reported without an automatic full-batch retry, and recurring activation requires an explicit review of the partial result

#### Scenario: Recurring schedule is authorized
- **WHEN** the one-time Job evidence is accepted and a separate production authorization is recorded
- **THEN** the operator may set `suspend: false` and verify that the next controller trigger corresponds to 16:30 `Asia/Shanghai`

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
