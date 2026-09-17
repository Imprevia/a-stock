## 1. Spec Delta

- [ ] 1.1 Add the new `Fail-closed production scheduling default` requirement to `openspec/changes/surface-scheduled-collection-failclosed-contract/specs/after-market-data-collection-scheduling/spec.md` and verify the file contains the requirement header, the four scenarios, and that each scenario uses exactly four hashtags.

## 2. Operator-Facing Visibility

- [ ] 2.1 Append a "Production scheduled collection contract" bullet to `docs/exec-plans/active/enable-truenas-scheduled-market-collection.md` under `## Remaining Gaps（剩余缺口）` stating verbatim that production scheduled collection is absent or suspended by Gate A design until Gate B and Gate C are separately authorized, and verify the bullet is rendered after the existing bullets and quotes the delta requirement text.
- [ ] 2.2 Append a `### 生产定时任务契约（fail-closed 默认）` subsection to `docs/runbooks.md` immediately after the existing `## k3s 部署` section, restating the same contract in the runbook voice, and verify the subsection appears before `### Helm Chart 与受控发布入口`.
- [ ] 2.3 Append a `### 生产定时任务 fail-closed 契约` bullet to `docs/status.md` under `## 进行中` referencing the delta requirement path, and verify the bullet is rendered after the existing Gate A bullet.

## 3. Reconciliation And Validation

- [ ] 3.1 Record the spec drift between the new delta requirement and the existing main spec requirement "Configurable after-market schedule" (which still says "enabled by default") as an item to be cleaned up when this change is archived, and verify the item points to the specific main-spec wording that must be edited.
- [ ] 3.2 Run `openspec validate --change surface-scheduled-collection-failclosed-contract --strict` and `python scripts/check-docs-contract.py --mode=fast` and verify both exit code 0, no skipped checks, and that the full offline gate `python scripts/check-docs-contract.py --mode=full` is not required because no Helm, entry point, or test change is included in this change.