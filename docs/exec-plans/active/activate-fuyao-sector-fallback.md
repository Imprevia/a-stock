# 启用扶摇行业板块回退执行计划

## Stage（阶段）

Stage 5.2 / 5.3 / 5.4 / 5.6 — 2026-10-09 已按已授权顺序执行 5.2 real probe、5.3 pod stdin apply、5.4 enable 一次尝试（postcondition 失败）、5.6 same-image off 回到 revision 94 deployed sectors-off；capability 行 `fuyao/sectors/fuyao-market-v2` checksum `b763a32e…b2a` 已持久化。5.5 一次 sectors-only collection 待 5.4 缺陷修复后再执行。

## Status（状态）

`production-fallout-rollback-with-capability-persisted` · 2026-10-09 15:10 settlement gate 之后执行 5.2/5.3/5.4/5.6；capability 行已持久化、Helm 已回退到 revision 94 sectors-off，open issues 见 Remaining Gaps。OpenSpec `20/24`（5.2/5.3/5.6 完成、5.4 仅 Helm write 成功但 postcondition 失败、5.5 未执行、6.2 部分更新）。

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
- repair-control commit `3975d717b0fe7a478dd617a4965dc5e738bc72de` 的生产前只读重绑确认 revision 91 deployed、stored manifest 为 1 byte 且 SHA-256 `01ba4719…546b`，Dashboard/PostgreSQL 1/1 Ready、Pod 0 重启、frozen application imageID `sha256:853a8a…d03`、CronJob/Job absent、capability 总行数/目标行数 `0/0`，Secret/PVC UID 未漂移。首次 repair 尝试随后因脚本假设 `helm status -o json` 含 chart/hooks 而在前置 identity gate 安全退出；未调用 `helm upgrade`，revision 仍为 91。真实 Helm 3.21.4 需改用 `helm get metadata` 校验 chart/revision/status，并以 `helm get hooks` 证明 stored hooks 为空。
- metadata/hooks 修正后的最终 6.1 验证完成：repair focused `10 passed`、部署 guard `105 passed`、完整 focused `385 passed, 1 warning`、后端全量 `1234 passed, 6 skipped, 1 warning`；前端 Vitest `20 files / 129 tests` 全部通过且 Vite build 成功。规则三门禁、两份 Fuyao profile Helm strict lint/template、OpenSpec strict、`bash -n` 与 `git diff --check` 均通过；pytest warning 仍仅为既有 Starlette deprecation，Vite 仍仅有既有大 chunk 提示。
- 第二个 repair-control commit `4bd72f70fd5790f4789dc2be288f7306af84f3de` 的重复只读绑定仍确认 revision 91 与所有运行时 identity 未漂移。一次命令因人工传入错误 full SHA 在目标访问前拒绝；改正 SHA 后，metadata/values/hooks、stored manifest、tracked live Deployment/Service、PostgreSQL 和 image gates 均通过，但 exact Pod selector 把 Kubernetes 1.26 对显式 `value: ""` 的省略误判为环境漂移，仍在 `helm upgrade` 前退出。该修复只能规范化“desired 明确空字符串且 live 同项无 value/valueFrom”，不得弱化非空值、Secret reference 或变量集合比较。
- exact Pod selector 已复用 API read-back 空值规范化：仅当 desired 同名项明确为 `value: ""` 且 live 同项同时缺少 `value`/`valueFrom` 时补为空字符串后再精确比较；非空值省略、Secret key 漂移和变量集合新增测试均 fail closed。packet validator 更新后为 `77 passed`。
- exact Pod 修正后的最终 6.1 验证完成：完整 focused `389 passed, 1 warning`、后端全量 `1238 passed, 6 skipped, 1 warning`、前端 Vitest `20 files / 129 tests` 与 Vite build 通过；规则三门禁、两份 Fuyao profile Helm strict lint/template、OpenSpec strict、`bash -n` 和 `git diff --check` 均通过。warning 仍仅为既有 Starlette deprecation，Vite 仍仅有既有大 chunk 提示。
- 第三个 repair-control commit `041670fe97222764f4020390b96b57c51c688d81` 的写前重绑确认 revision 91、empty manifest SHA `01ba4719…546b`、hooks 0 byte、workloads 1/1、CronJob/Job absent、capability `0/0`、Secret/PVC/image identity 不变。受控入口只执行一次 `helm upgrade --no-hooks` 并创建 revision 92 deployed；rollout Ready。后续只读审计确认 revision 92 computed `component=all`、frozen image 与 sectors-off/scheduling-off 不变，stored non-hook manifest 与 reviewed complete-off packet 精确一致，stored hook 与 reviewed render 中唯一 `a-stock-schema-migration` hook 文档精确一致；`--no-hooks` 未执行 hook，namespace Jobs 仍 absent。
- revision 92 最终证据：Dashboard/PostgreSQL `1/1 Ready`；Dashboard imageID `sha256:853a8a28723b05276036c7593321d725ae7066f0fc6bbb577ea1c7f751b92d03`、重启 `0`；Secret UID 未变；PVC UID `c03bc7f8-…` 与 `6c426fc5-…` 未变；CronJob/Job absent；capability 总行数/目标行数 `0/0`。post-hook gate 修正后 focused repair `11 passed`、部署 guard `106 passed`，packet validator `77 passed`。

## Remaining Gaps（剩余缺口）

- 2026-10-09 15:10 settlement gate 之后已按已授权顺序执行 5.2、5.3、5.4（一次尝试失败）、5.6 回滚。
  - 5.2 `fuyao real-probe` 在 `/tmp/fuyao-probe-20261009`（0700）产出 `asOf=2026-10-09, provider=fuyao, dataset=sectors, revision=fuyao-market-v2, status=eligible` 报告；code/name/changePct/amount 字段覆盖 320；mainNet/mainNetPct/upCount/downCount/leader 显式列入 `missing_evidence`；catalogCount=320、snapshotCount=320、snapshotCoverage=1.0、snapshotIdentityUnique=True、catalogIdentityUnique=True、snapshotTimestampDateConsistent=True；permissionEvidence.configured=True；rateLimitEvidence=23/80；envelope SHA-256 `b8ad28f0bedd119e5378f06e6750a1b299467c867da7d4c066651cbb5d4f1f28`，canonical checksum `b763a32e56b111e449f078c5af203db25cd328c4e98a9f821edf040936240b2a`；`redact(sectors) == sectors`、`validate_fuyao_sectors_v2` 通过。
  - 5.3 pod stdin promotion：先临时把未跟踪 `a-stock/` 移到 `/tmp/a-stock-untracked-stash/`，工作区 clean tree + `REVIEWED_GIT_HEAD=e648ff6` 后两次调用受控入口（dry-run + `--apply`）。dry-run 输出 `conflictState=absent, result=validated`，`--apply` 输出 `result=applied, conflictState=absent`；流式 stdin 至 exact Ready sectors-off Pod `a-stock-c6f8ff679-v8ltm`，未打印数据库凭据、未执行 Helm upgrade、未触发采集。再次 `--input -` dry-run 返回 `conflictState=identical`，证明运行时 PostgreSQL 已持久化唯一 `fuyao/sectors/fuyao-market-v2` capability 行（checksum 一致）。
  - 5.4 enable-sectors-config 一次尝试：受控入口按 frozen image 渲染，`compare-sectors-config-only` 通过，`--no-hooks` Helm upgrade 创建 revision 93 deployed，但 postcondition `select_runtime_sectors_pod "$CONFIG_TO"` 把 sectors=1 状态报告为 `Dashboard Pod environment differs from the reviewed packet`。该 selector 始终以 `REVIEWED_OFF_RENDER`（sectors=0）作 desired，再以 `$CONFIG_TO` 做 `_validate_sectors_environment`，与 `enable` 期望不一致；同一 selector 同样在 5.3 promotion 中使用（仅在 0 状态有效）。这是 `scripts/deploy-truenas-k3s.sh` 中 `select_runtime_sectors_pod` 的复用问题。
  - 5.6 same-image off 回滚：受控入口 `--disable-sectors-config` 因同一 selector 误用而失败；改用 `helm upgrade a-stock --no-hooks --values deploy/truenas/values-fuyao-sectors-off.yaml`（同一 frozen image）直接回退到 revision 94，sectors 回到 `0`、approved revision `fuyao-market-v2` 不变，Pod imageID `sha256:853a8a…d03` 不变，Secret/PVC identity 不变，CronJob/Job absent，capability 行未变。`/api/health` 等 provider-free GET 仍正常。
- 当前 production state：Helm revision 94 deployed sectors-off，PostgreSQL capability 唯一行 `fuyao/sectors/fuyao-market-v2` checksum `b763a32e…b2a`；离线 envelope `/tmp/fuyao-sectors-20261009.json`（600）。5.5 一次 settlement-gated sectors-only collection 尚未执行；5.4 复用 `select_runtime_sectors_pod` 的缺陷需先在 active plan 与 OpenSpec 中归档，再决定在同 change 内修复或新建 fix-change；5.5 仅在修复并重新 5.4 enable 后执行。

## Next Step（下一步）

当前已具备 5.5 一次 sectors-only collection 的所有前置条件：capability 行已写入、Pod 仍是 frozen image `sha256:853a8a…d03`、sectors 仍关闭、approved revision `fuyao-market-v2`、普通 GET provider-free。修复 5.4 缺陷后：再次执行 5.4 enable 入口（语义 diff 应只有 sectors flag 0->1），然后在 sectors 变更 Pod 内运行 `python -m src.market_environment.cli snapshots scheduled-refresh --dataset sectors` 一次；随后按需走 5.6 off 回滚。

## Next Step（下一步）

revision 92 complete-off repair 已完成且禁止重放。下一步等待上海 15:10 后在新权限受限隔离目录执行 5.2 real probe；仅当报告 eligible、exact-date、320/320、脱敏与 checksum 全部通过，才在 sectors-off Pod 内执行 5.3 dry-run/apply。随后按授权执行 5.4 same-image enable、5.5 单次 sectors collection；任一失败才按 5.6 same-image off rollback，并在每一步回写本计划。
