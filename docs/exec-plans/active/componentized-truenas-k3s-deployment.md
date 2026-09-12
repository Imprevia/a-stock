# componentized-truenas-k3s-deployment

## Stage（阶段）

把 `scripts/deploy-truenas-k3s.sh` 升级为 `all` / `database` / `service` / `schedule` 四个组件目标，并保留原 one-click 入口。

## Status（状态）

`in-progress / Stage 1 rework`

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
| 1 | D1-D3 | 脚本参数化、Helm 组件分支、PVC 保留/校验、依赖/后置条件、image work 分流、rollback 与 baseline fixture | 资深后端工程师 | `in_progress / rework_requested`，仅本阶段启动 | `bash -n`、`--help`、组件 fake trace、render hash、pytest focused、exact commit、无真实目标访问 |
| 2 | D4-D5 | 离线 all/database/service/schedule 矩阵、fake SSH/kubectl/containerd、首次安装与幂等重跑、partial all | 资深后端工程师 | `backlog`，Stage 1 完成后提升 | Helm lint/template 矩阵、OpenSpec strict、docs-contract、失败无写入与 PVC UID 保留证据 |
| 3 | D6 | 独立测试复核任务范围、负例、资源集合、调度授权边界和回归 | 资深测试工程师 | `backlog`，Stage 2 GO 后提升 | 测试报告、缺陷清单、固定命令输出、明确 GO/NO-GO，绑定 exact HEAD |
| 4 | D7 | 上线前只读计划、窗口/权限/监控/回滚清单；不执行生产变更 | 资深运维专家 | `backlog`，Stage 3 GO 后提升 | 运维计划与 runbook 对齐；Gate B/C 仍未授权的书面确认 |

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

- 计划阶段已完成：`python3 scripts/check-docs-contract.py --mode=fast` 通过（代码 0 / 文档 0 / plan 0）；`openspec validate componentized-truenas-k3s-deployment --strict --json` 通过（1/1）。
- 已创建串行子 issue：GYT-60（Stage 1 实施，资深后端，`todo`）、GYT-61（Stage 2 离线验证，资深后端，`backlog`）、GYT-62（Stage 3 独立测试，资深测试，`backlog`）、GYT-63（Stage 4 只读上线计划，资深运维，`backlog`）。
- Stage 1 执行人申报（GYT-60；已被独立审计退回，不是完成证据）：
  - `bash -n scripts/deploy-truenas-k3s.sh` 通过；`--help` 列出 `--component {all,database,service,schedule}`。
  - Helm chart 增加 component intent 模板分支：`database` 渲染 PVC（chart-managed）或 verify existingClaim，`service` 渲染 Deployment/Service/Ingress，`schedule` 渲染 suspended CronJob；`all` 维持原行为。
  - 执行人申报新增 focused 组件 fake-target 测试；审计环境缺少 pytest，当前数字不可作为独立实测结果。
  - 新增 component render 矩阵测试覆盖：`database` 仅 PVC、`service` 仅 dashboard 不含 PVC/CronJob、`schedule` 仅 suspended CronJob、existingClaim 路径不渲染 PVC object、`component=invalid` 在 chart schema 阶段拒绝。
  - `helm lint --strict deploy/helm/a-stock` 通过；`bash scripts/deploy-truenas-k3s.sh --offline-render --component {all,database,service,schedule} ...` 在 fake target 下成功。
  - 执行人申报 50 个既有失败未增加；该说法尚缺可复核测试环境和 exact commit 绑定。
  - Stage 1 范围内未运行 server-side dry-run、未创建 CronJob/Job、未备份、未发布、未激活调度；Gate B / Gate C 仍保持未授权。
- `bash -n scripts/deploy-truenas-k3s.sh` 通过。
- `helm lint --strict deploy/helm/a-stock` 通过。
- `python3 scripts/validate-scheduling-packet.py validate-generic-deploy-values --values deploy/helm/a-stock/values.yaml --values deploy/truenas/values-secure-manual-collection.yaml` 通过。
- 新增/更新的 Pytest 用例（manifest + TrueNAS guard 套件）全部通过且无需真实 TrueNAS/Provider。
- 文档 contract fast 检查通过（或显式记录既有阻断项）。

## Remaining Gaps（剩余缺口）

- GYT-60 独立审计为 NO-GO（`audit.state=rework_requested`）：实现尚未形成 clean、可交付且与 `origin/main` 对齐的 exact commit；OpenSpec 1.2、3.2-3.7 保持重新打开。
- `tests/fixtures/truenas_component_baseline.yaml` 当前无测试引用，无法证明缺失/冲突字段会被拒绝；OpenSpec 1.2 重新打开。
- `database`/`schedule` 当前在读取 namespace/PVC/service/runtime image 前以 render-only success 早退，未完成独立组件依赖验证；OpenSpec 3.2 重新打开。
- `service` 最终 pre-write render 与 `helm upgrade --install` 未携带 `component=service`，会回落为 chart 默认 `all`；OpenSpec 3.5 重新打开。
- `schedule` 的 frozen repository/tag 在初次 render 后才校验且未注入该 packet，无法证明调度与 reviewed frozen image 一致；OpenSpec 3.4/3.5 重新打开。
- reviewed schedule 写模式未透传 `component=schedule`，仍可能升级完整 release；OpenSpec 3.6 重新打开。
- `all` 仍只执行一次 Helm upgrade 并打印顺序摘要，未证明 database -> service -> schedule 的逐组件屏障、completed/failed 状态、PVC 保留与唯一 retry target；OpenSpec 3.3/3.7 重新打开。
- 系统 Python 缺少 pytest，但仓库 `.venv/bin/python` 可用；已只读复跑现有 component 用例为 manifest `4 passed`、guard `9 passed`。这些测试未覆盖本轮阻塞，返工仍须补 service final write、fixture consumption、dependency rejection、schedule frozen mismatch/reviewed mode、all staged failure/retry 负例，并提供命令、退出码、关键输出和 exact commit 绑定。
- Stage 2-4 的离线证据、独立测试和运维计划尚待对应子 issue 交付；当前 active plan 不将已有共享工作树改动视为本 change 的完成证据。
- 未在真实 TrueNAS 1.20 上执行 `all`/`database`/`service`/`schedule`；所有验证均为脱机 fake target / fake Helm / fake SSH/kubectl/containerd。
- 真正的 Gate C 激活必须使用既有的 `--activate-schedule` 路径并提交可审查证据；本任务不引入裸 CronJob patch 或直接 apply。
- 共享 worktree 在本计划启动前已有其他 agent 的 Helm/部署/fixture 改动；不得 reset、stash 或覆盖，后续证据必须绑定可审查的 exact diff。

## 子 issue 路由

| Issue | Stage | 角色 | 状态 | 提升条件 |
|-------|-------|------|------|----------|
| GYT-60 | 1 实施返工 | 资深后端工程师 | `todo / rework_requested`，新 run 等待 in-place 工作目录 | 修复 1.2、3.2-3.7，提交 clean exact commit 与可复核 focused evidence |
| GYT-61 | 2 离线验证 | 资深后端工程师 | `backlog` | GYT-60 terminal 且 exact diff/实现证据可复核 |
| GYT-62 | 3 独立测试 | 资深测试工程师 | `backlog` | GYT-61 GO、离线矩阵与 docs-contract/full evidence 完整 |
| GYT-63 | 4 上线准备 | 资深运维专家 | `backlog` | GYT-62 独立测试 GO；仅交付只读上线计划 |

## Next Step（下一步）

- 已重新调度 GYT-60 原资深后端工程师；新 run `01a09301-29ae-76fe-9b3a-d4b03324710e` 将在本次 in-place 工作目录释放后启动。返工修复 fixture 消费、组件依赖检查、service component 写入、schedule frozen image/既有 reviewed 模式绑定、`all` 真实分阶段编排及 failure/retry 证据，并完成 exact-main 收尾；修复后回到 `in_review` 接受独立复验。
- 仅在 GYT-60 独立审计 GO 且达到 terminal 状态后，将 GYT-61 从 `backlog` 提升为 `todo`。
- 依次提升 GYT-62、GYT-63；任何阶段失败都回流对应实现/验证 issue，不跳过屏障。
- 本阶段不访问 1.21 VM、不执行 read-only-discovery/server-side dry-run，不触发真实 `service`/`schedule`；Gate B/Gate C 仍保持未授权。
