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

`production-7-3-complete-awaiting-settlement` · 2026-10-14 用户已明确授权 7.1–7.5，并批准将过长的 Alembic revision
`0007_ths_catalog_revision_identity` 修正为 `0007_ths_catalog_identity`。短 ID 已通过真实 PostgreSQL 16
完整 Alembic 升级、默认 32 字符版本列和跨日期事务回归；2026-10-15 已完成 7.1 manual-freeze 与 7.3
不可变镜像发布控制的离线复核，OpenSpec 6.6 已完成。2026-10-15 执行 7.1 时已把 schedule 与 manual
writes 安全关闭，但 schedule 入口删除 Helm-retained CronJob 时由 Kubernetes owner-reference 级联删除了原
`Failed=True` 审计 Job/Pod。PostgreSQL collection run/task 审计仍完整；Kubernetes Job 证据不可恢复。
2026-10-15 用户已批准把该丢失登记为显式审计缺口、接受 PostgreSQL 审计与已捕获 pre-state 作为剩余证据，
并授权先把 schedule disable 修成 orphan-preserving 后继续 7.2。OpenSpec 6.7 已完成：调度关闭现在使用
hook-free Helm write，写前冻结完整 namespace terminal Job 证据，以 orphan propagation 删除 retained CronJob，
并对删除前后集合/UID/计数/完整终态 condition 漂移 fail closed。2026-10-15 已从包含本修复的 clean reviewed commit
`021071cbb7e3ce87dd59806226642cb916db6d75` 和新 detached worktree 完成 revision 110 只读复核，7.1 已收口；
生产继续保持安全停写。2026-10-15 已完成 7.2 不可覆盖备份、全新 loopback-only PostgreSQL 16.4 恢复和
隔离 `0007` 演练，所有迁移及历史不变门禁通过。7.3 已从该 clean reviewed HEAD 发布单一不可变镜像并完成
provider-free 验收，生产现为 Helm revision 113、schema v10/0007，schedule/manual 继续关闭；7.4 等待
2026-10-15 15:10 Asia/Shanghai 结算边界后执行已授权的 THS 三任务。
集成审查确认原有
`ths_catalog_revisions` 还包含 `UNIQUE (provider, capability_revision, checksum, fetched_at)`：该约束没有
交易日维度，无法在固定时钟、离线 replay/import 等合法场景中同时保存两个“日期不同、目录 checksum
相同、fetched_at 相同”的 observation revision；该约束已由离线 `0007` 删除并通过回归。本轮 6.7 修复不调用
provider，也不执行新的生产备份、迁移、部署或调度变更；先前 7.1 的 revisions 108–110 事实按下文保留。

## Acceptance（验收）

- capability revision 与 catalog observation revision 不再混用；同日同完整目录重试幂等，目录真实变化形成可共存的新 revision，跨日保留独立观察血缘。
- 四类完整目录的 checksum/tag counts 在每日行情对账前计算；行情字段为空不得删除 relation 或改变目录身份。
- snapshot 身份缺失、重复或日期不符仍 fail closed；身份与日期有效但行情字段为空时，以 `missingLiveCodes`/`missingRankingCodes`、行级质量和 `null` 明确表达，不生成全空 bar 或补零。
- ranking relations 与完整目录一致；bars 与 `missingLiveCodes` 精确覆盖唯一目录代码；同日隐式读取只选择一个确定的最新兼容 revision。
- `sector-turnover` 可消费兼容 partial；`sector-breadth` 排除不可排名行，有效候选不足时明确 `insufficient`，而不是伪装完整 Top N。
- collection/API/UI 提供有界、无敏感信息的稳定诊断，同时兼容历史纯文本 warning；普通 GET 保持 provider-free。
- 旧固定 revision、旧成功事实及 2026-10-14 PostgreSQL 失败/blocked 审计原样可读；`0007` 只删除冗余唯一约束，
  不重写历史。未来 schedule disable 必须以 orphan propagation 保留完整 namespace terminal Job 集合的
  name、UID 和终态；已丢失的 Kubernetes Job 仅登记不可恢复缺口，不得重建。
- focused/full pytest、前端 test/build、OpenSpec strict、docs-contract full 和 `git diff --check` 全部通过，或在 Remaining Gaps 中明确记录真实阻塞。

## 实施任务

- [x] 创建并严格校验 OpenSpec `fix-ths-catalog-revision` 的 proposal/spec/design/tasks
- [x] 同步架构、产品、runbook、仓库映射和状态事实
- [x] 实现目录观察身份、完整目录 checksum、两类缺口及行级质量
- [x] 实现 repository 单 revision 读取、partial 原子提交和 DAG 兼容性
- [x] 实现诊断 API、数据管理页和第 05 页展示
- [x] 完成 OpenSpec strict、docs-contract full 和最终 diff 门禁
- [x] 补齐并验证同镜像 manual-off 专用入口和普通发布的 clean reviewed HEAD / manifest-digest 门禁
- [x] 补齐并验证 schedule disable 的 hook-free Helm write、orphan 删除、namespace terminal Job 集合/身份/终态前后保持和漂移 fail-closed 门禁
- [x] 完成授权后的生产只读基线、安全停写、关键身份复核与不可恢复 Kubernetes Job 缺口登记（7.1）
- [x] 完成不可覆盖 PostgreSQL 备份、隔离 PostgreSQL 16.4 恢复、`0007` 演练和历史不变验证（7.2）
- [x] 完成 clean-HEAD-bound 不可变镜像发布、生产 `0007` 与 provider-free 零漂移验收（7.3）
- [ ] 执行盘后定向重采和至少两个交易日观察（7.4–7.5）

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
- 6.7 schedule disable 审计保留：入口在 Helm write 前冻结完整 namespace Job 集合，只接受每个 Job
  `active=0` 且恰有一个 `Complete=True`/`Failed=True`；冻结 name、UID、active/failed/succeeded 计数和完整
  true terminal condition。调度关闭 Helm write 强制 `--no-hooks`，retained exact CronJob 仅以
  `--cascade=orphan --wait=true` 删除，删除前后 Job 证据必须字节等价。聚焦成功/非终态/删除失败/删除前读取或
  UID 漂移/删除后新增、丢失、UID、计数、condition 漂移/空集合/CronJob 已 absent 共 `12 passed`；完整
  `tests/test_truenas_scheduling_guard.py` 为 `180 passed in 297.25s`，部署清单为 `190 passed in 6.99s`。
  独立只读审查未发现剩余 P0/P1；Bash 语法、OpenSpec strict、docs-contract full 与 diff gate 通过。
- 生产：7.1–7.5 已授权；7.1 已执行到安全停写，下述 Kubernetes Job 审计缺口已获准显式接受，待 6.7 reviewed commit 与 revision 110 只读复核后收口。
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
- 7.1 审计缺口：revision 109 删除 CronJob 使用 Kubernetes 默认级联语义，导致其 owner Job
  `a-stock-data-collection-29866110` 与 Pod 被垃圾回收，`kubectl get/logs` 均 NotFound；manual-off 入口没有
  删除 Job。数据库对应 run/task 仍保留（3 runs / 11 tasks），但不能伪造或重建原 Job。用户已批准将其作为
  不可恢复的显式审计缺口继续；7.1 收口时尚未执行 7.2 backup/migration、7.3 deployment 或任何 provider 调用。
- 7.1 clean reviewed 复核（2026-10-15 09:51 Asia/Shanghai）：detached worktree HEAD 为
  `021071cbb7e3ce87dd59806226642cb916db6d75` 且无改动；Helm revision 110/deployed，CronJob 与 Job 集合均为空，
  manual env=`0`、collection POST=403、health=200。active lease/run/task/THS operation 与非 idle DB session 全为 0；
  PostgreSQL 16.4 仍为 schema v9 / `0006_ths_rank_null_pct`。应用镜像仍为
  `20261014-104800-b0a7c35`，containerd manifest digest 仍为
  `sha256:ef8b524bf3e143ec68348100ed9384be8bd21048637a03cd1c358fcaaf7a2ae7`；Dashboard/PostgreSQL 均 Ready、
  0 restart。PVC `a-stock-data`=`c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe`/2Gi 与
  `a-stock-postgresql-data`=`6c426fc5-10e2-4e88-b534-b258c70869c4`/5Gi，Secret
  `a-stock-market-provider`=`81b9d039-7d77-44bc-9c4f-41b9ce2e19b2`、`a-stock-postgresql`=
  `653a79bf-a881-43de-8623-2d9f69e9aa0f` 均未漂移。4 条 capability 与旧
  `fuyao-ths-catalog-v1` / `b6997cd26d4cb5dc32b7bd69dd5b1fd64d2e24c8324b65c88008deafc32525ce` 保持；
  relations/rankings/bars 各 846。2026-10-14 仍为 3 runs（failed=2/partial=1）与 11 tasks
  （blocked=4/failed-missing=3/partial=2/success=2），canonical MD5 分别为
  `8fdfa695658239b7fabe84c0f8144758` / `590380dd68d8903bb5a6052c8103589c`。复核未调用 provider、未执行 Helm write、
  未迁移生产数据库，且没有重建已丢失 Job。
- 7.2 不可覆盖备份（2026-10-15 01:57:31 UTC）：生产持久目录已发布只读文件
  `/mnt/xiaomi/app-builds/a-stock/a-stock-pgdump-20261015T015731Z-helm110-schema9-pvc-6c426fc5-021071cbb7e3.dump`，
  2,885,212 bytes，SHA-256
  `8d459ecc3a8d3dc4cc09428afceef263ffa54d976583738b51db22a596a188c5`，`pg_restore --list` SHA-256
  `219642ec078f3724c0eb46ffc25b4ce86e6118d2c181e62ea79a6303c855d2b3`；同目录 `.sha256` 与 `.manifest`
  sidecar 均为 mode 0400。备份前后 Helm=110、CronJob/Job=0、manual=0、writer state=`0|0|0|0|0`、schema
  v9/0006 与 PostgreSQL PVC UID `6c426fc5-10e2-4e88-b534-b258c70869c4` 完全不变。首次通过远程 stdin 执行
  `pg_restore --list` 时因 stdin 未关闭而悬挂，final 尚未发布；已精确终止本次创建的两个只读校验进程，保留并
  三方校验同一个 `.partial` 后才以硬链接无覆盖发布，未重跑或覆盖 dump。
- 7.2 隔离恢复与迁移：操作机副本、生产持久副本和容器内副本 SHA-256 一致；全新容器
  `a-stock-pg-recovery-7-2-20261015T020129Z` 使用既有
  `docker.m.daocloud.io/library/postgres:16.4`（未 pull），仅绑定 `127.0.0.1:40919`，单事务恢复成功。
  迁移前为 v9/0006，目标冗余约束/`(revision_id, provider)` unique/主键计数=`1|1|1`；从 clean reviewed
  HEAD `021071cbb7e3ce87dd59806226642cb916db6d75` 以显式 loopback URL 应用 `0007` 后为
  v10/`0007_ths_catalog_identity`，计数=`0|1|1`，`alembic_version.version_num` 仍为 varchar(32)，
  `change_pct` 仍 nullable。37 个业务表迁移前后逐表 canonical SHA-256 文件完全一致，汇总 SHA-256 均为
  `42049c87be10586511c077a15f366e00e646c84e971fb4872f4e194b3739cccb`；旧 846/846/846、4 条 capability、
  3 runs/11 tasks 及 failed/blocked 状态、2 条 THS operation（failed=1/success=1，MD5
  `9daf0cb73301d6c3d490868940e8bb4f`）均不变。事务探针证明跨日期相同 checksum/fetched_at 两行可共存，
  rollback 后为 0。最终生产 post-check 仍为 Helm 110、v9/0006、health=200、POST=403、writer=0；7.2 未对生产
  运行 Alembic、未执行 Helm write、未调用 provider。
- 7.3 不可变镜像发布（2026-10-15 10:08–10:19 Asia/Shanghai）：clean detached worktree HEAD
  `021071cbb7e3ce87dd59806226642cb916db6d75` 构建唯一 tag
  `localhost/a-stock-market-environment:20261015-100802-021071c`；本地 health/首页 smoke 通过，归档 SHA-256
  `35d412a2b9e3be1fefad99630a3ae3e653d2b20b4b8eea04ead364dec46900bd`。远端校验并 import 后冻结 containerd
  manifest digest `sha256:ada52cb449d09ed3def9290a732d3d6925e23cbdcbe00893d38525affc8ed4fc`；database、service、full
  release 每次 Helm write 前均由受控入口重验 exact digest。Helm revisions 111/112/113 依次完成 migration、service
  rollout 和完整 release 收敛，schedule phase 因 disabled baseline 跳过；最终 Deployment `a-stock` → ReplicaSet
  `a-stock-78bd9df566` → Ready Pod `a-stock-78bd9df566-xsq2g` 使用同一 repo/tag，runtime imageID
  `sha256:d78c7092e94b6349b8a31ec07683c1ca80515a05cfe9030791e3bfacda122915`，restart=0，manual=0，CronJob/Job
  均 absent。
- 7.3 数据/接口验收：生产 Alembic=`0007_ths_catalog_identity`、schema=10，目标冗余 unique / 保留
  `(revision_id, provider)` unique / 主键计数=`0|1|1`，version 列仍 varchar(32)，`change_pct` 仍 nullable。
  两个 PVC 与两个 Secret UID 均未漂移；4 条 capability 的 provider/dataset/revision/status/sample_count 与旧值一致。
  旧 revision/checksum 与 relations/rankings/bars=`846|846|846` 不变，三份 canonical MD5 仍为
  `d101ab8e44276b1b528a76f922355a89` / `0c3cdd23051bd0ec5ee05ca459f42856` /
  `654a769dcb9ca222feb73991069e8bed`；2026-10-14 的 3 runs/11 tasks 状态与哈希不变，2 条 THS operation hash
  仍为 `9daf0cb73301d6c3d490868940e8bb4f`。health、data-collection、THS catalog、core、Chapter 01 sectors 五个
  provider-free GET 均 HTTP 200，调用前后总 run/task/operation 数 `103|246|2` 和全表审计哈希字节等价；无新
  collection/provider operation，manual POST=403，active writer/lease/session 全为 0。7.3 未启用任何写入口或调用 provider。

## Remaining Gaps（剩余缺口）

- `0007` 的短 revision ID、fresh schema、Alembic contract、runtime minimum version、真实 PostgreSQL 16
  完整升级和跨日相同 checksum/相同 `fetched_at` 可并存回归均已通过。不得通过扩大 version 表、篡改
  checksum、伪造 `fetched_at` 或复用跨日 revision 规避。
- 7.1–7.3 已从 clean reviewed HEAD `021071cbb7e3ce87dd59806226642cb916db6d75` 完成 revision 110 复核、
  不可覆盖备份、隔离恢复、生产迁移和不可变镜像发布；同镜像 manual-off、hook-free/orphan schedule disable 及
  all/service manifest-digest 门禁均已实际验收。生产现为 revision 113、v10/0007、writer=0；不得为了验证
  orphan 行为重建 CronJob/Job。
- OpenSpec 6.5–6.7 已完成：manual-off 入口只允许 reviewed full packet 的 literal `1 -> 0`、同镜像、
  `--no-hooks`、schedule absent、每个 retained Job 均有 `Complete=True`/`Failed=True` 终态、stored hooks 与
  PVC/Secret identity 不变，并保留 failed/completed 审计 Job、拒绝 terminating managed resources；普通
  all/service 必须在任何目标访问前绑定
  clean worktree + full reviewed HEAD，导入后冻结 manifest digest，Helm 写前重验并在 Ready Pod 上验证。
- 生产 schema 已由 7.3 受控 migration Job 升至 v10/`0007_ths_catalog_identity`；隔离和生产约束、版本列、nullable
  与历史不变验收均通过。
- 生产现状仍保留固定 `fuyao-ths-catalog-v1` 目录 revision 与 2026-10-14 的 checksum collision/blocked 审计；不得通过改写历史记录消除。
- 任务 7.4 的盘后 provider 写入与 7.5 的调度恢复/跨交易日观察已获授权但仍受自然时间边界约束；至少两个
  完成交易日证据未齐前不得勾选 7.5。
- 7.2 隔离容器 `a-stock-pg-recovery-7-2-20261015T020129Z` 与本地恢复目录继续保留为验证证据；删除它们属于
  独立清理动作，不影响 7.2 验收，也不得为释放空间而擅自销毁。
- 7.1 的 schedule/manual writer 已安全关闭，但 exact failed Kubernetes Job 被 CronJob 删除的默认级联回收；
  该证据不可原样恢复。用户已批准以保留的 PostgreSQL run/task 审计和已捕获 pre-state 作为显式缺口继续。
  schedule disable 入口已改为 hook-free Helm write + orphan-preserving 删除，冻结完整 namespace terminal Job
  集合的 name/UID/计数/终态，并对非终态、读取/删除失败、Job 新增/丢失或漂移 fail closed。不得创建替代 Job
  冒充原证据；旧 Job 的缺口不会因未来门禁补强而消失。

## Next Step（下一步）

保持 CronJob absent、manual=0 和所有 writer=0。等待 2026-10-15 15:10 Asia/Shanghai 结算边界；边界后只在
exact Ready Pod 中执行一次 `snapshots scheduled-refresh --dataset industry-ranking --dataset sector-turnover --dataset
sector-breadth`，由 CLI 自身再次验证结算时间并进入依赖 DAG。完成后核对新 observation revision 与 capability
revision 分离、完整 relation/ranking、bars 与 declared gaps 对账、无零占位、精确诊断和非 generic blocked 下游；
若 provider 或对账失败，保留真实 failed/partial/insufficient 审计并停止，不开启 schedule/manual，也不删除证据。
