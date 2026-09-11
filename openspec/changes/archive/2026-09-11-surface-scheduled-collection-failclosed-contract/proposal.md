## Why

The k3s deployment of the market-environment stack is observed by human operators
as having no application CronJob and no scheduled collection Jobs. Because the
production contract for that absence is not stated as a requirement in
`openspec/specs/after-market-data-collection-scheduling`, every operator who
audits the cluster must reconstruct the policy from
`proposal.md` / `design.md` / `deploy-truenas-k3s.sh` source to confirm the
absence is intentional rather than a deployment defect. The current main spec
in fact still says scheduled collection is "enabled by default", which is now
opposite to the fail-closed Chart default and the Gate B / Gate C authorization
contract that the approved Gate A implementation enforces. This change pins the
"absent until authorized" rule as a first-class requirement so it survives any
later refactor of the implementation, and so the next operator to look at a
quiet k3s deployment can answer the question from the spec alone.

## What Changes

- Add a delta requirement to `after-market-data-collection-scheduling`:
  scheduled collection MUST remain absent or suspended in production until
  Gate B and Gate C have been independently authorized and recorded; the
  Chart, TrueNAS baseline, and every overlay MUST default to
  `enabled=false / suspend=true`; generic install, upgrade, and
  application-rollback entry points MUST refuse to proceed unless the typed
  values are exactly that pair before the first Helm render, image work, or
  target API access; the active execution plan, status, and runbook MUST
  surface this contract so the absence is visible to operators without
  reading implementation source.
- Mark the conflict with the existing main spec requirement
  "Configurable after-market schedule" (which still says "enabled by
  default") as a known drift that must be reconciled when this delta is
  archived into the main spec.
- Do not touch any Helm template, overlay, deployment entry point, or test.
  Do not access the k3s cluster, call providers, or change production
  resources.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `after-market-data-collection-scheduling`: add the fail-closed default
  requirement and the surface-to-operators requirement; mark the
  existing "enabled by default" wording in the main spec as drift to be
  reconciled when this delta is archived.

## Impact

- Specs: `openspec/changes/surface-scheduled-collection-failclosed-contract/specs/after-market-data-collection-scheduling/spec.md`
  (new delta file, not the main spec).
- Documentation: `docs/exec-plans/active/enable-truenas-scheduled-market-collection.md`
  Remaining Gaps entry; `docs/status.md` recorded note.
- No code, no Helm, no entry point, no test, no production access.

## Spec Drift To Reconcile On Archive

When this change is archived, the merge MUST also reconcile the main spec
file `openspec/specs/after-market-data-collection-scheduling/spec.md`
requirement `Configurable after-market schedule`, whose current text reads
in part: "...enabled by default for the market-environment deployment,
runs in the `Asia/Shanghai` timezone after the configured settlement
boundary on Monday through Friday...". The merge MUST remove or
explicitly qualify the "enabled by default" phrase so the main spec does
not contradict the new `Fail-closed production scheduling default`
requirement that this delta adds. Acceptable reconciliation options:

1. Delete the phrase "enabled by default" from the main spec requirement
   text and reword the default scenario so it describes the off-by-default
   behavior of the new requirement.
2. Add an explicit "unless the fail-closed production scheduling default
   requirement applies, in which case the default is `enabled=false /
   suspend=true`" qualifier.

A `bash` grep verification must run after archive to prove the archived
main spec no longer asserts scheduled collection is enabled by default:

```
! grep -E 'enabled by default' openspec/specs/after-market-data-collection-scheduling/spec.md
```

This drift is intentionally not fixed in this change so the Gate A
implementation lineage bound to `cd26dff3e6bebe012198dcd38074c354c1a9afac`
and its docs-only wrappers remains untouched.