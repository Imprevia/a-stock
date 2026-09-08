# TrueNAS k3s 1.26 盘后定时采集 Gate A 实施计划

## Stage（阶段）

Gate A / Stage 1 项目计划与研发分配。后续仅包含仓库实现和离线验证；Gate B 生产验证与 Gate C 周期激活未获授权。

## Status（状态）

`in-progress`：Gate A 已批准，规划与研发分配已完成并待验收；后端研发任务保持串行 `backlog`，等待 Stage 1 验收和 reviewed clean baseline。

## Context（上下文）

- Parent：`GYT-45`（issue `01a07ca1-a97b-70c2-9e65-9d2cccd337cc`）。
- Gate A approval：成员于 2026-09-08（Asia/Shanghai）在评论 `01a07e3a-141c-71ac-b30b-0f06cf0c4a8b` 回复“批准”；Mika 在 `01a07e3d-5a77-7972-a9cd-360c9d41dc84` 记录 Gate A 决策。
- Approved change：`openspec/changes/enable-truenas-scheduled-market-collection/`。
- Gate A 只授权仓库实现与离线验证，不授权生产访问、生产 preflight、server-side dry-run、no-provider canary、SQLite 备份、suspended CronJob、provider-backed Job 或 recurring activation。

## Scope（范围）

### 后端 / 部署范围

- 在 Helm 中实现 `native`（Kubernetes 1.27+，输出 `spec.timeZone`）与 `controller`（k3s 1.26，省略该字段）策略及 fail-closed 校验。
- 增加 TrueNAS baseline + `scheduled-suspended` / `scheduled-active` / `scheduled-off` overlays，并保持镜像、PVC、NodePort、manual refresh 与安全上下文不变量。
- 更新 TrueNAS 部署入口，区分离线渲染、只读发现和后续需授权的写类验证；不得自动创建 canary/Job 或解除暂停。
- 先同步 README、产品规格、architecture、runbook、status，再修改代码；补齐 Helm/render/deployment/fake-provider 离线测试与证据。

### 无前端范围

**无前端范围。** 已批准 proposal/design 明确不修改 Dashboard 行为、页面、浏览器流程或前端 API 契约，因此不分配前端子任务。若实施发现必须改变前端，视为范围变更并返回架构审核。

### 明确排除

- 不修改应用 API、dataset、provider 行为、SQLite schema、collector 语义、NodePort 或 manual collection。
- 不访问生产集群、TrueNAS 主机或生产 SQLite/PVC，不调用真实 provider，不构建或发布生产镜像。
- 不执行 Gate B/Gate C 动作；不以 Gate A 批准推导任何生产权限。

## Assumptions（排期假设）

- 一名现有资深后端工程师串行投入；排期从 Stage 2 被人工提升为 `todo` 的下一个工作日开始，以 D1-D4 表示，不承诺未批准的生产日期。
- Stage 2 启动前存在一个 reviewed clean commit，并在独立 branch/worktree 中带入已批准 OpenSpec 与本计划；不 stash/reset/覆盖当前共享工作树中的他人改动。
- 离线验证只使用固定 fixture/fake provider，不依赖生产网络或 Kubernetes 写权限。

## Milestones（里程碑）

| Stage / 时间 | 里程碑 | 负责人 | 依赖 | 验收证据 | 状态 |
|---|---|---|---|---|---|
| Stage 1 / D0 | Gate A 计划与分配 | 资深项目经理 | Gate A approval | approval trace、OpenSpec/active plan、串行 backlog、strict validation | ready-for-review |
| Stage 2 / D1 | Clean baseline + 文档事实对齐（`GYT-47`） | 资深后端工程师 | Stage 1 accepted；reviewed clean commit/worktree | 精确 baseline SHA；README/product spec/architecture/runbook/status 一致；staged fast docs-contract 通过 | backlog |
| Stage 2 / D2-D3 | Helm/TrueNAS/部署入口实现（`GYT-47`） | 资深后端工程师 | 文档先行门禁通过 | tasks 2.1-2.5；focused render/deployment tests；无应用/前端/生产 diff | backlog |
| Stage 3 / D4 | 离线全矩阵与评审包（`GYT-48`） | 资深后端工程师 | `GYT-47` terminal + reviewed | tasks 3.1-3.5；Helm/OpenSpec/docs/full test/diff gate；clean reviewable diff | backlog |
| Gate B | 生产验证 | 未分配 | Stage 3 accepted + separate authorization | tasks 4.x-5.x 指定证据 | not authorized |
| Gate C | 周期激活 | 未分配 | Gate B evidence accepted + explicit authorization | suspend-only diff + next trigger evidence | not authorized |

## Task Breakdown And Dependencies（任务拆分与依赖）

1. Stage 1：项目经理记录 Gate A、工件边界、风险、计划与研发分配；不改代码。
2. Stage 2 / `GYT-47`：后端先建立 clean baseline 并完成 OpenSpec 1.3 文档对齐，再实现 2.1-2.5。文档未通过 staged fast gate 时禁止代码改动。
3. Stage 3 / `GYT-48`：后端在 `GYT-47` 完成并审阅后执行 3.1-3.5 离线验证；不得与 Stage 2 并行启动，避免测试证据绑定未冻结实现。
4. Gate B/Gate C：本轮不建可执行 issue、不分配负责人、不排生产日期；只有对应批准事实记录后才能另行规划。

## Risks（风险）

| 风险 | 影响 | 缓解 / 升级条件 | Owner |
|---|---|---|---|
| 当前 shared tree 含大量重叠 dirty files | diff 无法归属，gate 可能只验证旧提交 | Stage 2 保持 backlog；先建 reviewed clean branch/worktree并记录 SHA，禁止 reset/stash 他人改动 | PM + Backend |
| 现有 README/docs 对 1.26/1.27、revision 6/7 和直接 unsuspend 的表述冲突 | 实施依据不一致 | Stage 2 第一动作完成 OpenSpec 1.3；revision 7 仅记为 issue 报告，待后续获准只读预检验证 | Backend |
| canary 证据如何进入 fail-closed 校验未定义为具体配置契约 | 可能需要扩大批准设计 | 先按既有人工 gate 和 suspended 边界实现；若必须新增外部配置/API 字段，停止并提交架构差异复审 | Backend + Architect |
| Gate B 默认字段 allowlist、备份方法/空间阈值和 stop thresholds 尚未量化 | 后续 GO/NO-GO 不可重复判定 | 在 Gate B 请求包中先定义；任何生产动作前必须审核，Gate A 不代填生产事实 | Release owner |
| 误将 backlog 提升或把后续工作建为 todo | 未授权生产动作被触发 | 仅 Stage 2/3 建 backlog；Stage 2 需本计划验收，Stage 3 需 Stage 2 terminal；Gate B/C 不建 issue | PM |

## Acceptance（验收）

- OpenSpec 和本 plan 可追溯记录 Gate A 批准、里程碑、依赖、风险、负责人、验收证据和下一检查点。
- 实际仓库研发只分配给现有资深后端工程师，并以 Stage 2/3 `backlog` 串行停放；没有新建 specialist。
- 显式记录“无前端范围”及依据，没有向资深前端工程师创建无效任务。
- Gate B、Gate C 保持未授权；没有生产访问、真实 provider 调用、部署、备份、CronJob/Job 创建或激活。
- 本轮不改代码；OpenSpec strict、docs-contract 与 `git diff --check` 的实际结果及其 dirty-tree 限制如实记录。

## Completion Evidence（完成证据）

- 2026-09-08：已读取 parent approval thread、OpenSpec proposal/spec/design/tasks、active plan index、architecture、runbook、repository guide、status 和工作树状态。
- 2026-09-08：Gate A approval evidence 已定位为 `GYT-45` 评论 `01a07e3a-141c-71ac-b30b-0f06cf0c4a8b` 与 `01a07e3d-5a77-7972-a9cd-360c9d41dc84`。
- 2026-09-08：已确认现有资深后端工程师 ID `032a9aa5-2728-4ae7-b707-4175a957bb9c`；无前端任务。
- 2026-09-08：已在 parent `GYT-45` 下创建 `GYT-47`（Stage 2 implementation，issue `01a07e48-7b5a-712b-b22b-dcd3c8b1ba17`）与 `GYT-48`（Stage 3 offline verification，issue `01a07e48-7bd4-7a56-b7a6-7f9322520306`），均分配给资深后端工程师并保持 `backlog`，未触发执行。
- 2026-09-08：`openspec validate enable-truenas-scheduled-market-collection --strict --json` 通过（1/1）；active plan 六个必需字段齐全；full docs-contract 通过（代码 5 / 文档 7 / plan 2）；`git diff --check` 通过。
- 2026-09-08：fast docs-contract 输出“无变更，跳过 diff 检查”（代码 0 / 文档 0 / plan 0）。由于当前规划文件未 staged、full 模式又基于 upstream 范围，这两次结果不能证明 shared dirty tree 是 clean implementation baseline；OpenSpec 1.2 保持未完成，须在 `GYT-47` 的 reviewed clean baseline 中重跑。

## Remaining Gaps（剩余缺口）

- 当前分支和 shared tree 不是 clean implementation baseline；在隔离完成前 Stage 2/3 不得启动。
- OpenSpec 1.2 的 staged fast gate 与 1.3 的 README/product spec/architecture/runbook/status 对齐仍待 clean baseline 中完成。
- tasks 2.x-3.x 的实现与离线证据尚未开始。
- Gate B/Gate C 明确未授权；生产 revision、controller runtime timezone、image digest、PVC identity 和验证日期仍是后续待采集事实。

## Next Step（下一步）

完成本轮规划验收后，由 parent owner 在 reviewed clean commit/worktree 已建立且无重叠 active run 时，将 `GYT-47` 从 `backlog` 提升为 `todo`。`GYT-47` 必须先完成 OpenSpec 1.2/1.3 和 staged fast gate，再开始任何实现文件修改；`GYT-48` 在 `GYT-47` terminal + reviewed 前保持 `backlog`。
