# TrueNAS k3s 1.26 盘后定时采集 Gate A 实施计划

## Stage（阶段）

Gate A / Stage 2 仓库修复与离线验证。Gate B/Gate C 的推进授权已经记录，但不授权本任务绕过修复、独立审阅、Stage 3 验收或各自的精确发布门禁。

## Status（状态）

`stage-2-complete-awaiting-acceptance`：GYT-47 implementation candidate `5672c2a147e8975ac0de218fa0605ce83882aadf` 已在隔离 worktree `agent/backend/gyt-47-scheduled-collection-clean-baseline` 提交、推送并经三路独立复审取得 GO。冻结基线为 `bb0de075c4336e6a4532b38f221b043d9859f590`；rejected HEAD `5cc6e7f97e24a38c72adb84aa88b4cc693e9b969`、`e6ae0c09be62b483b3e5f45a122acbb8f4c2fc3e` 与 `58f5c4a986387ddeeb2f2f352f7fc9e3f0a775b6` 均不得成为 Stage 3 基线。Stage 2 仓库交付已完成，等待 GYT-47 人工验收。

## Context（上下文）

- Parent：`GYT-45`（issue `01a07ca1-a97b-70c2-9e65-9d2cccd337cc`）。
- Gate A approval：成员于 2026-09-08（Asia/Shanghai）在评论 `01a07e3a-141c-71ac-b30b-0f06cf0c4a8b` 回复“批准”；Mika 在 `01a07e3d-5a77-7972-a9cd-360c9d41dc84` 记录 Gate A 决策。
- Approved change：`openspec/changes/enable-truenas-scheduled-market-collection/`。
- Gate A 只授权仓库实现与离线验证。成员随后在 GYT-47 评论 `01a07fcd-9140-7aa7-b05a-83485a7ed8c7` 写明“Gate B/Gate C 授权”，但该推进授权必须按顺序使用：GYT-47 修复并取得独立 GO，GYT-48 完成 Stage 3，再准备和审核精确 Gate B 包；Gate B 证据被接受且明确选择 `next-schedule` 或 `immediate catch-up` 后，Gate C 才可执行。

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
| Stage 1 / D0 | Gate A 计划与分配 | 资深项目经理 | Gate A approval | approval trace、OpenSpec/active plan、串行 backlog、strict validation | accepted |
| Stage 2 / D1 | Clean baseline + 文档事实对齐（`GYT-47`） | 资深后端工程师 | Stage 1 accepted；reviewed clean commit/worktree | 精确 baseline SHA；README/product spec/architecture/runbook/status 一致；staged fast docs-contract 通过 | completed after remediation |
| Stage 2 / D2-D3 | Helm/TrueNAS/部署入口实现（`GYT-47`） | 资深后端工程师 | 文档先行门禁通过 | tasks 2.1-2.5；focused render/deployment tests；无应用/前端/生产 diff | independent GO; awaiting GYT-47 acceptance |
| Stage 3 / D4 | 离线全矩阵与评审包（`GYT-48`） | 资深后端工程师 | `GYT-47` terminal + reviewed | tasks 3.1-3.5；Helm/OpenSpec/docs/full test/diff gate；clean reviewable diff | backlog |
| Gate B | 生产验证 | 未分配 | GYT-47 independent GO + Stage 3 accepted + exact packet review + exact action authorization | tasks 4.x-5.x 指定证据 | progression/read-only permission recorded; blocked by prerequisites |
| Gate C | 周期激活 | 未分配 | Gate B evidence accepted + catch-up choice + exact operation authorization | suspend-only live diff + next trigger evidence | progression authorized; blocked by prerequisites |

## Task Breakdown And Dependencies（任务拆分与依赖）

1. Stage 1：项目经理记录 Gate A、工件边界、风险、计划与研发分配；不改代码。
2. Stage 2 / `GYT-47`：后端先建立 clean baseline 并完成 OpenSpec 1.3 文档对齐，再实现 2.1-2.5。文档未通过 staged fast gate 时禁止代码改动。
3. Stage 3 / `GYT-48`：后端在 `GYT-47` 完成并审阅后执行 3.1-3.5 离线验证；不得与 Stage 2 并行启动，避免测试证据绑定未冻结实现。
4. Gate B/Gate C：推进授权和后续 read-only permission 已记录，但本轮不执行生产动作；只有 GYT-47 独立 GO、GYT-48 验收、read-only preflight、精确 packet 审核及覆盖 exact actions 的 Gate B authorization 依次成立后才能进入写类 Gate B，Gate C 还需接受 Gate B 证据并形成明确 catch-up 选择的最终 operation authorization。

## Risks（风险）

| 风险 | 影响 | 缓解 / 升级条件 | Owner |
|---|---|---|---|
| 当前 shared tree 含大量重叠 dirty files | diff 无法归属，gate 可能只验证旧提交 | Stage 2 只在已记录的隔离 branch/worktree 活跃修复；禁止 reset/stash 或带入 shared tree 改动 | PM + Backend |
| 现有 README/docs 对 1.26/1.27、revision 6/7 和直接 unsuspend 的表述冲突 | 实施依据不一致 | Stage 2 完成 OpenSpec 1.3 remediation；revision 7 仅记为 issue 报告，待前置验收后使用已记录 permission 做只读预检验证 | Backend |
| canary 证据如何进入 fail-closed 校验未定义为具体配置契约 | 可能需要扩大批准设计 | 先按既有人工 gate 和 suspended 边界实现；若必须新增外部配置/API 字段，停止并提交架构差异复审 | Backend + Architect |
| Gate B 默认字段 allowlist、备份方法/空间阈值和 stop thresholds 尚未量化 | 后续 GO/NO-GO 不可重复判定 | 在 Gate B 请求包中先定义；任何生产动作前必须审核，Gate A 不代填生产事实 | Release owner |
| 误将 backlog 提升或把推进授权解释为跳过门禁 | 越权生产动作被触发 | Stage 3 需 Stage 2 independent GO；Gate B/C 即使获推进授权也必须逐项满足精确 packet 和证据门禁 | PM |

## Acceptance（验收）

- OpenSpec 和本 plan 可追溯记录 Gate A 批准、里程碑、依赖、风险、负责人、验收证据和下一检查点。
- 实际仓库研发只分配给现有资深后端工程师；Stage 2 在隔离 worktree active remediation，Stage 3 保持 `backlog` 串行停放，没有新建 specialist。
- 显式记录“无前端范围”及依据，没有向资深前端工程师创建无效任务。
- 八项 NO-GO 阻塞均有修复位置、负例、离线命令和输出摘要，并绑定新的完整 clean HEAD；rejected HEAD 不作为 Stage 3 基线。
- 部署入口在网络、构建或写操作前，以最终合并后的 typed Helm values 校验授权、`enabled`、`suspend`、业务时区和目标 release/namespace；离线非法输入不得读取 env、发起 SSH 或调用目标 API。
- server-side dry-run 仅允许目标 namespace 中精确的 suspended CronJob 和必要 verb；实际 suspended release 拒绝 dirty/drift 并复用冻结镜像；Gate C 仅接受审阅后的 `spec.suspend` 单字段差异。
- 本轮没有生产访问、真实 provider 调用、部署、备份、CronJob/Job 创建或激活；OpenSpec strict、docs-contract、focused tests 与 `git diff --check` 的实际结果如实记录。

## Completion Evidence（完成证据）

- 2026-09-08：已读取 parent approval thread、OpenSpec proposal/spec/design/tasks、active plan index、architecture、runbook、repository guide、status 和工作树状态。
- 2026-09-08：Gate A approval evidence 已定位为 `GYT-45` 评论 `01a07e3a-141c-71ac-b30b-0f06cf0c4a8b` 与 `01a07e3d-5a77-7972-a9cd-360c9d41dc84`。
- 2026-09-08：已确认现有资深后端工程师 ID `032a9aa5-2728-4ae7-b707-4175a957bb9c`；无前端任务。
- 2026-09-08：已在 parent `GYT-45` 下创建 `GYT-47`（Stage 2 implementation，issue `01a07e48-7b5a-712b-b22b-dcd3c8b1ba17`）与 `GYT-48`（Stage 3 offline verification，issue `01a07e48-7bd4-7a56-b7a6-7f9322520306`），均分配给资深后端工程师并保持 `backlog`，未触发执行。
- 2026-09-08：`openspec validate enable-truenas-scheduled-market-collection --strict --json` 通过（1/1）；active plan 六个必需字段齐全；full docs-contract 通过（代码 5 / 文档 7 / plan 2）；`git diff --check` 通过。
- 2026-09-08：fast docs-contract 输出“无变更，跳过 diff 检查”（代码 0 / 文档 0 / plan 0）。由于当前规划文件未 staged、full 模式又基于 upstream 范围，这两次结果不能证明 shared dirty tree 是 clean implementation baseline；OpenSpec 1.2 保持未完成，须在 `GYT-47` 的 reviewed clean baseline 中重跑。
- 2026-09-08：GYT-47 已确认共享 worktree 保持不触碰；隔离 worktree 的 HEAD 为 `bb0de075c4336e6a4532b38f221b043d9859f590`（`docs: establish GYT-47 clean baseline`），branch 为 `agent/backend/gyt-47-scheduled-collection-clean-baseline`，工作树干净且没有重叠 active run。
- 2026-09-08：在该隔离 worktree 暂存 README、产品规格、architecture、runbooks、status 和本计划后，`python3 scripts/check-docs-contract.py --mode=fast` 通过（代码 0 / 文档 6 / plan 1）。文档明确 Dashboard 保持 Kubernetes 1.26+、native CronJob timezone 仅为 1.27+、revision 7 仅为待预检确认的报告值。
- 2026-09-08：Helm template 实现 `timezoneStrategy=native|controller`：native 仅接受 1.27+ 并输出 `spec.timeZone: Asia/Shanghai`；controller 仅接受 1.26、`Etc/UTC` 或 `Asia/Shanghai`、已声明时区证据及精确 16:30 上海映射，未证明 canary 时不能设置 `suspend=false`。unknown/native-1.26/missing-evidence/early/complex/mapping/canary 7 个非法 profile 均在 Helm render 前失败。
- 2026-09-08：新增 `values-scheduled-suspended.yaml`、`values-scheduled-active.yaml` 与 `values-scheduled-off.yaml`。固定离线 YAML 解析确认 native 1.27、controller 1.26 UTC/Shanghai、disabled/suspended/active/off matrix 正确，所有 CronJob 保持共享 image/PVC、non-root/read-only-rootfs/no-token、`Forbid`、`backoffLimit: 0` 与 `scheduled-refresh`；各 overlay 的非 CronJob manifests 与 baseline 完全一致。
- 2026-09-08：`bash -n scripts/deploy-truenas-k3s.sh`、`python3 -m py_compile tests/test_deployment_manifests.py`、`helm lint --strict deploy/helm/a-stock`、`kubectl kustomize deploy/k3s` 与 offline-render suspended/off 命令通过。系统 Python 无 `pytest`，且无法创建 venv（缺少 `ensurepip`），因此未运行 pytest runner；对应 Helm/YAML assertions 已由无 target 的固定离线命令执行。
- 2026-09-08：`openspec validate enable-truenas-scheduled-market-collection --strict --json` 通过（1/1）；`python3 scripts/check-docs-contract.py --mode=full` 通过（代码 0 / 文档 2 / plan 1）；`git diff --cached --check` 通过。diff 仅包含部署 chart/Kustomize/TrueNAS values/entry script、对应 tests、OpenSpec 和所需文档，不含 application API、provider、dataset、SQLite schema、frontend 或生产状态改动。
- 2026-09-08：reviewable Stage 2 implementation commit 为 `4b334051de43f09ef44fd2753f7b6a64510c5738`（`GYT-47: add scheduled collection compatibility`）；该独立 branch 已推送，未创建 PR，因为运行环境未安装 `gh` CLI。
- 2026-09-08：在 review-evidence commit 前再次运行 `python3 scripts/check-docs-contract.py --mode=full`，通过（代码 4 / 文档 8 / plan 2）；strict OpenSpec validation 仍通过（1/1）。
- 2026-09-08：独立审阅冻结 baseline `bb0de075c4336e6a4532b38f221b043d9859f590` 与 HEAD `5cc6e7f97e24a38c72adb84aa88b4cc693e9b969` 并给出 NO-GO；原 focused 证据不再构成 Stage 2 验收，必须修复后生成新的 clean HEAD 再审。
- 2026-09-08：Gate B/Gate C 推进授权已在评论 `01a07fcd-9140-7aa7-b05a-83485a7ed8c7` 记录；当前任务仍禁止生产访问和写操作，且授权不能提前满足 GYT-47 独立 GO、GYT-48、精确 Gate B packet 或 Gate C catch-up 选择。
- 2026-09-09：NO-GO #1 已关闭：native offline cron 解析使用局部 IFS、严格五字段检查和显式非零退出；非法 schedule 测试证明不会读取 env 或调用目标工具。
- 2026-09-09：NO-GO #2/#3 已关闭：Chart JSON schema 与 template 都要求四个调度字段为 boolean，并锁定 `marketEnvironment.timezone=Asia/Shanghai`；字符串 boolean 与非上海时区负例通过。
- 2026-09-09：NO-GO #4 已关闭：入口在 SSH/build/write 前检查 merged typed render；普通 deploy 只能是 disabled，调度模式按目标 state/authorization ref 拒绝，`GIT_UPDATE=true` 在任何目标或更新命令前失败。
- 2026-09-09：NO-GO #5 已关闭：server dry-run 只提取一个目标 release/namespace 的 `suspend=true` CronJob，只检查并使用 `create cronjobs.batch`，active overlay 在 target access 前失败。
- 2026-09-09：NO-GO #6 已关闭：actual release 要求 clean HEAD=upstream 与 chart/baseline/overlay/render hashes，使用本次只读 snapshot 消除 TOCTOU，比较 Helm record 与 API live state，严格绑定 Deployment→ReplicaSet→ready Pod、containerd tag 与 imageID digest，使用 `--atomic` 并执行写后 postcondition；Gate C 异常补偿暂停 exact CronJob。
- 2026-09-09：NO-GO #7 已关闭：`/version` 使用 JSON/SemVer 解析（含 prerelease+build），actual release/namespace/version 贯穿 render、target read 和 write；binding hashes 输出为单行日志。
- 2026-09-09：NO-GO #8 已关闭：status/plan/product/architecture/runbook/OpenSpec 统一为 progression/read-only permission、frozen packet 后 exact Gate B action authorization、Gate B evidence 后 exact Gate C operation authorization；删除裸 active patch/Job 与未知状态 Helm 命令。
- 2026-09-09：Kustomize base 已移除 CronJob；`deploy/k3s-native-scheduled/` 由 `scripts/render-k3s.py` 在 kubectl 调用前强制 Kubernetes 1.27+。1.26 fake kubectl 零调用负例与 1.27 正例通过。
- 2026-09-09：focused deployment/guard/validator suite `63 passed`；全库 `204 passed, 2 warnings`（现有 FastAPI/Starlette deprecation）；`bash -n`、Python `py_compile`、Helm 1.26 suspended lint、Kustomize base/native render、OpenSpec strict 1/1、docs-contract full（代码 4 / 文档 8 / plan 2）及 `git diff --check` 通过。
- 2026-09-09：所有验证均为本地固定 values、fake kubectl/ssh/containerd/provider 与离线 render；没有访问 TrueNAS/生产 Kubernetes、调用真实 provider、读取生产 SQLite/PVC、执行 server dry-run 或生产写操作。
- 2026-09-09：首轮 remediation candidate `e6ae0c09be62b483b3e5f45a122acbb8f4c2fc3e` 已提交并推送，工作树 clean 且 `HEAD == @{upstream}`；baseline diff 不含 `src/`、`apps/`、provider、dataset 或 SQLite schema。三路独立只读审阅仍给出 NO-GO：非法 SemVer 可到达 kubectl/target path，Gate C 未强制 1800 秒 missed-schedule window，Helm 成功后的部分读取/信号异常未统一补偿暂停，runbook 仍有裸写命令且事实源状态落后。
- 2026-09-09：successor 修复使用严格 SemVer 2.0.0 并按 precedence 拒绝 `1.27.0-rc.1` 低于 stable 1.27.0；malformed/core 前导零/numeric prerelease 前导零负例均证明 kubectl/target 零调用。Gate C validator 从 active packet 计算 weekday previous/next trigger、1800 秒 deadline、UTC/上海审计时间和固定 300 秒 safety buffer；两种 catch-up mode 的 weekday/weekend/边界正负例通过。
- 2026-09-09：activation 写前建立 release-derived exact CronJob fail-safe guard；Helm failure、Helm success 后 live capture/read/compare/final get failure 与 HUP/INT/TERM 都统一在 EXIT 路径补偿 `suspend=true`，成功完成全部 postcondition 后才清 guard。combined deployment/validator/guard suite `104 passed`；独立全库复跑 `204 passed, 2 warnings`。
- 2026-09-09：加入 successor 负例后的主线全库复跑为 `244 passed, 1 failed, 2 warnings`；唯一失败是 baseline-identical 的 `test_persistent_cold_requests_share_one_cross_service_refresh` 冷加载 TOCTOU，`src/market_environment/` 与该测试均无本 issue diff。独立审阅已确认竞态发生在第二请求“读缺失”与“获取 lease”之间，并曾在相同 deployment candidate 上跑出 `204 passed`；本任务不以重试或放宽断言掩盖，也不越界修改应用层。
- 2026-09-09：candidate `58f5c4a986387ddeeb2f2f352f7fc9e3f0a775b6` 已提交、推送且 clean/upstream 一致，但最终复审仍为 NO-GO：Helm template 的 `>=1.27.0-0` 接受 native `1.27.0-rc.1`，且早期通过的 activation-window decision 可能在 live/read/render 工作期间老化，必须在 Helm write 前重验。其余补偿、strict parser 与原八项边界未发现新阻塞。
- 2026-09-09：第二轮 successor remediation 已把 Helm native comparator 收紧为 `>=1.27.0`，并将 raw `--kube-version` 传入 scheduling packet validator；严格 SemVer precedence 使 `1.27.0-rc.1` 在 env、SSH、kubectl 或目标 API 前失败。
- 2026-09-09：Gate C 在早期 preflight 后，于 live/image/diff/re-render/hash 检查完成且 Helm write 尚未开始时再次校验 activation window；第二次校验失败的负例证明 Helm write 与 compensation patch 均为零，Helm failure 和 final CronJob get failure 负例各证明仅执行一次 exact `suspend=true` compensation。
- 2026-09-09：更新后的 scheduling packet/deployment guard/deployment manifest focused suite `117 passed`；`bash -n`、Python `py_compile`、Helm 1.26 suspended strict lint 和 `git diff --check` 通过。完整门禁与 successor SHA 待本轮冻结步骤记录。
- 2026-09-09：候选冻结前门禁通过：OpenSpec strict 1/1、docs-contract fast（代码 3 / 文档 4 / plan 1）与 full（代码 8 / 文档 9 / plan 2）、Helm 1.26 controller suspended lint/render、Helm 1.27 native render、Kustomize Dashboard base/native 1.27 render。Helm 3.21.4 会把 `--kube-version 1.27.0-rc.1` 规范化为 stable capabilities，因此受支持部署入口额外把 raw 版本交给 strict packet validator；对应 focused 负例已证明在 target access 前拒绝。
- 2026-09-09：全库复跑为 `257 passed, 1 failed, 2 warnings`；唯一失败仍是 baseline-identical 的 `tests/test_market_environment_service.py::test_persistent_cold_requests_share_one_cross_service_refresh` 冷加载 TOCTOU，冻结 baseline 到候选的 diff 不含 `src/market_environment/` 或该测试。本 issue 保留该真实结果，不重试、放宽断言或越界修改应用层。
- 2026-09-09：successor implementation candidate `5672c2a147e8975ac0de218fa0605ce83882aadf` 已提交并推送；工作树 clean、`HEAD == @{upstream}`，baseline diff 不含 `src/`、`apps/`、`trading-rules/`、provider、dataset 或 SQLite schema。
- 2026-09-09：三路独立只读复审均以 baseline `bb0de075c4336e6a4532b38f221b043d9859f590` 和 exact candidate `5672c2a147e8975ac0de218fa0605ce83882aadf` 为对象并给出 GO，无 blocking finding；审阅分别覆盖八项 release fail-safe、SemVer/activation-window/compensation 测试严谨性、OpenSpec/docs/scope 一致性。独立验证包括 focused `117 passed`，另一路全库 `258 passed, 2 warnings`，确认上述冷加载竞态为非确定性 baseline defect。

## Remaining Gaps（剩余缺口）

- 当前共享 worktree 不是 clean implementation baseline，但 Stage 2 已在记录的隔离 worktree 中执行；不得把共享树的改动带入本 issue。
- Stage 2 仓库修复已在 candidate `5672c2a147e8975ac0de218fa0605ce83882aadf` 完成并取得三路独立 GO；GYT-47 尚待人工验收，未因此自动推进 GYT-48。
- baseline 的跨 service 冷加载存在“旧 missing 观察后晚到 worker 再取 lease”的应用层 TOCTOU；它不由 GYT-47 引入，需另行修复并用确定性 Event 栅栏测试，不影响本 issue 的 deployment-only diff 归属。
- GYT-48 的 Stage 3 仍为 backlog；只有新的完整 clean HEAD 取得独立 GO 且 GYT-47 被接受后才可提升。
- controller runtime timezone、canary、production revision、image digest、PVC identity、备份目标、验证日期和 stop thresholds 仍是后续 Gate B 精确 packet 中待采集或冻结的事实；推进授权不能替代这些证据。

## Next Step（下一步）

将 GYT-47 置为 `in_review` 等待人工验收；只有 parent owner 确认该 Stage 2 交付并将 GYT-47 置为 terminal 后，才可提升 GYT-48。当前不得执行生产 preflight、server-side dry-run、canary、Job、备份、部署或解除暂停。
