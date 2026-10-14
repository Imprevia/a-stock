# 修复 THS 目录观察版本与每日行情缺口耦合

## 目标

修复 `industry-ranking` 把固定 capability revision 当作目录主键、又按每日空行情裁剪目录后产生 checksum 冲突的问题；完整目录、每日排名可用性和板块日线可用性分开表达，使兼容的 partial 证据可以继续驱动 `sector-turnover` 与 `sector-breadth`。

## 范围

包含：OpenSpec `fix-ths-catalog-revision`、事实文档、领域模型、Fuyao THS adapter、PostgreSQL repository、三任务 collector/committer/DAG、Chapter 01/API、数据采集页、第 05 页和离线测试。目录观察 revision 使用 `provider + capability revision + 上海交易日 + 完整目录 checksum`；本阶段新增一个窄范围 Alembic `0007_ths_catalog_identity`，将 PostgreSQL runtime/fresh schema 从 version 9 提升到 10，仅删除不含交易日的冗余唯一约束。该 revision ID 保持不超过 Alembic 默认 `version_num VARCHAR(32)` 的边界，不扩大版本表字段。

生产阶段 7.1–7.5 已于 2026-10-14 获用户整体授权，但仍必须逐步满足 runbook 的只读基线、停写、不可覆盖
备份、隔离恢复、不可变镜像、盘后窗口、写后验收和回滚门禁；任一步失败即停止，不把整体授权当作跳过前置条件。

## Stage（阶段）

- 当前阶段：**7.1–7.5 已授权的生产恢复**
- 阶段序列：事实文档 → 领域/provider → 持久化/采集 → API/前端 → 离线验证 → 另行授权的生产恢复

## Status（状态）

`production-rollout-paused-audit-job-gc` · 2026-10-14 用户已明确授权 7.1–7.5，并批准将过长的 Alembic revision
`0007_ths_catalog_revision_identity` 修正为 `0007_ths_catalog_identity`。短 ID 已通过真实 PostgreSQL 16
完整 Alembic 升级、默认 32 字符版本列和跨日期事务回归；2026-10-15 已完成 7.1 manual-freeze 与 7.3
不可变镜像发布控制的离线复核，OpenSpec 6.6 已完成。2026-10-15 执行 7.1 时已把 schedule 与 manual
writes 安全关闭，但 schedule 入口删除 Helm-retained CronJob 时由 Kubernetes owner-reference 级联删除了原
`Failed=True` 审计 Job/Pod。PostgreSQL collection run/task 审计仍完整；因 Kubernetes Job 证据不可恢复，
7.1 保持未完成，7.2 及后续生产动作暂停等待处置决定。
集成审查确认原有
`ths_catalog_revisions` 还包含 `UNIQUE (provider, capability_revision, checksum, fetched_at)`：该约束没有
交易日维度，无法在固定时钟、离线 replay/import 等合法场景中同时保存两个“日期不同、目录 checksum
相同、fetched_at 相同”的 observation revision；该约束已由离线 `0007` 删除并通过回归。未调用 provider，未执行任何
生产写入、生产迁移、部署或调度变更。

## Acceptance（验收）

- capability revision 与 catalog observation revision 不再混用；同日同完整目录重试幂等，目录真实变化形成可共存的新 revision，跨日保留独立观察血缘。
- 四类完整目录的 checksum/tag counts 在每日行情对账前计算；行情字段为空不得删除 relation 或改变目录身份。
- snapshot 身份缺失、重复或日期不符仍 fail closed；身份与日期有效但行情字段为空时，以 `missingLiveCodes`/`missingRankingCodes`、行级质量和 `null` 明确表达，不生成全空 bar 或补零。
- ranking relations 与完整目录一致；bars 与 `missingLiveCodes` 精确覆盖唯一目录代码；同日隐式读取只选择一个确定的最新兼容 revision。
- `sector-turnover` 可消费兼容 partial；`sector-breadth` 排除不可排名行，有效候选不足时明确 `insufficient`，而不是伪装完整 Top N。
- collection/API/UI 提供有界、无敏感信息的稳定诊断，同时兼容历史纯文本 warning；普通 GET 保持 provider-free。
- 旧固定 revision、旧成功事实及 2026-10-14 失败/blocked 审计原样可读；`0007` 只删除冗余唯一约束，
  不重写历史。
- focused/full pytest、前端 test/build、OpenSpec strict、docs-contract full 和 `git diff --check` 全部通过，或在 Remaining Gaps 中明确记录真实阻塞。

## 实施任务

- [x] 创建并严格校验 OpenSpec `fix-ths-catalog-revision` 的 proposal/spec/design/tasks
- [x] 同步架构、产品、runbook、仓库映射和状态事实
- [x] 实现目录观察身份、完整目录 checksum、两类缺口及行级质量
- [x] 实现 repository 单 revision 读取、partial 原子提交和 DAG 兼容性
- [x] 实现诊断 API、数据管理页和第 05 页展示
- [x] 完成 OpenSpec strict、docs-contract full 和最终 diff 门禁
- [x] 补齐并验证同镜像 manual-off 专用入口和普通发布的 clean reviewed HEAD / manifest-digest 门禁
- [ ] 在另行授权后执行生产备份、发布、定向重采和至少两个交易日观察

## Completion Evidence（完成证据）

- OpenSpec：`openspec validate fix-ths-catalog-revision --strict` 已通过；离线任务 1.1–6.4 全部完成。
- 文档先行：架构、产品规格、runbook、仓库映射、状态和旧 THS plan cross-reference 已同步；
  `python3 scripts/check-docs-contract.py --mode=fast`、`git diff --check` 通过。
- 领域/provider 聚焦测试：45 passed。
- 诊断/API 聚焦测试：48 passed；架构测试 13 passed。
- 前端聚焦测试：28 passed；Vite production build 通过（仅保留既有大 chunk warning）。
- 持久化/采集/DAG 已补显式 sync 的 checksum/observation revision 复核、缺失 accepted ranking
  prerequisite 的 typed hard failure，以及 partial Chapter 01 materialization round-trip；物化聚焦测试
  `4 passed`。dataset + DAG 聚焦为 `19 passed`；operations 聚焦为 `15 passed`；THS provider/domain/diagnostics
  聚焦为 `54 passed`；PostgreSQL/schema/migration 聚焦为 `23 passed, 1 skipped`，另有 PostgreSQL THS/database
  回归 `19 passed, 3 skipped`；HTTP/API/queries 聚焦为 `32 passed, 2 warnings`。
- 最终 THS focused 命令覆盖 provider/domain/repository/operations/dataset/DAG/materialization/migration/API 共
  16 个测试文件：`140 passed, 1 warning`；warning 为 Starlette `BlockingPortal` 已知弃用提示。
- 全量后端：`.venv/bin/python -m pytest -p no:cacheprovider tests -q` →
  `1472 passed, 6 skipped, 1 warning in 511.19s`；6 个 skip 均由测试自身条件声明，无 unexplained failure。
- 前端：`npm run test` → `20 files / 143 tests passed`；`npm run build` → 成功生成 production bundle，仅有
  既有的 `>500 kB` chunk warning。
- 生产预审发现原 Alembic revision ID 长 34，超过默认 `version_num VARCHAR(32)`；用户已批准缩短为
  `0007_ths_catalog_identity`，且不扩大 Alembic 版本表、不增加额外 DDL。
- 短 ID 聚焦迁移套件：`14 passed`；`.venv/bin/alembic heads` → `0007_ths_catalog_identity (head)`。
- 真实 PostgreSQL 16.4 fresh migration：`alembic upgrade head` 完整应用 0001–0007；实际
  `alembic_version.version_num` 为 `character varying(32)`，head 为 `0007_ths_catalog_identity`，
  `schema_migrations max(version)=10`，目标冗余唯一约束数为 0。事务内不同日期 revision 在相同
  provider/capability/checksum/fetched_at 下同时插入 2 行成功，随后 `ROLLBACK` 后为 0；验证容器
  `a-stock-pg-revision-check-20261014` 已停止但未删除。
- 受控 manual freeze：新增 `--disable-manual-refresh`，仅允许 reviewed full packet 的 literal `1 -> 0`，
  同 frozen image、三阶段 stored hook exact compare、terminal audit Job 保留、terminating resource 拒绝、
  StatefulSet/PVC 在内的 full live exact compare、PVC/Secret identity 与 Ready Pod runtime 校验；唯一写入为
  `--no-hooks --atomic --wait`，无 build/import/provider/migration。聚焦 `33 passed`，完整调度 guard
  `151 passed in 219.56s`，Bash/Python 语法和 diff gate 通过；两轮只读复审发现的 5 项 P1 均已修复。
- 普通 `all`/`service` 发布门禁：任何目标访问或 build 前要求 clean worktree 与 full lowercase
  `REVIEWED_GIT_HEAD == HEAD`；image import 后冻结 exact containerd manifest digest，在 database、service 和
  final release 每次 Helm write 前分别重验，写后验证 Deployment→current ReplicaSet→唯一 Ready Pod 的
  repo/tag/runtime imageID 及 target manifest digest。独立只读审计无阻塞；import 缺失/不匹配与第 2/3/4
  次 digest 漂移均有精确的写入阻断测试，成功路径证明 4 次 capture 与 database→service→all 顺序。
  补强后的完整调度 guard 为 `168 passed in 266.92s`；Bash 语法、Python 编译和 `git diff --check` 通过。
- 6.6 收口后的最终门禁：前端 `20 files / 143 tests passed`，Vite production build 成功（仅既有
  `>500 kB` chunk warning）；OpenSpec strict、docs-contract full（代码 48 / 文档 8 / plan 2）与 diff gate
  通过。首次把 Vite build 与全量后端并行时，build 清空 `dist/assets` 的瞬间使 12 个 API 静态目录挂载测试
  失败，其余 `1512 passed, 6 skipped`；受影响两文件在 build 完成后复跑 `28 passed`，随后顺序全量后端
  `.venv/bin/python -m pytest -p no:cacheprovider tests -q` →
  `1524 passed, 6 skipped, 1 warning in 533.20s`。warning 仍为 Starlette `BlockingPortal` 已知弃用提示。
- 生产：7.1–7.5 已授权；7.1 已执行到安全停写，但因下述 Kubernetes Job 审计缺口保持未完成并暂停。
- 7.1 只读基线（2026-10-15 01:25 Asia/Shanghai）：Helm revision 107、k3s
  `v1.26.6+k3s-6a894050-dirty`、镜像 `20261014-104800-b0a7c35`、containerd manifest digest
  `sha256:ef8b524b…2ae7`、Dashboard/PostgreSQL Ready 且 0 restart；schema v9 / Alembic
  `0006_ths_rank_null_pct`。CronJob 为 `30 16 * * 1-5`、`suspend=false`、active=0；唯一 Job
  `a-stock-data-collection-29866110` 为 `Failed=True`/active=0。manual=1，THS writes/capability 开关保持 on；
  active lease/run/task/THS operation 全为 0。旧目录 revision/checksum 为
  `fuyao-ths-catalog-v1` / `b6997cd2…525ce`，relations/rankings/bars 均 846；4 条 capability 不变。
  2026-10-14 有 3 个 collection run、11 个 task，包含原失败/blocked 链。
- 7.1 停写执行：第一次 `--disable-schedule` 产生 revision 108；Helm stored release 已 off，但 retained
  CronJob 仍 active shape，入口拒绝删除并 fail-safe patch 为 `suspend=true`。确认所有 writer=0 后重跑，
  revision 109 删除 exact retained CronJob并证明 absent。`--disable-manual-refresh` 使用 clean reviewed HEAD
  `cca2690d4b65c98f865d421192ab8229514170c9`、reviewed chart/values/render hashes 与同一 frozen image，
  revision 110 以 `--no-hooks --atomic --wait` 完成，manual=0、Ready=1、POST 返回 403、schema 仍 v9，两个
  PVC 与两个应用 Secret UID 不变。数据库旧 846 事实及 2026-10-14 审计哈希保持可读，所有 writer=0。
- 7.1 阻塞：revision 109 删除 CronJob 使用 Kubernetes 默认级联语义，导致其 owner Job
  `a-stock-data-collection-29866110` 与 Pod 被垃圾回收，`kubectl get/logs` 均 NotFound；manual-off 入口没有
  删除 Job。数据库对应 run/task 仍保留（3 runs / 11 tasks），但不能伪造或重建原 Job。未执行 7.2
  backup/migration、7.3 deployment 或任何 provider 调用。

## Remaining Gaps（剩余缺口）

- `0007` 的短 revision ID、fresh schema、Alembic contract、runtime minimum version、真实 PostgreSQL 16
  完整升级和跨日相同 checksum/相同 `fetched_at` 可并存回归均已通过。不得通过扩大 version 表、篡改
  checksum、伪造 `fetched_at` 或复用跨日 revision 规避。
- 7.1 的同镜像 manual-off 专用入口和 7.3 的普通 all/service clean reviewed HEAD、导入后 manifest
  digest 强制校验均已完成离线门禁；生产仍须从 clean reviewed commit 按 7.1 顺序重新捕获基线并停写。
- OpenSpec 已新增 6.5/6.6：manual-off 入口只允许 reviewed full packet 的 literal `1 -> 0`、同镜像、
  `--no-hooks`、schedule absent、每个 retained Job 均有 `Complete=True`/`Failed=True` 终态、stored hooks 与
  PVC/Secret identity 不变，并保留 failed/completed 审计 Job、拒绝 terminating managed resources；普通
  all/service 必须在任何目标访问前绑定
  clean worktree + full reviewed HEAD，导入后冻结 manifest digest，Helm 写前重验并在 Ready Pod 上验证。
- 生产 schema 仍是 v9；`0007` migration/deploy 已授权但尚未执行。
- 生产现状仍保留固定 `fuyao-ths-catalog-v1` 目录 revision 与 2026-10-14 的 checksum collision/blocked 审计；不得通过改写历史记录消除。
- 任务 7.x 的生产备份、部署、provider 写入、调度恢复及跨交易日观察已获授权但尚待逐步执行；至少两个
  完成交易日的观察存在自然时间边界，未获得足够日期证据前不得勾选 7.5。
- 7.1 的 schedule/manual writer 已安全关闭，但 exact failed Kubernetes Job 被 CronJob 删除的默认级联回收；
  该证据不可原样恢复。必须先决定是否以保留的 PostgreSQL run/task 审计和已捕获 pre-state 作为显式缺口继续，
  或停止本 rollout；无论选择哪条路径，schedule disable 入口都需先改为 orphan-preserving 删除并补回归，避免
  后续再次删除 completed/failed Job。不得创建替代 Job 冒充原证据。

## Next Step（下一步）

保持 CronJob absent、manual=0 和所有 writer=0，不执行 7.2–7.5。先由操作责任人决定如何处理已被级联回收的
failed Kubernetes Job 证据；获准继续时，先更新 schedule disable 入口为保留 terminal Job 的 orphan 删除并完成
离线回归，再从当前 revision 110 只读复核后进入 7.2 的不可覆盖备份和隔离恢复。
