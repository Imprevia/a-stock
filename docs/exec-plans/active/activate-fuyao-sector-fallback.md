# 启用扶摇行业板块回退执行计划

## Stage（阶段）

Stage 5 — same-image complete-off repair 与 6.1 全量离线门禁已完成；准备冻结 clean repair-control commit 并执行生产前只读重绑，真实 probe 继续受上海 15:10 门禁约束。

## Status（状态）

`production-stage-repair-ready` · 2026-10-09 用户已明确授权扩展当前 change，并保留对 probe、生产 capability 写入、rollout、一次 collection 和条件回滚的授权。OpenSpec 当前 `17/24`；任务 3.4 与 6.1 已完成，6.2 保持打开。首次 5.1 已执行受控 Helm/Kubernetes 写入和单次 image build/import，但不能标记完成：revision 90 的完整 off release 后又出现 revision 91 empty non-hook disabled schedule-component stored manifest，exact gate 已停止后续操作。下一步冻结 clean repair-control commit 并重新只读绑定生产状态；尚未执行生产 repair、调用真实 provider、写 capability、启用 sectors 或执行 production collection。

## Scope（范围）

- 增加通用 `capabilities promote` dry-run/apply CLI，并以事务方式晋升单条、脱敏、checksum-valid 的 capability report。
- 支持 `--input -` 从 stdin 读取唯一 JSON envelope，使生产 promotion 只在 exact Ready Pod 内使用既有 PostgreSQL Secret 环境，不把数据库连接导出到宿主，也不把报告复制或持久化到 Pod。
- 对 `fuyao/sectors/fuyao-market-v2` 强制 exact-date、320/320、字段覆盖、权限和请求预算证据。
- 保持 Eastmoney-first、Fuyao 仅在匹配 eligible report 后回退，四个可靠字段保留，其余字段为 `null`。
- 增加仅启用 Fuyao sectors 的默认关闭 overlay；先从 clean reviewed source 构建一个新镜像并以 sectors-off 发布，再复用同一 frozen image 做 hook-free config-only enable/off，唯一允许的语义差异是 sectors enabled flag。
- 调度 disabled 的 `component=all` stage 在完整 release 收敛后终止；对已发生的 exact reviewed schedule-only stored-manifest 中断形态，增加 same-image、无 build/import/provider/capability/collection、`--no-hooks` 的完整 off release repair。
- `fuyao real-probe` 必须在 provider/client 和 JSON/SQLite I/O 前校验上海当前有效日期、工作日及 settlement time；首次生产采集只使用 settlement-gated sectors-only command。
- 调度、Scrapling、enrichment、shadow、其他 Fuyao 数据集和 HTTP API/schema 不变。

## Acceptance（验收）

- promotion 默认 dry-run；checksum/identity/status/redaction/evidence 错误在写入前拒绝；apply 单事务单行、重复幂等、冲突拒绝。
- stdin 与文件输入遵循相同的单 envelope、checksum、redaction 和事务契约；空、畸形、多文档输入不回显内容且零写入。
- Fuyao v2 fixture 和集成测试覆盖双 Eastmoney 失败、exact-date、320/320、稳定排序、四字段、五个 null 字段、同日留存和跨日拒绝。
- real probe 在 15:09、请求日期不匹配或周末时，于 provider/client 和文件 I/O 前拒绝；15:10 边界可继续且没有 force 绕过。
- Helm lint/template、packet 和 manifest 测试证明 Secret 只引用不渲染、schedules absent/suspended、Scrapling/enrichment/shadow disabled；dirty source、hash/image drift、hook、config-only build/import 和非 sectors flag 差异均在网络或 Helm write 前拒绝。
- 真实操作按已授权顺序执行：clean reviewed sectors-off 新镜像预发布 → 盘后 probe → exact Ready Pod stdin dry-run/apply → same-image hook-free config-only enable → 一次 settlement-gated sectors-only collection；失败时 same-image config-only off。
- partial-stage repair 只接受 reviewed empty non-hook disabled schedule-component stored manifest + 与完整 off packet 精确一致的 tracked live Deployment/Service + exact Ready frozen-image sectors-off Pod + CronJob/Job absent；使用一次 hook-free complete release write，写前写后证明 Secret/PVC、镜像和禁用状态不变。

## Completion Evidence（完成证据）

- `/home/gyt/a-stock/openspec/changes/activate-fuyao-sector-fallback/` 已包含 proposal、design、两份 delta spec 和 24 项 tasks；2026-10-09 根据只读生产 preflight 和用户扩展授权补入 off-first、stdin promotion、same-frozen-image config rollout、partial-stage repair 与 real-probe pre-I/O 时间门禁。
- 前置 `deploy-unified-market-data-adapters-20261008` 已于 2026-10-09 标记为 `completed-with-production-write`；其完成证据由该计划维护。
- 已实现通用 `capabilities promote` application command/CLI、stdin 单 envelope、`fuyao/sectors/fuyao-market-v2` evidence policy、checksum-first 与 redaction equality 校验、PostgreSQL 窄事务 UoW，以及 `INSERT ... ON CONFLICT DO NOTHING` 的并发不可覆盖语义；同 checksum 幂等、异 checksum 冲突拒绝，promotion 不装配 provider，不写快照、聚合、collection run 或配置。
- 已增加 `values-fuyao-sectors-enabled.yaml` 与 `values-fuyao-sectors-off.yaml`。两份配置的 `helm lint --strict` 和离线 `helm template` 均通过，每份仅渲染 6 个非 Secret、非 CronJob 资源；回滚配置只改变 sectors enabled flag。
- 已实现 packet-bound `--stage-sectors-off`、`--promote-sectors-capability`、`--enable-sectors-config` 与 `--disable-sectors-config`。stage 在 clean reviewed source/chart/values/render/repository-tag 通过后只 build/import 一次，从目标 containerd exact tag 读取 manifest digest，并在任何 Helm write 前冻结；promotion 绑定 stored/live reviewed-off release 与同一 Deployment→ReplicaSet→Ready Pod 快照；config-only 复用同一镜像并强制 `helm upgrade --no-hooks`，唯一语义差异为 sectors enabled flag。
- 独立审查发现并修复三项 fail-closed 缺口：并发 promotion 不再覆盖不同 checksum；runtime sectors gate 只接受 `fuyao-market-v2`；typed Fuyao row 边界强制 code/name/changePct/amount 四字段有效且 `mainNet/mainNetPct/upCount/downCount/leader` 五字段显式为 `null`。
- repair 扩展前的历史 focused 验证为 `278 passed`，部署 guard 为 `96 passed`，packet validator 为 `73 passed`；这些结果尚未覆盖任务 3.4，不构成当前重新打开的 6.1 完成证据。
- repair 扩展前的后端串行全量为 `1225 passed, 6 skipped, 1 warning`，前端 Vitest 为 `20 files / 129 tests` 且 Vite build 成功；规则、OpenSpec strict、docs-contract full、Helm strict lint/template、`bash -n` 和 `git diff --check` 当时均通过。任务 3.4 完成后必须全部重跑并记录新结果。
- 2026-10-09 用户明确授权原任务 5.1–5.5，随后明确授权扩展当前 change；扩展后的受控顺序记录为 5.1–5.6。09:18（Asia/Shanghai）只读 preflight 确认 TrueNAS k3s `v1.26.6+k3s-6a894050-dirty`、Helm release `a-stock/a-stock` revision 87 deployed、Dashboard 与 PostgreSQL 均 1/1 Ready、应用 Pod 0 重启、NodePort health 200、CronJob/Job 均为 0。
- 生产 before-image：Dashboard 镜像 tag `20261008-235342-36aba3b`、imageID `sha256:d0b1fefe8408ef07c45e53fec14a31902077a6638a188deefdae2c7509a8ec30`；`a-stock-data` 2Gi 与 `a-stock-postgresql-data` 5Gi 均 Bound/RWO；调度 `enabled=false/suspend=true`；Fuyao sectors enabled/shadow 均为 0、approved revision 为空。只核对 Secret 引用和键名，未读取值。
- PostgreSQL 只读检查确认 `provider_capability_reports` 表存在、总行数 0，目标 `fuyao/sectors/fuyao-market-v2` 行数 0。preflight 退出后临时 k3s API 隧道已关闭；未调用 provider、collection，未执行集群或数据库写入。
- 扩展后的产品规格、架构、runbook、status 和 active plan/index 已同步；runbook 的所有生产 promotion/config 命令统一走受控部署入口，不再展示可绕过 packet/Pod 门禁的裸 Helm 或裸 `kubectl exec` 写路径。
- 镜像源码和首次离线证据已冻结为本地 reviewed source commit `8e83125`（分支 `codex/activate-fuyao-sector-fallback`，未推送）；生产 5.1 已从该 commit 的独立 clean worktree 完成唯一一次 build/import，后续 repair-control 和证据提交不得重建该镜像，也不改变其来源身份。
- 首次 5.1 packet 的 frozen image source 已绑定为 `FROZEN_IMAGE_SOURCE_GIT_HEAD=8e83125e6302868fd9bf4d92a5bf8f51c65bc6e4`，chart `000962ae…2aef`、off values `f2befa30…0002`、enabled values `fcf9488c…b4416`、off render `31b2adc7…499f`、enabled render `2e96a092…d6069`。镜像只 build/import 一次，为 `localhost/a-stock-market-environment:20261009-102618-8e83125@sha256:8ca1614e6bd69879b56070b9157cfda2cb5e7b38a3de02d7dc54f6a21866cf42`；新的 `REVIEWED_GIT_HEAD` 待 clean repair-control commit 后冻结，本地 smoke 已通过。
- 生产 revisions 88/89/90 分别完成 database、service、complete release；旧控制流随后因 stage 已填充 `FROZEN_IMAGE_*` 又执行 disabled schedule component，revision 91 Helm 写成功但其 stored manifest 被缩窄为 reviewed empty non-hook disabled schedule-component render，随后 `compare-release-exact` 按设计失败并停止。当前 live Dashboard 仍 `1/1 Ready`、运行上述 exact image、sectors enabled=`0`、approved revision=`fuyao-market-v2`；其他 Fuyao、shadow、enrichment、Scrapling 均关闭，CronJob/Job absent。
- 中断后 PVC 未变：`a-stock-data` UID `c03bc7f8-…`、2Gi Bound；`a-stock-postgresql-data` UID `6c426fc5-…`、5Gi Bound。未执行 probe、capability promotion、sectors enable 或 collection。
- 任务 3.4 已实现：disabled `component=all` 不再写 schedule 尾部；repair 双重绑定 revision 91 deployed/chart/hooks/computed values/stored manifest 与 mutable live state，只执行一次 `helm upgrade --no-hooks`，并要求 revision 92 deployed、`component=all` 与完整 off stored/live state。Helm v3.21.4 源码确认同 ownership live resources 会在 update 前补入 current；focused repair `9 passed`、部署 guard `104 passed`、packet validator `73 passed`。
- repair 扩展后的 6.1 验证完成：focused `384 passed, 1 warning`；后端全量 `1233 passed, 6 skipped, 1 warning`；前端 Vitest `20 files / 129 tests` 全部通过，Vite production build 成功并仅保留既有单 chunk 大于 500 kB 提示。`rules validate`（49 rules）、`rules coverage`（330 documented / 49 executable）、`docs sync-check`、两份 Fuyao profile 的 Helm strict lint/template、OpenSpec strict、`bash -n`、`git diff --check` 与 docs-contract full（代码 1 / 文档 6 / plan 1）均通过；唯一 pytest warning 是既有 Starlette `BlockingPortal` deprecation。

## Remaining Gaps（剩余缺口）

- 6.2 必须在 repair 及后续每个生产操作后持续更新。必须用已冻结 digest 恢复 complete off stored/live release，且不得再次 build/import；成功前 5.1 保持未完成。
- 真实 v2 报告尚未生成，运行时 PostgreSQL 目标行仍为 0；旧 v1 隔离证据不能作为资格。任务 5.2–5.6 均未执行；5.2 不得在上海 15:10 前执行。

## Next Step（下一步）

先完成并离线验证任务 3.4，重跑 6.1 并更新 6.2；repair 前重新只读记录 revisions 88–91 status、revision 91 stored manifest 资源集/hash、PostgreSQL Ready、Secret/PVC identity、runtime imageID 和 capability 行数。随后从新的 clean reviewed repair-control HEAD 使用现有 frozen image source HEAD/tag/digest 及 `EXPECTED_REPAIR_HELM_REVISION=91` 执行一次 `repair-sectors-off-release`；禁止 build/import/hooks/provider/capability/collection。只有 revision 92 deployed、stored complete off release、tracked live Deployment/Service exact、Pod/image exact、CronJob/Job absence和 Secret/PVC identity 全部通过后才勾选 5.1。达到上海 settlement gate 后依次执行 5.2–5.5，任一 rollout 或观察失败时执行 5.6 same-image off rollback。
