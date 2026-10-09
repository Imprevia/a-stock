## Context

See `proposal.md` for motivation. The Fuyao THS sectors adapter, exact-date validation, field-availability warnings, capability gate, PostgreSQL capability repository, and Helm environment variables already exist. The current real-probe command intentionally writes reports only to an isolated SQLite store, while the runtime gate reads PostgreSQL. Production currently has no sectors capability report, and the previously observed `fuyao-market-v1` report cannot approve the current `fuyao-market-v2` contract.

The normal unified-adapter deployment is a prerequisite and must keep scheduling, Fuyao sectors, sector enrichment, and Scrapling disabled. Probe, report promotion, Helm rollout, and the first production sectors collection are separate authorized operations.

Read-only production discovery on 2026-10-09 found that Helm revision 87 runs image
`20261008-235342-36aba3b`, which predates the promotion CLI. The runtime capability table is
present but empty. Therefore promotion cannot precede every rollout: the reviewed new image
must first be staged with sectors disabled, after which promotion and activation remain
separate controlled operations.

The first authorized stage built and imported image
`localhost/a-stock-market-environment:20261009-102618-8e83125` once and froze digest
`sha256:8ca1614e6bd69879b56070b9157cfda2cb5e7b38a3de02d7dc54f6a21866cf42`.
Revisions 88, 89, and 90 applied the database component, service component, and complete
sectors-off release. The generic `component=all` tail then incorrectly treated the now-populated
`FROZEN_IMAGE_*` values as authorization to apply a disabled schedule component, creating
revision 91 with the reviewed empty, non-hook disabled schedule-component stored manifest. The live Dashboard remained Ready on the
frozen image with sectors disabled and no CronJob/Job, but the exact stored-release gate
correctly rejected promotion. No probe, capability write, activation, or collection followed.

## Goals / Non-Goals

**Goals:**

- Add one reusable, transactional boundary between isolated capability evidence and the runtime capability repository.
- Enable the existing Fuyao fallback without changing Eastmoney-first ordering, dates, payload shape, or field authority.
- Make image staging, dry-run, apply, config-only activation, observation, and rollback independently auditable.
- Make provider probes reject pre-settlement, non-current, and non-trading-date execution before provider or artifact I/O.

**Non-Goals:**

- Do not make the probe write directly to production or accept a production database URL on the command line.
- Do not export the production database URL to the operator host, copy the reviewed report into a Pod, or persist it in the container.
- Do not enable Eastmoney dataapi enrichment, Scrapling, scheduled collection, another Fuyao dataset, or a new HTTP API.
- Do not rebuild or import an image during config-only activation/rollback, bypass the time gate with a force flag, or use bare Helm, `kubectl patch`, historical Helm rollback, or release uninstall.
- Do not migrate the old v1 report, backfill historical sectors, or delete reports, snapshots, tasks, Jobs, Secrets, or PVCs.

## Decisions

### 1. Promote reviewed evidence through a generic CLI use case

Add `capabilities promote` under the market-environment CLI. It accepts a redacted report envelope plus explicit provider, dataset, and revision selectors. The runtime database is resolved only from normal environment settings, so credentials do not appear in arguments or output.

Dry-run is the default. It parses the input, selects exactly one report, validates it, opens the configured repository only for conflict inspection, and reports a redacted plan. `--apply` runs the same validation and writes through the provider-capability repository inside one application transaction.

Alternative considered: extend `fuyao real-probe` with a production database target. Rejected because it would combine external I/O, evidence generation, review, and production mutation in one command.

Alternative considered: use a one-off SQL statement or import the entire probe SQLite database. Rejected because both bypass repository validation and can mutate unrelated facts.

### 2. Use the existing capability model as the signed logical envelope

`ProviderCapabilityReport.from_dict` verifies the canonical checksum. Promotion additionally requires an exact selector match, `eligible` status, positive sample count, and non-empty endpoint, field coverage, date evidence, permission evidence, and rate-limit evidence. Applying the repository redaction function to the supplied report must produce an identical value; otherwise the command rejects it without echoing the offending value.

An existing identical checksum is idempotent. An existing provider/dataset/revision with a different checksum remains a conflict rather than an implicit overwrite. A genuinely changed provider contract therefore needs a new reviewed revision.

Promotion also applies a registered evidence policy after generic validation. The
`fuyao/sectors/fuyao-market-v2` policy requires the three official endpoints, matching
envelope/requested/calendar/snapshot dates, 320 unique catalog rows and 320 unique snapshot
rows with 1.0 coverage, same-day batch timestamps, complete code/name/changePct/amount
coverage, explicit absence evidence for the five unsupported fields, configured permission,
and a positive request budget with `requestsUsed <= requestBudget`. Unknown policies and the
legacy v1 contract fail closed. The original canonical report is checksum-validated before
redaction equality is checked; the command never recomputes a checksum over a redacted copy.

### 3. Stream production promotion into the disabled runtime

Promotion writes only `provider_capability_reports`. It does not construct a provider client,
collection coordinator, snapshot committer, scheduler, deployment client, Secret client, or
change any enabled/approvedRevision setting. Tests inject repository/UoW doubles and assert
zero provider, snapshot, configuration, and deployment operations.

The CLI accepts `--input -` as one JSON envelope from stdin while retaining file input for
isolated use. The controlled production path resolves exactly one Ready application Pod,
proves it runs the staged frozen image with sectors disabled and both application CronJobs
absent, then uses `kubectl exec -i` to stream the local reviewed envelope to the CLI. The Pod
uses its existing `MARKET_ENVIRONMENT_DATABASE_URL` Secret reference. The wrapper never reads,
prints, or exports that value and does not use `kubectl cp`.

Alternative considered: port-forward PostgreSQL and run the CLI on the operator host. Rejected
because it would export production database credentials and create an additional network path.

### 4. Stage one clean reviewed image with sectors disabled

Before probe promotion, freeze a production packet bound to the clean reviewed HEAD, chart,
off/enabled values, release, namespace, Kubernetes version, rendered manifests, and image
repository/tag. The sectors-off operation builds, saves, transfers, and imports that image
exactly once, then resolves the manifest digest from the exact imported containerd tag and
completes the immutable image identity before any Helm write. An operator-supplied digest, when
present, must match the resolved digest; it is not required before the only build. At minimum the
completed packet records `reviewedHead`, `chartSha256`, `offValuesSha256`,
`enabledValuesSha256`, `offRenderSha256`, `enabledRenderSha256`, release, namespace,
Kubernetes version, and the immutable image repository/tag/manifest-digest identity. The
real-probe envelope is separately bound by its file SHA-256 and canonical capability checksum.

The first rollout builds, transfers, and imports the image exactly once and deploys the complete
sectors-off release. It must fail before network or cluster writes when the checkout is dirty,
the reviewed HEAD or source packet hashes differ, scheduling is not disabled, or the candidate
values enable sectors, enrichment, shadow, Scrapling, or an unrelated Fuyao dataset. If the
exact imported tag does not resolve to one valid manifest digest, it must stop before Helm writes.

When the reviewed values keep scheduling disabled, the staged database and service writes end
with exactly one `component=all` convergence. The generic schedule-component tail is not part of
that flow even after the stage discovers and freezes the image digest.

### 5. Repair an interrupted sectors-off release without rebuilding

An explicit `repair-sectors-off-release` operation exists only for the observed partial-stage
shape: the stored release must be the exact expected deployed revision and equal the reviewed empty,
non-hook disabled schedule-component render; its chart, hooks, and computed values must also match
while the live tracked Deployment/Service declarative state equals the reviewed complete off
release and its Deployment/ReplicaSet/Ready Pod chain proves the exact frozen image and
sectors-off environment. Both application CronJobs and every namespace Job must be absent, the reviewed
source/chart/values/full renders and image digest must match, and preserved Secret/PVC identities
must be captured before any write.

Repair performs one `helm upgrade --no-hooks` with `component=all`, the reviewed sectors-off
values, and the exact existing image repository/tag. It does not build, save, copy, transfer,
import, retag, execute a hook, invoke a provider, promote a report, or run a collection. The
postcondition requires the immediately following revision to be deployed with the reviewed complete
off stored manifest and computed values, the tracked live Deployment/Service state to equal that release,
the exact Pod/image and sectors-off state to remain intact, CronJob/Job absence, and unchanged
Secret/PVC identities. Any other stored-manifest or live-state shape fails before Helm writes.
The repair-control source HEAD is reviewed independently from the already-frozen image source
HEAD; immutable image identity remains the imported tag plus manifest digest recorded by the
original stage.

### 6. Enable Fuyao sectors with a same-image config-only rollout

Add a TrueNAS values overlay that references the existing `a-stock-market-provider` Secret key and sets only the sectors enabled flag and approved `fuyao-market-v2` revision. The overlay explicitly keeps sector shadow/enrichment and Scrapling disabled. The ordinary deployment contract continues to render no CronJob, and the rollout packet must prove both exact CronJob names absent.

After promotion, a dedicated config-only operation renders the complete Helm release with hooks
disabled and the exact staged image identity. It performs no build, save, copy, import, migration,
or provider-backed Job. Before Helm writes it compares the live and desired manifests and values;
the only permitted semantic difference is
`MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED: "0" -> "1"`. Resource identities, image,
Secret references, PVCs, Services, topology, scheduling, approved revision, enrichment, shadow,
Scrapling, and unrelated provider settings must be identical.

The first collection is a one-dataset manual run after settlement. Acceptance requires exact date, Fuyao source/revision, stable ranking, fallback/partial quality, four supported fields, five unsupported fields as `null`, and the preceding Eastmoney failures in warnings.

### 7. Reject provider I/O before the settlement gate

`fuyao real-probe` validates the requested date against the current effective Shanghai market
date, weekday, and configured settlement time before constructing any provider/client or creating
the JSON/SQLite output. There is no force bypass. The one production collection uses the existing
settlement-gated, one-dataset `snapshots scheduled-refresh --dataset sectors` path rather than a
general refresh command.

### 8. Roll back by configuration only

Rollback runs the same config-only operation against the reviewed off profile and the exact same
staged image. The only permitted semantic difference is the sectors enabled flag from `"1"` to
`"0"`. It never rebuilds an image, runs hooks, or deletes the promoted report or collected
evidence. A failed post-rollback attempt may be `failed-retained` only for the same date;
cross-date substitution remains prohibited.

## Risks / Trade-offs

- [A reviewed report is promoted to the wrong database] -> Resolve the target from runtime settings, print only a masked backend identity, require dry-run, and bind apply evidence to report checksum and deployment packet.
- [A report contains credentials despite being called redacted] -> Compare the supplied structure with the standard redaction result and fail without reproducing sensitive values.
- [The provider contract changes under the same revision] -> Reject checksum conflicts and require a new revision plus probe.
- [Fuyao restores only part of `SectorRow`] -> Keep unsupported fields `null`, quality fallback/partial, and visible warnings.
- [A rollout accidentally reactivates scheduling or optional engines] -> Use a dedicated overlay and deployment tests that prove both CronJobs absent and unrelated switches false.
- [The old runtime cannot execute promotion] -> Stage the reviewed image with sectors off before promotion and prove zero Fuyao I/O during that rollout.
- [A partial stage narrows the stored release after the live service is healthy] -> Skip the schedule tail whenever scheduling is disabled and allow only the expected deployed revision with the exact reviewed empty non-hook disabled schedule-component failure shape to enter a same-image, hook-free complete-release repair.
- [Production credentials escape to the host] -> Execute promotion in the exact Ready Pod and stream only the redacted report over stdin.
- [Config rollback changes the image or another resource] -> Freeze the image identity and reject every live/desired semantic diff except the sectors enabled flag before Helm writes.
- [An operator starts the current-date probe before settlement] -> Enforce the date/weekday/settlement check in the CLI before provider or output I/O; provide no force escape.

## Migration Plan

1. Complete the existing unified-adapter application deployment with all new provider switches disabled and both CronJobs absent.
2. Implement stdin promotion, the pre-I/O settlement gate, packet validation, and frozen-image config-only rollout; run all offline gates.
3. Freeze a clean reviewed source/values/render/repository-tag packet, build and import the image once, resolve and freeze its exact containerd manifest digest before any Helm write, and deploy the complete sectors-off release. Verify health, image identity, Secret references, PVC identities, disabled optional engines, and CronJob/Job absence. A disabled stage stops after complete-release convergence and does not apply a schedule component.
4. If an interrupted stage has the expected deployed revision with the exact reviewed empty non-hook disabled schedule-component stored manifest and computed values, while tracked live Deployment/Service state equals the complete off release and the exact frozen sectors-off Pod is healthy, run the reviewed same-image hook-free repair once and prove the immediately following revision restores the complete sectors-off release. Do not repair any other drift shape.
5. After settlement and explicit authorization, run the current code's real probe into a new isolated SQLite path and redacted JSON file. Review the exact-date v2 sectors report, envelope SHA-256, canonical checksum, 320/320 coverage, and redaction equality.
6. Stream the reviewed report to the exact Ready staged Pod. Run promotion dry-run, review its single-row masked plan, then run explicit apply and verify the checksum and database before/after counts without exporting database credentials.
7. Run the config-only enable operation with the frozen image and reviewed enabled profile. Require an exact one-field semantic diff, hooks disabled, complete release resource preservation, healthy rollout, and both CronJobs absent.
8. Start exactly one settlement-gated current-date sectors collection and verify task, snapshot, status, and chapter response evidence.
9. On any rollout or observation failure, run the same config-only operation with the off profile and frozen image, then retain all reports, snapshots, task history, Jobs, Secrets, and PVCs.
