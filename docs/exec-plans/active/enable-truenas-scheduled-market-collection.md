# TrueNAS k3s 1.26 盘后定时采集 Gate A 实施计划

## Stage（阶段）

Gate A / Stage 4 local-main-first 整合与独立复验。GYT-47 的通用发布修复和 GYT-48 的已批准离线证据已在最新主线基线上重放；GYT-52 仍须对新的精确主线 SHA 独立验收。Gate B/Gate C 的推进授权不授权本任务访问生产、调用真实 provider，或绕过重新验证及后续精确发布门禁。

## Status（状态）

`local-main-integrated-awaiting-stage-4-revalidation`：以最新 `origin/main=b6d3942a7cf75d51b9c6efebcef71b7317931fb6` 为基线，按原顺序重放 `99a625a..4a2a617` 的 23 个 GYT-47/GYT-48 提交，明确排除 GYT-21 提交 `99a625a38bff8bdbfc421fb21176565b8c9d3028`。pre-evidence integration commit `c6dd6b799dad3d8a07e17bd60f004d7ba0d5fd49` 已 fast-forward 到本地 `main`，focused `243 passed`、fake-provider `7 passed, 10 deselected` 及纯离线 Helm/Kustomize/OpenSpec/docs 门禁通过；该提交的首次全量为 `384 passed, 2 warnings`。事实源提交 `296f62aabadafe0f3aff9197f5089e819d723231` 上的最终全量复跑保留两项 baseline-identical 失败（`382 passed, 2 failed, 2 warnings`），未重试掩盖。GYT-47 和已批准的 GYT-48 Stage 3 交付已进入本地主线；GYT-52 必须对最终推送 SHA 重验，Gate B/Gate C 保持阻塞，未访问生产或真实 provider。

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
- 将 Helm 默认值和 README、TrueNAS 教程、runbook 的通用 install/upgrade/rollback 固定为 scheduled collection disabled；禁止 `--reuse-values` 和裸 `helm rollback` 继承或恢复未审阅的 active CronJob 状态。
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
| Stage 2 / D2-D3 | Helm/TrueNAS/部署入口实现（`GYT-47`） | 资深后端工程师 | 文档先行门禁通过 | tasks 2.1-2.7；focused render/deployment tests；无应用/前端/生产 diff | approved range integrated into local `main` from `b6d3942` |
| Stage 3 / D4 | 离线全矩阵与评审包（`GYT-48`） | 资深后端工程师 | `GYT-47` reviewed | tasks 3.1-3.7；Helm/OpenSpec/docs/full test/diff gate；clean reviewable diff | accepted delivery integrated; rebased offline gates pass |
| Stage 4 / D5 | 独立 Gate A 验收（`GYT-52`） | 独立测试工程师 | final pushed `main` contains GYT-47/GYT-48 | 通用发布负例、全量离线门禁、exact clean HEAD | pending exact-main revalidation |
| Gate B | 生产验证 | 未分配 | GYT-47 independent GO + Stage 3 accepted + exact packet review + exact action authorization | tasks 4.x-5.x 指定证据 | progression/read-only permission recorded; blocked by prerequisites |
| Gate C | 周期激活 | 未分配 | Gate B evidence accepted + catch-up choice + exact operation authorization | suspend-only live diff + next trigger evidence | progression authorized; blocked by prerequisites |

## Task Breakdown And Dependencies（任务拆分与依赖）

1. Stage 1：项目经理记录 Gate A、工件边界、风险、计划与研发分配；不改代码。
2. Stage 2 / `GYT-47`：后端先建立 clean baseline 并完成 OpenSpec 1.3 文档对齐，再实现 2.1-2.7。文档未通过 staged fast gate 时禁止代码改动。
3. Stage 3 / `GYT-48`：后端在 `GYT-47` 完成并审阅后执行 3.1-3.7 离线验证；不得与 Stage 2 并行启动，避免测试证据绑定未冻结实现。
4. Gate B/Gate C：推进授权和后续 read-only permission 已记录，但本轮不执行生产动作；只有 GYT-47 独立 GO、GYT-48 验收、read-only preflight、精确 packet 审核及覆盖 exact actions 的 Gate B authorization 依次成立后才能进入写类 Gate B，Gate C 还需接受 Gate B 证据并形成明确 catch-up 选择的最终 operation authorization。

## Risks（风险）

| 风险 | 影响 | 缓解 / 升级条件 | Owner |
|---|---|---|---|
| 当前 shared tree 含大量重叠 dirty files | diff 无法归属，gate 可能只验证旧提交 | Stage 2 只在已记录的隔离 branch/worktree 活跃修复；禁止 reset/stash 或带入 shared tree 改动 | PM + Backend |
| 现有 README/docs 对 1.26/1.27、revision 6/7 和直接 unsuspend 的表述冲突 | 实施依据不一致 | Stage 2 完成 OpenSpec 1.3 remediation；revision 7 仅记为 issue 报告，待前置验收后使用已记录 permission 做只读预检验证 | Backend |
| canary 证据如何进入 fail-closed 校验未定义为具体配置契约 | 可能需要扩大批准设计 | 先按既有人工 gate 和 suspended 边界实现；若必须新增外部配置/API 字段，停止并提交架构差异复审 | Backend + Architect |
| Gate B 默认字段 allowlist、备份方法/空间阈值和 stop thresholds 尚未量化 | 后续 GO/NO-GO 不可重复判定 | 在 Gate B 请求包中先定义；任何生产动作前必须审核，Gate A 不代填生产事实 | Release owner |
| 误将 backlog 提升或把推进授权解释为跳过门禁 | 越权生产动作被触发 | Stage 3 需 Stage 2 independent GO；Gate B/C 即使获推进授权也必须逐项满足精确 packet 和证据门禁 | PM |
| 通用 Helm install/upgrade/rollback/uninstall 继承、恢复或移除 release | 在 Gate B/Gate C 外创建周期任务，或绕过受控退役边界；`--atomic` 失败可自动恢复旧 active revision | 通用写操作只通过受支持入口；按 release-derived exact name 读取 live CronJob，不依赖可漂移 label；写前同时证明 Helm stored manifest 与 live release 的 CronJob 已 absent/off；使用已验证只读 chart packet完成 Helm write；失败、信号和写后读取异常均证明 CronJob 仍 absent/suspended；禁止 `--reuse-values`、裸 `helm rollback`、原始 `helm uninstall` 和文档中的原始 Helm 写命令 | Backend + Release owner |

## Acceptance（验收）

- OpenSpec 和本 plan 可追溯记录 Gate A 批准、里程碑、依赖、风险、负责人、验收证据和下一检查点。
- 实际仓库研发只分配给现有资深后端工程师，没有新建 specialist。GYT-47 remediation 与 GYT-48 已批准 Stage 3 提交均已在隔离 worktree 中重放到最新 `origin/main` 基线并 fast-forward 进入本地 `main`；GYT-21 与其他 issue 的提交未进入该 23-commit 范围。新的完整主线 SHA 仍须由 GYT-52 独立复验。
- 显式记录“无前端范围”及依据，没有向资深前端工程师创建无效任务。
- 八项 NO-GO 阻塞均有修复位置、负例、离线命令和输出摘要，并绑定新的完整 clean HEAD；rejected HEAD 不作为 Stage 3 基线。
- 部署入口在网络、构建或写操作前，以最终合并后的 typed Helm values 校验授权、`enabled`、`suspend`、业务时区和目标 release/namespace；离线非法输入不得读取 env、发起 SSH 或调用目标 API。
- server-side dry-run 仅允许目标 namespace 中精确的 suspended CronJob 和必要 verb；实际 suspended release 拒绝 dirty/drift 并复用冻结镜像；Gate C 仅接受审阅后的 `spec.suspend` 单字段差异。
- Helm 无覆盖默认 render 不包含 CronJob；README、TrueNAS 教程和 runbook 的通用发布只调用受支持的 fail-closed 入口，不包含原始 Helm 写命令、`--reuse-values` 或裸 `helm rollback`。通用入口在 Helm stored manifest 与 live release 已 off/absent 时才允许写入；已 active/suspended 的 release 必须先走受审 `--disable-schedule`。只有 exact Gate B packet 与 Gate C 入口可表达 suspended/active scheduling state。
- 文档命令审计覆盖 CommonMark 更长 closing fence 与 info attrs、`sudo -n`/`env`/`command` 包装、Helm 全局参数前置、独立 install/uninstall/rollback、续行、pipe/条件语法、shell 分隔符与 inline comment；安全关键参数必须位于实际执行 token 中，注释文字不能满足断言，归档部署设计也纳入回归范围。
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
- 2026-09-09：GYT-47 当时被置为 terminal `done`；其证据提交形成 Stage 3 exact clean baseline `dd1277b86d04ed3a5d2cabe41c558d6de9049c09`，该 SHA 与远端 Stage 2 分支一致且 worktree clean。该状态与验收后来被 Stage 4 NO-GO 作废，GYT-47 已重新打开。
- 2026-09-09：GYT-48 已从该 SHA 建立独立分支/worktree `agent/backend/gyt-48-scheduled-collection-offline-verification`；OpenSpec apply 状态为 `ready`（8/30 完成），本阶段仅处理 3.1-3.5。
- 2026-09-09：OpenSpec 3.1/3.2 已补齐自动化覆盖：Helm 3 profile x 3 state render matrix 固化 controller-UTC 1.26、controller-Shanghai 1.26 与 native 1.27 的 disabled/suspended/active 精确 cron/timeZone；非法表逐项覆盖 earlier/equal、list/range/step/multiple-time、策略/版本/时区/持久化/结算/映射/canary，并校验精确失败消息。
- 2026-09-09：Kustomize、Helm default 与 TrueNAS suspended/active manifests 显式锁定共享 Dashboard image/PVC/snapshot path、non-root/read-only-rootfs/no-token/cap-drop、`Forbid`、`backoffLimit: 0`、1800/3600 deadlines、3/3 history 和完整 `python -m src.market_environment.cli snapshots scheduled-refresh` 命令；`PYTHONDONTWRITEBYTECODE=1 /home/gyt/a-stock/.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_deployment_manifests.py` 为 `57 passed`。
- 2026-09-09：OpenSpec 3.3 固定 fake-provider 回归命令 `PYTHONDONTWRITEBYTECODE=1 /home/gyt/a-stock/.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_market_environment_collection.py -k scheduled_refresh` 为 `7 passed, 10 deselected`，覆盖 success/partial/failed/skipped/settlement/lease-conflict；provider 为测试内 fixture，SQLite 仅使用 `tmp_path`，未访问真实 provider、生产 SQLite/PVC 或 Kubernetes。
- 2026-09-09：deployment/validator/guard 专项 `138 passed`；全库固定离线测试单次运行 `279 passed, 2 warnings`，warnings 为既有 FastAPI/Starlette deprecation。`bash -n scripts/deploy-truenas-k3s.sh` 与调度脚本/测试 `py_compile` 通过。
- 2026-09-09：Helm 3.21.4 对 native 1.27、controller-UTC 1.26 suspended/active/off、controller-Shanghai 1.26 均完成 `lint --strict`（每项 `1 chart(s) linted, 0 failed`）和 `template`（exit 0）；`kubectl kustomize deploy/k3s` 与受门禁的 native `scripts/render-k3s.py --kube-version 1.27.0` 均 exit 0。裸 Helm 会规范化 prerelease capabilities，native prerelease 的 fail-closed 证据只取受支持部署入口及其自动化 guard，不把裸 Helm render 误记为边界证明。
- 2026-09-09：proposal/design/tasks、`docs/status.md`、runbook 验证矩阵、active plan index 当时同步了 GYT-47 terminal 与 GYT-48 Stage 3 状态；这些历史状态后来被 Stage 4 NO-GO 作废。architecture、repository guide 和 capability spec 经审计无契约变化，因此未做无关修改。
- 2026-09-09：GYT-48 review candidate 为 `552fc4b4aa883ea2e482877de33e42fb8a33d641`。在该提交上，`openspec validate enable-truenas-scheduled-market-collection --strict --json` 为 1/1，`PYTHONDONTWRITEBYTECODE=1 python3 scripts/check-docs-contract.py --mode=full` 通过（代码 1 / 文档 4 / plan 1），native/controller Helm lint/template 与 `git diff --check dd1277b86d04ed3a5d2cabe41c558d6de9049c09..HEAD` 均通过。环境没有 `python` 命令（原写法 exit 127），因此使用仓库支持的 `python3` 执行同一 gate 脚本。
- 2026-09-09：`git diff --name-status dd1277b86d04ed3a5d2cabe41c558d6de9049c09..552fc4b4aa883ea2e482877de33e42fb8a33d641` 仅包含 `tests/test_deployment_manifests.py`、OpenSpec planning artifacts、active plan/index、runbook 与 status 共 8 个文件；`git diff --name-only bb0de075c4336e6a4532b38f221b043d9859f590..552fc4b4aa883ea2e482877de33e42fb8a33d641 -- src apps trading-rules` 为空，不含 application API、provider、dataset、SQLite schema、frontend 或生产状态变更。
- 2026-09-09：review branch `agent/backend/gyt-48-scheduled-collection-offline-verification` 已推送至 `origin`，包含计划先行提交 `200cae2`、测试/文档候选 `552fc4b` 与离线 gate 证据提交 `95af911`。环境未安装 `gh`，因此未创建 PR；GitHub 已返回该分支的 pull/new 评审入口。
- 2026-09-09：两路独立只读复审最终均为 GO：测试复审确认 3 x 3 matrix、exact template/schema failure messages 与 Kustomize/Helm/TrueNAS 不变量完整；文档复审确认 GYT-47/GYT-48 状态、3.1-3.4 证据和 Gate B/Gate C 权限边界一致。
- 2026-09-09：本阶段未访问 TrueNAS/生产 Kubernetes，未调用真实 provider，未读取生产 SQLite/PVC，未运行 server-side dry-run，未创建 canary/CronJob/Job、备份、release 或解除暂停；后续任何生产动作仍受 actual-version packet review 与 exact Gate B/Gate C 门禁约束。
- 2026-09-09：GYT-52 对冻结 HEAD `b231ef4507e4003d2a5d3fe3a25ec1d659d7cb75` 给出 Stage 4 NO-GO：Chart 默认 `enabled=true`，README 与 TrueNAS 教程仍提供 `--reuse-values` 和裸 `helm rollback`，可在 Gate B/Gate C 外继承或恢复 active CronJob。GYT-47 已重新打开，GYT-48/GYT-52 回到 `backlog`；本次返工以该 clean HEAD 为精确 baseline。
- 2026-09-09：返工计划先行更新并两次通过 staged fast docs-contract：仅 active plan 时为代码 0 / 文档 1 / plan 1；同步 README、产品规格、architecture、runbook、status 与 OpenSpec 后为代码 0 / 文档 7 / plan 1。文档先于 Helm 和测试文件修改。
- 2026-09-09：Chart 默认改为 `enabled=false`、`suspend=true`，TrueNAS baseline/off overlay 显式锁定相同布尔值。README、TrueNAS 教程和 runbook 的通用 install/upgrade/application rollback 均重交完整环境 values、显式 disabled/suspended 并使用 atomic upgrade；不再提供 `--reuse-values` 或裸 `helm rollback`，历史 revision 仅用于审计。
- 2026-09-09：部署文档测试现在解析 README、TrueNAS 教程和 runbook 的 fenced Bash 多行命令，逐条拒绝 release-value inheritance 与 historical rollback，并验证完整 values、两个安全覆盖和 atomic write；另覆盖 TrueNAS YAML 示例、默认无 CronJob、baseline/off 双布尔值及 prior active values 被通用 off 覆盖。
- 2026-09-09：默认 Helm 1.27 render 为 Deployment/Service/PVC/Ingress 且 CronJob 0 个；显式 1.26 suspended/active overlay 各为 CronJob 1 个；active values 加通用 off 覆盖后 CronJob 0 个。Helm strict lint、Kustomize base/native render、Bash syntax、OpenSpec strict 1/1、docs-contract full（代码 8 / 文档 9 / plan 2）和 `git diff --check` 均通过。
- 2026-09-09：deployment/validator/guard focused suite `144 passed`；全库固定离线测试单次运行 `285 passed, 2 warnings`，warnings 为既有 FastAPI/Starlette deprecation。测试未访问 TrueNAS、生产 Kubernetes、真实 provider 或生产 SQLite/PVC。
- 2026-09-09：首轮 Stage 4 candidate `9478ff0fd946993ae582b75dbb3287cf3a818aea` 已提交、推送且 clean/upstream 一致，但三路独立复审均为 NO-GO。发布安全复审证明原始 `helm upgrade --atomic` 在旧 active revision 存在时可因普通应用发布失败自动回滚为 active；规格复审发现归档 change 的 `design.md` 仍给出可执行 `helm rollback`；测试复审确认 fence 解析未统一覆盖 `sudo`、standalone install、shell 分隔符、inline comment 与合成负例。该 SHA 不得作为最终证据或后续 Stage 3 baseline。
- 2026-09-09：第二轮 successor 将通用应用发布统一收口到 `scripts/deploy-truenas-k3s.sh`。普通 deploy 与受审 scheduling modes 共用 release lock，在构建/目标写入前和 Helm write 前分别检查 Helm stored manifest 与 live CronJob；active/suspended 均要求先完成受审 `--disable-schedule`。从 Helm write 到 rollout、endpoint 和 post-read 完成前保持 failure guard；异常时将 validator 绑定的意外 active CronJob 精确补偿为 suspended 并重读验证 absent/suspended，无法证明则保持 uncertain/NO-GO。
- 2026-09-09：README、TrueNAS guide 与 runbook 的生产写示例仅调用受支持入口，不再包含 raw Helm install/upgrade/rollback、`values-production.yaml` 或 `--reuse-values`；归档 manual-collection design 的历史 rollback 指令已废止。fenced shell 审计使用 token 化解析并覆盖 `bash/sh/shell`、同长度三字符以上 backtick/tilde fence、续行、inline comment、`sudo helm`、standalone install、shell 分隔符与后置参数覆盖。
- 2026-09-09：generic lifecycle subset `12 passed`；deployment/validator/guard focused suite `165 passed`；全库固定离线测试单次运行 `306 passed, 2 warnings`，warnings 为既有 FastAPI/Starlette deprecation。Helm default/suspended/active/active-plus-off CronJob 计数分别为 `0/1/1/0`；Helm strict lint、Kustomize base/native render、Bash/Python syntax、OpenSpec strict 1/1 与 `git diff --check` 均通过。
- 2026-09-09：第二轮 successor candidate `8ef80b7ea42ce7e72ea3262f1e1d5390e2ed0213` 已提交、推送且 clean/upstream 一致，但三路 exact-SHA 独立复审均为 NO-GO。文档复审发现 TrueNAS guide 仍有原始 `helm uninstall`；发布安全复审证明 live guard 的 instance-label selector 会漏掉 label drift 的 exact CronJob，且普通发布在 render 后仍从可变 repo chart 执行 Helm write；测试复审证明命令审计会漏掉合法更长 closing fence、`sudo -n`、Helm 全局参数前置、注释续行及 archive 回归。该 SHA 不得作为最终证据或后续 Stage 3 baseline。
- 2026-09-09：第三轮 successor 从 frozen chart render 取得 release-derived exact CronJob name，以 `kubectl get cronjob <exact-name> --ignore-not-found` 查询 live state；label 缺失不再被 selector 隐藏，而是由 identity validation fail closed。普通 deploy 在网络前冻结 chart/input values/overlay，最终 values render 后固定 SHA-256，Helm write 前从同一只读 packet 重渲染并比对，Helm 不再读取可变 repo chart。
- 2026-09-09：TrueNAS guide 已移除 raw uninstall 可执行块并明确独立退役边界。命令审计纳入受影响 archive，支持 CommonMark 更长 closing fence 与 info attrs，区分 comment 内外续行，并识别 `sudo -n`、`env`、`command`、condition/pipe、Helm global flags、install/upgrade/rollback/uninstall；合成审计用例 `21 passed`。
- 2026-09-09：新增 label-drift、source-chart drift 与首次安装 live active/suspended 负例后，generic lifecycle subset `16 passed`；deployment/validator/guard focused suite `178 passed`；全库固定离线测试 `319 passed, 2 warnings`，warnings 为既有 FastAPI/Starlette deprecation。Helm strict lint/default/controller suspended/controller active renders、Kustomize base/native render、Bash/Python syntax、OpenSpec strict 1/1 与 `git diff --check` 均通过。
- 2026-09-09：第三轮 candidate 提交前 `PYTHONDONTWRITEBYTECODE=1 python3 scripts/check-docs-contract.py --mode=full` 通过（代码 8 / 文档 10 / plan 2）；`git diff --cached --check` 与 `git diff --check` 均通过。相对 Stage 4 baseline 的 working-tree scope 检查在 `src/`、`apps/`、`trading-rules/` 下输出为空，不含应用 API、provider、dataset、SQLite schema、前端或生产状态变更。
- 2026-09-09：第三轮 candidate `3c4d2dc056b9f70e3966407fda18f976841475db` 已提交、推送且 clean/upstream 一致。发布安全复审为 GO，并额外验证 Kubernetes 1.26 `nameOverride` 与 1.27 `fullnameOverride` 的 exact name；规格/文档与测试严谨性复审为 NO-GO。事实源仍有未标记为历史且已被 Stage 4 作废的 GYT-47 terminal/Stage 3 completed 表述；命令审计仍漏掉 `--kube-tls-server-name` 等未列举 Helm value option、uninstall aliases `del/delete/un`、`exec`/substitution/brace 包装、EOF 隐式闭合和 list/blockquote 内 fence。该 SHA 不得作为最终证据或后续 Stage 3 baseline。
- 2026-09-09：第四轮已修正 design/plan/proposal/tasks 中失效的 GYT-47 terminal、Stage 3 completed 与 third-successor 表述；历史 evidence 保留 SHA，但明确已被 Stage 4 NO-GO 作废，当前 GYT-47 reopened、GYT-48/GYT-52 backlog。
- 2026-09-09：命令审计改用 `markdown-it-py` CommonMark token 与 `bashlex` Bash AST，不再用有限 fence/shell token 近似解析。负例覆盖已知与未来未知 Helm value option、`del/delete/un`、`helm test` hooks、`exec`/absolute path/`sudo --user`、`env -S/--split-string`、`bash/sh -c` 及 clustered `-cu`、任意命名动态 Helm executable、`xargs helm` stdin argv、command/backtick substitution、brace/subshell、EOF 隐式闭合、ordered-list 与 nested-blockquote fence；对照用例保证 read action、help/lookup、wrapper option value、shell `-c` 定位参数、quoted literal、非 shell fence 与 indented code 不误报，不可解析 shell fence fail closed。实际指南中的尖括号占位符已引用为合法 shell；最终审计 subset `67 passed`。
- 2026-09-09：新增解析依赖经 `uv pip check` 验证 52 个包兼容；最终 deployment/validator/guard focused suite `224 passed`，全库固定离线测试 `365 passed, 2 warnings`，warnings 仍为既有 FastAPI/Starlette deprecation。Bash/Python syntax、Helm default/controller suspended/controller active strict lint、native render、Kustomize base/native render、OpenSpec strict 1/1 与 `git diff --check` 均通过。
- 2026-09-09：第四轮 candidate 提交前 staged fast docs-contract 通过（代码 1 / 文档 4 / plan 1），full docs-contract 通过（代码 8 / 文档 10 / plan 2）；`git diff --cached --check` 通过，Stage 4 baseline 到工作树在 `src/`、`apps/`、`trading-rules/` 下差异为空。
- 2026-09-09：中间 candidate `0ab44479923ca461c0fe000865f26cc56a7ef2be` 曾提交、推送且 clean/upstream 一致，但本地对抗审查在正式复审完成前发现未知 Helm option 的值可伪装为 read action 并遮蔽后续 write action；三路复审已立即中止。未知 Helm 与 wrapper 前置 option 现在一律产生明确审计 violation，该 SHA 不作为最终证据。
- 2026-09-09：candidate `437b03989ddf279757c7c5e92580493c65eca62d` 已提交、推送且 clean/upstream 一致，但测试复审为 NO-GO，其余两路随即中止：`--help=false` 被误当作纯帮助，`env -S/--split-string` 与 `bash/sh -c` 可执行字符串未递归审计，未知 `nohup` wrapper 也可跳过。当前修复只让 bare/true help 停止 action 解析，将 split-string 与 shell `-c/-lc` 内容递归交给 Bash AST，并对仍含 exact Helm write 的未知 wrapper fail closed；该 SHA 不作为最终证据。
- 2026-09-09：candidate `18062563728da8409cac9c38d5238286ece79370` 已提交、推送且 clean/upstream 一致；文档复审确认此前六处 stale terminal/completed finding 均已关闭，但因 `docs/status.md` 三处仍把第三 successor 与 `178/319` 写为当前证据而给出 NO-GO，其余两路随即中止。当前已将第三 candidate 历史化、同步第四 successor 的 `214/355` 证据与新检查点；该 SHA 不作为最终证据。
- 2026-09-09：candidate `f3fb0203f7bd97e434836ef9bfe209b31720e625` 已提交、推送且 clean/upstream 一致；文档复审为 GO，但测试复审发现 `bash -cu 'helm rollback ...'` 与 `sh -cu 'helm uninstall ...'` 会执行却逃过审计，随后的本地对抗检查还确认 `${HELM_BINARY:-helm} rollback ...` 动态 executable 可绕过，发布复审因此中止。当前解析会把任意包含 `c` 的短 `bash/sh` option cluster 的下一 argv 作为 command string 递归审计，并对含 Helm expansion 的动态 executable fail closed；该 SHA 不作为最终证据。
- 2026-09-09：candidate `09e29c59bee3bce2720b14d0636281a186577840` 已提交、推送且 clean/upstream 一致；文档复审为 GO，测试与发布安全复审为 NO-GO。`CMD=helm; $CMD rollback ...` 可绕过基于变量名含 `helm` 的动态 executable 启发式，`bash -c COMMAND [ARG...]` 的后续定位参数会被误解析为额外 command string，`printf 'uninstall ...' | xargs helm` 可从 stdin 注入写 action，且 `helm test` 会创建 hook 资源却仍被归为 read action。当前返工要求任意动态 executable 加 Helm write action fail closed、shell `-c` 只消费一个 command string、`xargs` 不得动态构造 Helm argv，并将 `helm test` 归为禁止的 release 写操作；该 SHA 不作为最终证据。
- 2026-09-09：candidate `b16785c815081981f9df2dd9fbfcac88d7a0a7bd` 已提交、推送且 clean/upstream 一致；文档复审为 GO，测试与发布安全复审为 NO-GO。`ACTION=rollback; helm $ACTION ...`、`${ACTION}` 与 `$(printf uninstall)` action substitution 仍返回无 violation；`xargs echo helm` 和 `xargs -a helm echo safe` 又会把 data/option value 误判为 executor。后续预候选审查进一步证明 wrapper allowlist 会在 `ionice`/`watch` 等未列举 executable 上继续漏检，并在 wrapper 数据参数上误报；当前返工改为解析 xargs options 后拒绝任意显式 utility。该 SHA 不作为最终证据。
- 2026-09-09：replacement 工作树将 xargs required-value 与 optional-value options 分开解析，`--eof`、`--max-lines`、`--replace` 未带 `=` 时不会吞掉后续 utility；任意显式 utility 均 fail closed，仅无 utility 的 default echo 允许。两路独立脏树对抗预检均为 GO；command-audit subset `82 passed`，deployment/guard focused suite `191 passed`，fake-provider scheduled-refresh `7 passed, 10 deselected`，全库固定离线测试 `384 passed, 2 warnings`。`uv pip check` 确认 52 个包兼容；Bash/Python syntax、五组 native/controller/off Helm strict lint/template、Kustomize base/native render、OpenSpec strict 1/1、staged fast docs-contract（代码 1 / 文档 2 / plan 1）、full docs-contract（代码 8 / 文档 10 / plan 2）、scope 与 `git diff --check` 均通过。该证据已绑定下述 exact clean candidate。
- 2026-09-09：fourth-successor exact candidate `0cd9b31fc3f3a35dc404f6bafe8af8f87dc66ca2` 已提交、推送，`HEAD == @{upstream}` 且 worktree clean。文档/规格、测试严谨性和发布安全三路只读复审均对 baseline `b231ef4507e4003d2a5d3fe3a25ec1d659d7cb75` 到该 candidate 给出 GO，无 blocking finding；两路独立复跑 deployment/guard 均为 `191 passed`，full docs-contract 为代码 8 / 文档 10 / plan 2，OpenSpec strict 为 1/1。文档审阅者额外全库复跑为 `383 passed, 1 failed, 2 warnings`；唯一失败是本 plan 已记录且 baseline-identical 的跨 service 冷加载 TOCTOU，candidate 未修改 `src/` 或该测试，作为残余风险保留，不以重试或放宽断言掩盖。
- 2026-09-09：三路 GO 后已同步 proposal、design、tasks、active plan 与 `docs/status.md` 的当前状态；evidence-only staged fast docs-contract 通过（代码 0 / 文档 2 / plan 1），full docs-contract 通过（代码 8 / 文档 10 / plan 2），OpenSpec strict 仍为 1/1，`git diff --cached --check` 通过；无代码、部署或生产状态变更。
- 2026-09-09：用户授权以最新 `origin/main=b6d3942a7cf75d51b9c6efebcef71b7317931fb6` 解除主线分叉，并要求纳入 GYT-48、排除 GYT-21。新隔离 worktree 按原顺序重放 `99a625a..4a2a617` 的 23 个提交；`git range-diff` 显示 21 个 patch 完全一致，两个 active-plan index patch 只删除 GYT-21 的 `fix-refresh-stale-regressions` 行并保留 GYT-47 日期更新。相对 `origin/main` 的 `src/`、`apps/`、`trading-rules/`、GYT-21 专属 plan 和两份 refresh/service 测试差异均为空，主线新增的两份 completed plan 也保持不变。
- 2026-09-09：pre-evidence integration commit `c6dd6b799dad3d8a07e17bd60f004d7ba0d5fd49` 已通过 `git merge --ff-only` 进入本地 `main`。该提交上 deployment/validator/guard focused suite 为 `243 passed`，fake-provider scheduled-refresh 为 `7 passed, 10 deselected`，全库为 `384 passed, 2 warnings`；五组 Helm strict lint/template、controller suspended/off offline render、Kustomize base/native、Bash/Python syntax、OpenSpec strict 1/1、docs-contract full、52-package dependency check 与 `git diff --check` 全部通过。所有验证均使用本地 render、fixture 和 fake provider，未访问生产或真实 provider。
- 2026-09-09：事实源提交 `296f62aabadafe0f3aff9197f5089e819d723231` 上重新执行同一门禁。focused suite 仍为 `243 passed`，fake-provider 仍为 `7 passed, 10 deselected`；五组 Helm lint/template、两组 offline render、Kustomize base/native、Bash/Python syntax、OpenSpec strict 1/1、docs-contract full（代码 5 / 文档 9 / plan 1）、52-package dependency check、scope 和 `git diff --check` 均通过。全库为 `382 passed, 2 failed, 2 warnings`：已知 `test_persistent_cold_requests_share_one_cross_service_refresh` 冷加载 TOCTOU 再现，`test_materialized_local_read_is_provider_free_fast_and_non_blocking` 实测 `0.877854s` 超过 `0.5s` 阈值。`src/market_environment/` 与两项测试相对 `origin/main` 均无差异，本次未重试、放宽断言或纳入被明确排除的 GYT-21 修复；两项结果留给 GYT-52 独立判定。

## Remaining Gaps（剩余缺口）

- 共享 worktree 仍不是 clean implementation baseline；本次整合只在新隔离 worktree 和临时本地 `main` worktree 中执行，未 stash/reset/覆盖共享树改动。
- Stage 2 既往八项阻塞和 Stage 4 通用发布/命令审计回流已在原 exact candidate `0cd9b31fc3f3a35dc404f6bafe8af8f87dc66ca2` 关闭并取得三路独立 GO；其获准内容与 GYT-48 已批准提交现已重放到新主线 lineage。由于提交 SHA 改写，GYT-52 仍须绑定最终 `origin/main` SHA 重验，旧 SHA 的 GO 不自动迁移。
- baseline 的跨 service 冷加载存在“旧 missing 观察后晚到 worker 再取 lease”的应用层 TOCTOU，materialized local read 也在最终并行全量门禁中出现一次 `0.877854s > 0.5s` 的性能断言失败；两项源文件和测试均与 `origin/main` 相同，不由 GYT-47 引入。GYT-21 已按授权排除，因此本 issue 不越界修复或通过重跑掩盖，GYT-52 必须在 exact-main 审阅中评估。
- `9478ff0fd946993ae582b75dbb3287cf3a818aea`、`8ef80b7ea42ce7e72ea3262f1e1d5390e2ed0213`、`3c4d2dc056b9f70e3966407fda18f976841475db`、`437b03989ddf279757c7c5e92580493c65eca62d`、`18062563728da8409cac9c38d5238286ece79370`、`f3fb0203f7bd97e434836ef9bfe209b31720e625`、`09e29c59bee3bce2720b14d0636281a186577840` 与 `b16785c815081981f9df2dd9fbfcac88d7a0a7bd` 均是被替代的历史候选，`0ab44479923ca461c0fe000865f26cc56a7ef2be` 被本地对抗审查替代；原 lineage 中仅 `0cd9b31fc3f3a35dc404f6bafe8af8f87dc66ca2` 取得三路 GO，本次重放后的 SHA 必须重新绑定验收。
- GYT-48 已完成且其四个 Stage 3 提交已整合；剩余仓库门槛是 GYT-52 对最终推送主线的 Stage 4 独立复验。
- controller runtime timezone、canary、production revision、image digest、PVC identity、备份目标、验证日期和 stop thresholds 仍是后续 Gate B 精确 packet 中待采集或冻结的事实；推进授权不能替代这些证据。

## Next Step（下一步）

由 GYT-52 对最终推送的 `origin/main` SHA 执行 Stage 4 独立验收，并显式评估已记录的两项 baseline-identical 全量测试失败。GYT-52 明确 GO 前不得启动 GYT-50/GYT-51、生产只读 preflight 或任何生产动作。
