## MODIFIED Requirements

### Requirement: Configurable after-market schedule
The system SHALL provide a scheduled collection job that is disabled and suspended by default for the market-environment deployment, targets 16:30 `Asia/Shanghai` on Monday through Friday when explicitly enabled through the staged scheduling path, can be disabled or suspended, and can be assigned a different post-settlement schedule through deployment configuration. `marketEnvironment.timezone` SHALL remain `Asia/Shanghai`; controller timezone changes only the trigger mapping, never the business date or settlement zone. The scheduling flags `enabled`, `suspend`, `controllerTimeZoneVerified`, and `controllerCanaryVerified` MUST be typed booleans, and string lookalikes MUST be rejected. A custom production schedule MUST be one unambiguous weekday trigger in the numeric five-field form `M H * * 1-5`, and its Shanghai `H:M` MUST be strictly later than the configured settlement boundary. Every enabled schedule SHALL use an explicit timezone strategy. A native strategy SHALL emit `spec.timeZone: Asia/Shanghai` only for a target API server that accepts that field. A controller-timezone compatibility strategy SHALL omit `spec.timeZone` and MUST require a single active controller topology, reproducible controller-runtime timezone evidence, and a cron expression proven equivalent to the configured Shanghai schedule; the TrueNAS k3s 1.26 compatibility profile is limited to the default 16:30 schedule. It MUST remain suspended until an authorized no-provider scheduling canary observes the predicted controller trigger. The deployment SHALL reject an enabled schedule when its value types, business timezone, strategy, target capability, controller evidence, settlement boundary, cron equivalence, schedule shape, or required canary result is missing or inconsistent.

#### Scenario: Chart defaults are rendered
- **WHEN** the Helm Chart is rendered without a reviewed scheduling overlay
- **THEN** scheduled collection is disabled and suspended and no CronJob is present

#### Scenario: Boolean value is supplied as a string
- **WHEN** any scheduling boolean is supplied as `"true"`, `"false"`, or another non-boolean value
- **THEN** deployment validation rejects the final merged values before the first Helm render, build, image work, SSH, or target API access

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
The production scheduled collection SHALL be activated in stages: remediated implementation at a new clean HEAD with independent GO, accepted offline Stage 3 evidence, read-only target preflight under the already recorded permission, a frozen exact packet, Gate B action authorization covering that packet, a non-persistent admission probe of only the suspended CronJob in the target namespace, a no-provider scheduling canary, a non-overwriting consistent SQLite backup, suspended application CronJob creation using the frozen image, one explicitly named provider-backed Job cloned from that CronJob, Gate B evidence acceptance, and final Gate C operation authorization with an explicit catch-up choice and a fresh live suspend-only diff. Generic application install, upgrade, and rollback operations SHALL use the repository's supported fail-closed deployment entry point with complete reviewed baseline values, scheduled collection explicitly disabled and suspended, and no scheduling overlay; they SHALL NOT inherit opaque release values, invoke a direct Helm write, execute raw uninstall, or restore a historical release revision that may contain an active schedule. Before build, image work, or target write, the entry point MUST freeze the generic chart/input values, derive and query the exact application CronJob name independently of mutable labels, and prove both the Helm stored manifest and API-server exact live resource are absent. It MUST bind the final disabled render and use the same read-only packet for an immediate pre-write render check and Helm write. A new release MUST have neither an existing release nor a release-derived application CronJob. Passing or pre-authorizing an earlier stage MUST NOT satisfy a later production prerequisite, and a boolean deployment switch MUST NOT serve as authorization evidence.

#### Scenario: Planning artifacts are approved
- **WHEN** a user approves the OpenSpec planning artifacts
- **THEN** implementation may begin but no production resource or data may be changed under that approval

#### Scenario: Generic application release is performed
- **WHEN** an operator installs, upgrades, or rolls back the Dashboard outside the exact Gate B or Gate C scheduling path
- **THEN** the operation uses `scripts/deploy-truenas-k3s.sh` with complete reviewed baseline values, `enabled=false`, `suspend=true`, and no scheduling overlay, does not inherit stored release values, execute raw uninstall, or restore a historical revision, and cannot create or restore an application CronJob

#### Scenario: Generic release encounters an existing application CronJob
- **WHEN** the ordinary deployment entry point discovers an active or suspended application CronJob in the Helm stored manifest or API-server live state
- **THEN** it queries the release-derived exact name independently of its mutable instance label, rejects active, suspended, or identity-drifted resources before build, image copy/import, or target write, and requires a separately reviewed and authorized `--disable-schedule` operation to remove the exact CronJob before an ordinary retry

#### Scenario: Generic release sources drift after validation
- **WHEN** the repository Chart or caller-owned values change after the ordinary deployment entry point validates and freezes its generic packet
- **THEN** the Helm write continues to read only the frozen chart and values, and an immediate pre-write render-hash mismatch rejects the operation before release mutation

#### Scenario: Generic release postcondition is uncertain
- **WHEN** the generic release write, rollout, server-observed release read, live CronJob read, or disabled/absent comparison fails
- **THEN** the entry point exits nonzero without reporting success, precisely suspends any unexpected active release-derived CronJob, verifies a final absent/suspended safety state, treats an unprovable state as uncertain/NO-GO, and requires the reviewed `--disable-schedule` workflow before another generic deployment whenever the CronJob is not proven absent

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
The production rollback path SHALL stop new scheduled work by suspending or disabling the CronJob, SHALL provide a bounded exact-Job termination procedure for hard-boundary failures, and SHALL preserve the Dashboard Deployment, Service exposure, manual-collection setting, PVC, snapshots, collection audit records, and previously successful data. A disable operation MUST require a non-empty, validated rollback-authorization reference that is independent of Gate B and Gate C references and is auditably bound to the exact command, release, namespace, Kubernetes version, reviewed HEAD, and packet hashes; a boolean switch alone MUST NOT authorize the operation. The reference MUST use a rollback-only namespace and MUST carry the SHA-256 of a versioned canonical binding over those fields, so a reference for another operation or packet cannot be replayed. From the moment an active or suspended CronJob can be changed to off until the deletion postcondition is proven, Helm failure, signal, post-write read failure, or comparison failure MUST trigger an exact-resource safety check, suspend an active or unclassifiable CronJob by exact API name, and prove the final state is absent or explicitly `spec.suspend=true`. Mutable labels and non-safety-critical packet-shape drift MUST NOT prevent emergency suspension. An unprovable safety state MUST remain uncertain/NO-GO.

#### Scenario: Scheduled collection breaches an operational threshold
- **WHEN** the scheduled workload produces unexpected restarts, provider pressure, SQLite lock or integrity errors, lease loss, date mismatch, or unacceptable PVC growth
- **THEN** the operator suspends or disables scheduled collection before further scheduled Jobs start and preserves the existing data volume for diagnosis

#### Scenario: Scheduled collection is rolled back
- **WHEN** the operator applies the reviewed rollback configuration
- **THEN** no new CronJob work is created, the Dashboard continues reading prior local data, and the release is not uninstalled and its PVC is not deleted or replaced

#### Scenario: Disable authorization is incomplete
- **WHEN** an operator supplies only a rollback boolean, omits the rollback-authorization reference, reuses a Gate B or Gate C reference, supplies unsupported reference characters, or supplies a reference whose canonical operation/release/namespace/version/packet binding differs from the current request
- **THEN** the deployment entry point rejects `--disable-schedule` before SSH, target API access, or release mutation

#### Scenario: Disable write does not complete safely
- **WHEN** an active-to-off operation fails during Helm write, receives a termination signal, or cannot complete its server-observed postcondition
- **THEN** the entry point checks the release-derived exact CronJob, patches any existing exact-name resource not proven to have typed `spec.suspend: true`, verifies absent or suspended, exits nonzero, and reports uncertain/NO-GO if that verification cannot be completed

### Requirement: Executable deployment documentation fails closed
Executable production commands in repository documentation SHALL be parsed as CommonMark shell fences and shell syntax. The gate MUST reject brace or glob executable expansion, `eval`, stdin-fed `bash`/`sh`/`dash`/`zsh`, stdin sourcing through `source` or `.`, shell command-resolution mutation through aliases or `hash -p`, dynamic Helm executable or action construction, and unknown Helm plugins or actions. Parse ambiguity in these audited paths MUST be treated as a violation rather than skipped.

#### Scenario: Shell input is reinterpreted
- **WHEN** a documented command pipes or sources stdin into a shell, mutates command resolution, or uses brace/glob/`eval` expansion to synthesize a Helm executable or write action
- **THEN** the documentation safety gate rejects the command even when no literal top-level `helm <write-action>` argv is present

#### Scenario: Helm action is unknown or dynamic
- **WHEN** a documented command selects a Helm executable or action dynamically, or invokes an unknown Helm plugin/action whose read-only behavior cannot be proven
- **THEN** the documentation safety gate fails closed

#### Scenario: Active Job crosses a hard stop boundary
- **WHEN** a uniquely identified active scheduled Job has a wrong trigger date or time, violates the security or storage boundary, loses its lease, or threatens SQLite integrity
- **THEN** the operator first suspends future scheduling, terminates only that exact Job under the approved incident procedure, and verifies Pod termination, lease release or expiry, and SQLite integrity without deleting the PVC
