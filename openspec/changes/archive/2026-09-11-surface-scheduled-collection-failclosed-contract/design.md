## Context

The approved Gate A change `enable-truenas-scheduled-market-collection`
already implements the fail-closed default in code: `deploy/helm/a-stock/values.yaml`
declares `scheduledCollection.enabled=false / suspend=true` as the Chart
default; the CronJob template renders only when `enabled=true`; the
TrueNAS overlays (`scheduled-off`, `scheduled-suspended`, `scheduled-active`)
each layer on top of the secure-manual baseline; and
`scripts/deploy-truenas-k3s.sh` rejects any generic release whose typed
values are not exactly that pair before any Helm render, image work, or
target API access. The `proposal.md` and `design.md` of the Gate A change
also describe the Gate B / Gate C separation in prose.

None of this is captured in `openspec/specs/after-market-data-collection-scheduling`.
The main spec still requires that scheduled collection is "enabled by
default" — wording that the Gate A implementation has made false. Any
operator who reads the spec alone, or who arrives at the k3s deployment
months later, has no formal hook to discover that the absence of an
application CronJob is the intended contract rather than a missing
deployment.

See `proposal.md` for motivation. See the delta spec for the resulting
behavior contract.

## Goals / Non-Goals

**Goals:**

- Pin the fail-closed default and the Gate B / Gate C separation as a
  spec-level requirement on `after-market-data-collection-scheduling`,
  so the contract survives any refactor of the Chart, overlays, or entry
  point.
- Make the contract visible to operators in three places they already
  read: the active execution plan's `Remaining Gaps`, the project
  `status.md`, and the deployment `runbook`.
- Record the spec drift between the new delta requirement and the
  current main spec requirement "Configurable after-market schedule" as
  an explicit reconciliation item for the archive step.

**Non-Goals:**

- Modify any Helm template, overlay, entry point, test, or Chart
  manifest.
- Modify the Gate A implementation's `proposal.md`, `design.md`,
  `tasks.md`, or `spec.md`.
- Access the TrueNAS k3s cluster, call any provider, render against the
  real Kubernetes API, or change any production resource.
- Reconcile the spec drift inside this change. The drift is recorded in
  the delta spec so a later change — likely the Gate A archive — can
  edit the main spec's "enabled by default" wording when it merges the
  delta.
- Introduce a new capability, new failure mode, new audit log, or new
  test surface.

## Decisions

### 0. Distinguish progression authorization from action and operation authorization

The Gate A-approved implementation lineage records three distinct authorization
classes that the change artifacts, the operator-facing trail, and the spec
delta must keep separated:

- **Gate B / Gate C progression authorization** records that the work needed
  to reach Gate B and Gate C may proceed through prerequisite review. It is
  not a production-operation authorization and MUST NOT be presented to
  operators as evidence that scheduling may be created or unsuspended.
- **Gate B action authorization** is recorded only after the frozen packet
  review and covers the bounded production validation window: the exact
  server-side dry-run, one no-provider scheduling canary, a consistent
  SQLite backup, a suspended application CronJob release, and exactly one
  named provider-backed Job cloned from that CronJob after settlement.
- **Gate C operation authorization** is recorded only after Gate B evidence
  is accepted and explicitly selects `next-schedule` or `immediate
  catch-up` while authorizing only `spec.suspend: true -> false`.

This split mirrors `enable-truenas-scheduled-market-collection/design.md`
Gate A Delivery Plan and `proposal.md` Approval Record, where the recorded
progression authorization is explicitly noted as not bypassing the new clean
HEAD review, Stage 3 acceptance, exact production packet, Gate B evidence
acceptance, or the explicit Gate C catch-up choice. The original draft of
this delta conflated the three classes into "Gate B and Gate C have each
been separately authorized"; that wording is tightened below to prevent
operators from reading a recorded progression authorization as a green light
for production execution. No production behavior changes as a result of
this clarification — only the operator-facing wording is tightened.

### 1. Add a delta requirement rather than editing the main spec directly

The new requirement is recorded as an `## ADDED Requirements` block under
the existing capability `after-market-data-collection-scheduling` inside
this change's delta spec. Editing the main spec directly would (a) lose
the OpenSpec archive trail that proves why the wording changed, (b) blur
the boundary with the still-in-progress Gate A change that produced the
implementation, and (c) require the editor to also reconcile the
"enabled by default" wording on the same commit, which would couple an
unrelated clarification to a contract add.

### 2. Surface the contract in three artifacts operators already read

The delta requires visibility in `docs/exec-plans/active/...`, `docs/status.md`,
and `docs/runbooks.md`. Each of these is read during the recurring
post-deploy audit cycle and during onboarding. Adding the statement in
only the spec would leave the operator-facing trail untouched and would
not actually solve the "operators reading the k3s cluster" problem the
change targets.

### 3. Do not touch the Gate A artifacts

Gate A's `proposal.md`, `design.md`, `tasks.md`, and `spec.md` are part
of an independently reviewed implementation lineage bound to commit
`cd26dff3e6bebe012198dcd38074c354c1a9afac` plus docs-only wrappers
ending at `4f6d2b28b1694c78f53eb3ce007b8530b0667ead`. Editing any of
those would invalidate the independent Gate A verdict pending from
GYT-52 and would mix contract capture with implementation review. The
delta stays purely additive and human-visible.

### 4. Record the spec drift as an explicit reconciliation note

The main spec requirement "Configurable after-market schedule" still says
scheduled collection is "enabled by default". The new delta requirement
contradicts that wording. Rather than fix the contradiction here, the
delta's `Migration` companion note (inside the new requirement scenario)
records that the archive step for this change MUST also rewrite the main
spec wording to remove "enabled by default" or qualify it with the
Gate A preconditions. This keeps this change small and lets the Gate A
archive — which is the change that already owns the preconditions —
carry the wording cleanup at the natural point.

### Alternatives considered:

- **Edit the main spec inline.** Rejected because it loses the OpenSpec
  archive trail and forces a coupled wording fix.
- **Add a separate capability such as `scheduled-collection-authorization`.**
  Rejected because the contract is a property of the existing scheduling
  capability, not an independent domain; a second capability would split
  one behavior contract across two specs.
- **Surface the contract only in the runbook.** Rejected because the
  status document and active plan are the first artifacts an operator
  opens during incident triage; visibility in only the runbook leaves
  the wrong default mental model intact for the most common audit path.

## Risks / Trade-offs

- [Two specs may disagree until archive merges the delta] → The delta
  spec carries an explicit reconciliation scenario in its `Migration`
  note so the archive step is forced to clean up "enabled by default"
  before the wording becomes authoritative.
- [Operators who read main spec still see the old "enabled by default"
  text] → The active plan, status, and runbook additions are written
  with verbatim wording from the delta requirement so the operator-facing
  trail stays correct even before archive.
- [An operator reads a recorded Gate B / Gate C progression
  authorization as a green light to create or unsuspend a CronJob] →
  The delta requirement's second paragraph explicitly distinguishes
  Gate B action authorization and Gate C operation authorization from a
  recorded progression authorization, and the third scenario's `AND`
  clause forces the entry point to refuse non-off initial state until
  both action and operation authorizations exist. The active plan,
  status, and runbook state the same three-class distinction verbatim.
- [A future contributor may add a new overlay or entry-point branch that
  bypasses the fail-closed default] → The delta requirement's third
  scenario explicitly covers the entry-point rejection behavior, and
  the `Remaining Gaps` note in the active plan points new contributors
  to the spec delta so they discover the rule before extending the
  Chart or entry point.
- [Delta lands before Gate A archive, so a brief window of spec
  contradiction exists] → Acceptable; both Gate A and this change share
  the same senior-backend owner and the archive ordering is already
  documented in `enable-truenas-scheduled-market-collection/tasks.md`
  Stage 7 closeout.