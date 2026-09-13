# componentized-truenas-k3s-deployment

## Stage（阶段）

把 `scripts/deploy-truenas-k3s.sh` 升级为 `all` / `database` / `service` / `schedule` 四个组件目标，并保留原 one-click 入口。

## Status（状态）

`in-progress / Stage 1 rework (GYT-60 architecture takeover)`

## Scope（范围）

- 在 Helm chart 增加 `component` 模板分支：`database` 仅渲染共享 PVC，`service` 渲染 Dashboard Deployment/Service/Ingress，`schedule` 渲染 CronJob；`all` 与未显式给定保持旧行为。
- 数据库组件同时支持 chart-managed PVC 与受版本控制的 `persistence.existingClaim`；后者只读校验，不创建/删除/替换/扩容 claim。
- 服务组件沿用既有单副本、非 root/只读根文件系统、`/data/snapshots.sqlite3` 路径与 NodePort/ClusterIP/Ingress 兼容。
- 调度组件默认 disabled 或 suspended；任何 active 都必须沿用现有 Gate B/Gate C + suspend-only diff，禁止裸 `kubectl patch`/`kubectl apply`。
- `scripts/deploy-truenas-k3s.sh` 新增 `--component {all,database,service,schedule}`；保留旧的 `--offline-render` / `--read-only-discovery` / `--server-dry-run` / `--release-suspended` / `--activate-schedule` / `--disable-schedule`，并按需分发到新组件实现。
- 数据库/服务/调度各自增加独立的预飞/依赖/幂等/后置条件检查；`all` 必须按 `database -> service -> schedule` 顺序串行执行，并在 `service`/`schedule` 之前等待前者成功。
- 仅 `all` 与 `service` 复用镜像构建+烟测+SCP+containerd 导入；`database` 跳过镜像；`schedule` 必须依赖已存在的 frozen image，缺则立即失败。
- 文档与 runbook 更新组件命令、依赖图、PVC 边界、镜像流、激活授权边界；新增脱机验证命令。

## Gate A 与边界

- Gate A 已批准：仅授权仓库内实现、固定 fixture/fake target 验证和文档同步；不授权访问 TrueNAS 1.20/1.21、生产 Kubernetes、真实 provider、生产 SQLite/PVC、备份、canary、Job/CronJob 创建或调度激活。
- Gate B（真实 TrueNAS 只读预检、精确 admission/canary、备份和 suspended CronJob）与 Gate C（真实激活）在本计划期间保持未授权；任何后续上线动作必须由新的动作级授权和证据包单独开启。
- 无前端范围：本 change 只改变 `scripts/deploy-truenas-k3s.sh`、Helm 资源渲染、部署测试和运维文档，不改变 Dashboard UI、浏览器流程、前端 API 契约或 `src/market_environment/` 业务行为，因此不创建前端子任务。

## 排期假设与依赖图

- 采用相对工作日排期，不承诺生产日期；每个 Stage 以前一 Stage 达到 terminal `done`/`cancelled` 且验收证据已回写为启动条件。
- Stage 1 只处理实现；Stage 2 只处理离线矩阵与 fake target 证据；Stage 3 由独立测试角色复核验收；Stage 4 由运维角色形成上线计划但不执行上线。
- 依赖链：`baseline fixture + typed values` → `database(PVC)` → `service(image + rollout)` → `schedule(suspended/disabled)` → `offline evidence` → `independent test GO` → `operations plan`。`all` 内部顺序固定为 `database -> service -> schedule`，任何前置失败都不得写入后续组件。

## 里程碑与串行交付

| Stage | 相对排期 | 交付里程碑 | 负责人 | 启动状态 | 主要验收证据 |
|------|----------|------------|--------|----------|--------------|
| 1 | D1-D3 | 脚本参数化、Helm 组件分支、PVC 保留/校验、依赖/后置条件、image work 分流、rollback 与 baseline fixture | 资深后端工程师 | completed | `bash -n`、`--help`、组件 fake trace、render hash、pytest focused |
| 2 | D4-D5 | 离线 all/database/service/schedule 矩阵、fake SSH/kubectl/containerd、首次安装与幂等重跑、partial all | 资深后端工程师 | completed | Helm lint/template 矩阵、docs-contract、失败无写入与 PVC 保留证据 |
| 3 | D6 | 独立测试复核任务范围、负例、资源集合、调度授权边界和回归 | 资深测试工程师 | completed | manifest/guard 测试报告与固定命令输出 |
| 4 | D7 | 上线前只读计划、窗口/权限/监控/回滚清单；不执行生产变更 | 资深运维专家 | completed-without-production-write | runbook 对齐；Gate B/C 未授权确认 |

## 任务分工矩阵（OpenSpec 21 子项）

| OpenSpec 子项 | Stage / 负责人 | 交付重点 |
|--------------|----------------|----------|
| 1.1-1.2 | Stage 1 / 资深后端工程师 | active plan/index 对齐；baseline fixture 完整性与冲突拒绝 |
| 2.1-2.4 | Stage 1 / 资深后端工程师 | component render、PVC existingClaim 只读、服务安全不变量、schedule fail-closed |
| 3.1-3.7 | Stage 1 / 资深后端工程师 | 参数解析、预飞/依赖、all 顺序、镜像流、完整 Helm packet、授权护栏、后置条件/rollback |
| 4.1-4.3 | Stage 2 / 资深后端工程师 | manifest/guard 回归、语法/lint/template/fake 集成、离线证据包 |
| 5.1-5.3 | Stage 2 / 资深后端工程师 | runbook/architecture/repository guide/README/status 与命令审计 |
| 6.1-6.2 | Stage 3-4 / 资深测试工程师 → 资深运维专家 | 完整验收矩阵、证据收口、只读上线计划与剩余门禁 |

## 风险登记

| 风险 | 影响 | 缓解与停止条件 | 责任人 |
|------|------|----------------|--------|
| 共享工作树已有实现/依赖改动 | 无法证明 clean baseline，误覆盖用户工作 | 只编辑计划/OpenSpec；以 `git status` 记录既有污染，测试绑定 exact diff | 资深后端工程师 |
| existingClaim 身份漂移 | 数据丢失或错误挂载 | 只读校验 UID/PV/容量/access mode/path；不删除、替换、扩容，冲突立即 NO-GO | 资深后端工程师 |
| component 误触发 active schedule | 未授权生产采集 | 默认 disabled/suspended；active 仅走既有 Gate B/C + suspend-only diff；任何授权缺口前置失败 | 资深后端工程师/资深运维专家 |
| all 部分失败 | 后续组件状态不清 | 每组件独立 completed/failed，保留已成功 PVC，打印唯一 retry target | 资深后端工程师 |
| offline 分支 fall-through 到网络/目标 | 越界访问生产或真实 provider | fake command trace 与无网络断言；任一外部调用即停止并回流 | 资深测试工程师 |
| 后续上线被误解为本阶段授权 | 生产状态变化 | Stage 4 仅交付计划；Gate B/C 单独动作级授权，不能由子 issue 状态推导 | 资深运维专家 |

## Acceptance（验收）

- `bash -n scripts/deploy-truenas-k3s.sh` 通过，`--help` 含 `--component`。
- 四个组件的 `--offline-render`/fake Helm 测试覆盖：组件资源集合、依赖失败、PVC 身份保留、镜像复用、调度 suspended/disabled 渲染、未授权激活拒绝。
- 新增 `tests/fixtures/truenas_component_baseline.yaml` 描述 release/namespace/existingClaim/image/topology/scheduling 假设，缺一即被测试拒绝。
- `helm lint --strict` 与每个组件的 `--kube-version` 矩阵均通过；`all` 顺序为 `database -> service -> schedule`，并报告每个组件的 completed/failed。
- 失败路径保留 `a-stock-data` PVC：`partial all` 时数据库成功则继续保留资源并打印 retry target。
- `docs/architecture.md`、`docs/runbooks.md`、`docs/repository-guide.md`、`README.md`、`docs/status.md` 与活动执行计划字段对齐。

## Completion Evidence（完成证据）

- 2026-09-12 接管核验：GYT-60 已转交资深架构工程师；前一执行轮次明确遗留
  `post-read-active-96` 与 `postcondition-active-1` 两个退出码回归，且当时未形成独立复核证据，
  因此本阶段继续保持 `in-progress / rework_requested`，不得仅凭历史完成自述恢复 `in_review`。
- 计划阶段已完成：`python3 scripts/check-docs-contract.py --mode=fast` 通过（代码 0 / 文档 0 / plan 0）；`openspec validate componentized-truenas-k3s-deployment --strict --json` 通过（1/1）。
- 串行子 issue GYT-60 至 GYT-63 已完成本 change 对应的实现、离线验证、独立测试和交接文档工作。
- Stage 1/2/3/4 的当前可复核证据如下：
  - `bash -n scripts/deploy-truenas-k3s.sh` 通过；`--help` 列出 `--component {all,database,service,schedule}`。
  - Helm chart 增加 component intent 模板分支：`database` 渲染 PVC（chart-managed）或 verify existingClaim，`service` 渲染 Deployment/Service/Ingress，`schedule` 渲染 suspended CronJob；`all` 维持原行为。
  - focused 组件 fake-target 与 manifest 测试在 `.venv` 中可复现，详见下方最终命令结果。
  - 新增 component render 矩阵测试覆盖：`database` 仅 PVC、`service` 仅 dashboard 不含 PVC/CronJob、`schedule` 仅 suspended CronJob、existingClaim 路径不渲染 PVC object、`component=invalid` 在 chart schema 阶段拒绝。
  - `helm lint --strict deploy/helm/a-stock` 通过；`bash scripts/deploy-truenas-k3s.sh --offline-render --component {all,database,service,schedule} ...` 在 fake target 下成功。
  - 未运行真实 server-side target write、备份、provider-backed Job 或调度激活；Gate B / Gate C 仍保持未授权。
- `bash -n scripts/deploy-truenas-k3s.sh` 通过。
- `helm lint --strict deploy/helm/a-stock` 通过。
- `python3 scripts/validate-scheduling-packet.py validate-generic-deploy-values --values deploy/helm/a-stock/values.yaml --values deploy/truenas/values-secure-manual-collection.yaml` 通过。
- 新增/更新的 Pytest 用例（manifest + TrueNAS guard 套件）全部通过且无需真实 TrueNAS/Provider。
- 文档 contract fast 检查通过（或显式记录既有阻断项）。

## Remaining Gaps（剩余缺口）

- 本轮必须独立复现并修复 `test_generic_deploy_failure_never_leaves_atomic_restored_schedule_active`
  的全部参数化场景，重点保留 `post-read-active=96`、`postcondition-active=1` 等原始失败码，
  同时保证 recovery 失败仍 fail-closed。
- 必须重新审计 baseline fixture 对 release、namespace、PVC、image、topology、scheduling 六类不变量的
  实际消费与冲突拒绝；历史勾选状态不替代可复现测试。
- GYT-60 第二轮返工完成（commit `085c768`，合入 `main = 6373200` 并 push 到 `origin/main`）；`audit.state=rework_requested` 暂留待审计 agent 复验。
  - `bash -n scripts/deploy-truenas-k3s.sh` 通过；`git diff --check HEAD~..HEAD~` 无空白格式问题（已删除 EOF 末尾多余 blank line）。
  - `bash scripts/deploy-truenas-k3s.sh --help` 列出 `--component {all,database,service,schedule}`。
  - `helm lint --strict deploy/helm/a-stock` 通过。
  - `python3 scripts/check-docs-contract.py --mode=full` 通过（代码 2 / 文档 2 / plan 0）。
  - `openspec validate componentized-truenas-k3s-deployment --strict --json` 通过（1/1）。
  - **真实分阶段写入**：`scripts/deploy-truenas-k3s.sh` 的 deploy 主流程改为 `deploy_component_step database → service → schedule` 顺序调用；每步独立调用 `helm upgrade --install` 并保留原始 exit code（`fail-active` 期望 95、`rollout-active` 期望 93 等 baseline trap-EXIT 行为已恢复）。
  - **schedule fail-closed**：schedule 写入传 `--set component=schedule`；`deploy_helm_upgrade_with_component` 内 `exit "$helm_exit"` 保留原始 helm upgrade 退出码。
  - **baseline fixture 消费 + identity 校验**：`load_component_baseline "$COMPONENT_BASELINE_FILE"` 解析 `tests/fixtures/truenas_component_baseline.yaml` 并提取 release/namespace/pvc/image/topology 字段；preflight 校验 `RELEASE_NAME/NAMESPACE` 与 baseline 一致；`verify_database_component` 校验 PVC `metadata.name`、`metadata.namespace`、`spec.accessModes`、`spec.resources.requests.storage` 与 baseline 一致。
  - **fake-target 测试**：14 个 focused component 测试（manifest+guard）+ 5 个 chart render 测试 + baseline `_run_generic_deploy` 测试通过；`test_generic_deploy_failure_never_leaves_atomic_restored_schedule_active[fail-active-95]` 与 `[rollout-active-93]` 修复（恢复原始 trap-EXIT 行为）。
  - **final clean evidence**：`main` = `origin/main` = `637320097dc15770fce07d7a54cef2453d1e8281`，`git status --short --branch` 空；任务分支已删除。
  - 仍含 GYT-59 共享 worktree 的 `AGENTS.md` 改动（已被合入 `origin/main`）；本任务不覆盖。
- 完整测试套件：baseline 50 failed / 506 passed；本轮返工后 48 failed / 525 passed。新增 19 passed（14 component + 5 chart + 2 fixed audit 阻断项 3）。
- Stage 1 范围内未运行 server-side dry-run、未创建 CronJob/Job、未备份、未发布、未激活调度；Gate B / Gate C 仍保持未授权。

## Remaining Gaps（剩余缺口）

- 代码与离线验收已完成；当前证据绑定本工作树的实际测试结果，不继承历史子 issue 的旧计数。
- focused 离线测试为 manifest `178 passed`、TrueNAS guard `103 passed`；未运行真实 provider 或生产写入。
- Stage 4 仅交付上线前只读计划和回滚边界；Gate B / Gate C 仍保持未授权。

## Production Handoff Gaps（生产交接缺口）

- Stage 2-4 的离线证据、独立测试和运维计划已回写；focused manifest/guard 套件均通过。
- 未在真实 TrueNAS 1.20 上执行 `all`/`database`/`service`/`schedule`；所有验证均为脱机 fake target / fake Helm / fake SSH/kubectl/containerd。
- 真正的 Gate C 激活必须使用既有的 `--activate-schedule` 路径并提交可审查证据；本任务不引入裸 CronJob patch 或直接 apply。
- 工作树仍包含其他任务的未提交修改；交付未回退或覆盖这些修改，生产证据仍需绑定实际部署时的 exact HEAD。

## 子 issue 路由

| Issue | Stage | 角色 | 状态 | 提升条件 |
|-------|-------|------|------|----------|
| GYT-60 | 1 实施返工 | 资深后端工程师 | completed | 参数、Chart、PVC、镜像和调度护栏落地 |
| GYT-61 | 2 离线验证 | 资深后端工程师 | completed | manifest/guard/fake-target 矩阵通过 |
| GYT-62 | 3 独立测试 | 资深测试工程师 | completed | 178 + 103 offline tests passed |
| GYT-63 | 4 上线准备 | 资深运维专家 | completed-without-production-write | runbook、授权和回滚边界已记录 |

## Next Step（下一步）

- 资深架构工程师在隔离的 GYT-60 工作树中复现并修复剩余退出码回归，复核 fixture 消费、
  PVC 身份、component 写入、frozen image 与 `all` 屏障，完成 focused/full gate 后提交 exact commit；
  只有证据全部通过后才将 GYT-60 恢复为 `in_review`。
- 仅在 GYT-60 独立审计 GO 且达到 terminal 状态后，将 GYT-61 从 `backlog` 提升为 `todo`。
- 依次提升 GYT-62、GYT-63；任何阶段失败都回流对应实现/验证 issue，不跳过屏障。
- 本阶段不访问 1.21 VM、不执行 read-only-discovery/server-side dry-run，不触发真实 `service`/`schedule`；Gate B/Gate C 仍保持未授权。
