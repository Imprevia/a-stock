# 以 Hermes 接管盘后市场数据采集调度

## 目标

将项目内 Kubernetes CronJob 调度替换为 `192.168.1.21` 上的 Hermes Agent 调度，同时由后端继续掌握上海有效日期、结算门禁、七数据集依赖、provider 调用、PostgreSQL 持久化和 lease。新增的全量自动化入口必须幂等、默认关闭，并如实保留 success、partial、failed-retained、failed-missing、blocked 与 busy。

## 范围

包含 OpenSpec `replace-market-collection-scheduling-with-hermes`、后端全量自动化 API 与持久幂等/结构化失败、Hermes caller/prompt、Helm/Kustomize/部署脚本中的 Kubernetes 调度退役、前端兼容、事实文档、离线测试和另行授权的生产迁移。本轮新增授权只覆盖 task 7.2：部署已审阅的不可变 backend/schema v11，并在 automation/manual 都保持关闭时执行 provider-free 验收；不授权 gate 修改、full endpoint/provider 调用或 Hermes 写入。

## Stage（阶段）

- 当前阶段：**7.2 单次 schema-hook 合同已离线验证，正在重新冻结 immutable candidate**
- 阶段序列：事实/计划 → 持久化与 API → Hermes 资产 → Kubernetes 调度退役 → UI/文档/离线验证 → 另行授权的生产迁移与两日观察

## Status（状态）

`production-7-2-single-schema-hook-validated-awaiting-refreeze`（29/34） · 用户已在 2026-10-15 明确授权 task 7.2。部署前审计发现的 Job-absent/schema-hook 冲突已经协调到 OpenSpec，事实文档、部署脚本与测试也已完成修复：调度/provider-backed collection Job 始终 absent，唯一临时例外是 database 阶段精确的 provider-free `a-stock-schema-migration` hook；service 和最终完整 release 收敛都使用 `--no-hooks`。聚焦与扩展部署测试、Shell 语法、Helm lint、OpenSpec strict、docs-contract full 和 diff 检查均通过；旧候选 `291a8de` 已失效，正在重新冻结候选。生产仍为 revision 113 / schema v10，尚未恢复镜像导入、Helm 或数据库写入。automation/manual 继续关闭，不调用 full POST/provider，不写 Hermes。

架构、产品规格、仓库指南和 runbook 已在代码前改为 Hermes 持有时钟/投递、后端持有上海日期/结算/七数据集/provider/持久化的合同；full endpoint、持久幂等、structured failure、默认关闭 automation gate、匿名内网边界和两个旧 CronJob identity 的只读负向 guard 已成为实施事实基线。

原 `fix-ths-catalog-revision` 7.5 的 Kubernetes schedule restoration 已被本计划取代；旧任务保持未完成，由本计划 7.5 的 Hermes canary 与两个完整上海交易日证据承接。THS 7.4 的一次盘后定向验证仍是独立前置，不因调度迁移取消。旧 THS 7.1–7.5 授权不自动授权 Hermes automation gate、Hermes job、投递目标或额外同日 provider 重采。

## Acceptance（验收）

- 仓库不再渲染、安装、暂停或激活市场数据 Kubernetes CronJob；普通部署仍对两个旧 CronJob identity fail closed。
- Hermes 以 `Asia/Shanghai` 工作日 16:30 调用默认关闭、受独立开关控制的七数据集全量端点；17:00 后不补跑。
- 同一 schedule-slot key 的重放复用同一 persisted run，断线、202 轮询和进程重启不创建重复批次或 provider 调用。
- 七数据集状态和结构化失败可由 provider-free GET 读回；partial/failed-retained/failed-missing/blocked/busy 不被改写为成功。
- 两个完整上海交易日内，THS ranking/turnover/breadth 每日保持 exact-date/same-revision 血缘，不同日期使用不同 date-addressed catalog observation revision。
- 若仍需生产证明 THS 同日真实重采幂等，必须另获 provider-write 授权；仅当完整 catalog 内容不变时要求复用同一 observation revision，不能以 same-key HTTP replay 冒充该证据。
- 仓库与生产均不得创建 Kubernetes CronJob 或 scheduling/provider-backed collection Job。另行授权的 backend/schema rollout 仅允许精确的 provider-free `a-stock-schema-migration` hook 在 database 阶段执行一次，service 与最终完整 release 收敛使用 `--no-hooks`；成功后全部 Job 再次 absent。hook 失败时停止后续收敛并保留 failed Job 与安全诊断证据，task 7.2 不得报告完成。
- 后端/前端/部署/Hermes 测试、OpenSpec strict、全量 docs-contract 与 `git diff --check` 通过，或明确登记真实阻塞。

## 实施任务

- [x] 完成任务 1.1：active plan 建立、索引登记和 fast docs-contract 验证
- [x] 完成任务 1.2：按本 change packet 重做只读生产发现
- [x] 完成任务 1.3：在代码前同步架构、产品、仓库指南和 runbook
- [x] 完成任务 1.4：协调 THS/Fuyao 历史计划、状态和索引
- [x] 完成任务 2.x–3.x：持久幂等、结构化失败和 sync-first 全量 API
- [x] 完成任务 4.x：确定性 Hermes caller、中文 prompt 与安装/运行说明
- [x] 完成任务 5.x：退役项目内调度创建/激活路径并保留旧资源负向检测
- [x] 完成任务 6.1：前端结构化失败兼容与桌面/390px 状态显示
- [x] 完成任务 6.2–6.3：事实文档与聚焦离线验证
- [x] 完成任务 6.4：全量 pytest、规则检查、OpenSpec strict 与 docs-contract full
- [x] 完成任务 7.1：生产只读基线、不可覆盖 PostgreSQL 备份和隔离恢复演练
- [ ] 完成已授权的任务 7.2：immutable backend/schema 部署与 provider-free 验收
- [ ] 完成尚未授权的任务 7.3–7.6：canary、Hermes job、两日观察与停止演练

## Completion Evidence（完成证据）

- `openspec status --change replace-market-collection-scheduling-with-hermes --json` 显示 proposal/specs/design/tasks 均 planning complete。
- 2026-10-15 计划协调以 production revision 113、v10/0007、manual=0、writer=0、CronJob/Job absent 为当前只读事实；没有执行生产或 Hermes 外部写入。
- 2026-10-15 task 1.2 现场只读复核：k3s `v1.26.6+k3s-6a894050-dirty`、release `a-stock/a-stock`
  revision 113 deployed；stored manifest 仅含 Deployment/PVC/Service/StatefulSet，CronJob/Job 和两个 exact
  name 都为 0；live CronJob/Job 列表为空；Deployment/PostgreSQL 均 1/1；manual=0；active
  lease/run/task/THS operation/non-idle session=`0|0|0|0|0`。查询未输出 Secret，也未产生外部写。
- task 1.3 已同步 `docs/architecture.md`、产品规格、repository guide 与 runbook；文档固定
  `POST /api/market-environment/collection-runs/full`、`MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED`、
  七数据集、200/202、持久幂等、structured failure、Hermes `192.168.1.21` → backend
  `192.168.1.20:32001` 匿名内网边界，以及两个历史 CronJob identity 的 read-only fail-closed guard。
- task 2.1 新增 Alembic `0008_collection_idempotency` / runtime schema v11：只增加
  `collection_idempotency_bindings`、两个查询索引和 nullable `collection_tasks.failure_json`，downgrade
  不删除证据。migration/schema/UoW/sector focused：`17 passed, 1 skipped`；skip 是未配置隔离 PostgreSQL
  环境的既有 integration，新增 SQLite 隔离 upgrade/backup/restore 回归已证明 v10 run/task 历史字节值不变。
- task 2.2 新增 full-collection semantic fingerprint、严格 idempotency key、binding/claim/submission state、
  structured task failure 与 repository/UoW ports；fingerprint 明确排除 wait preference，safe failure 会脱敏 URL
  credential、Authorization、token/password/secret/api key。值对象与端口回归：`14 passed`。
- task 2.3 新增 PostgreSQL idempotency repository，在一个 savepoint/外层 UoW 中创建 run、固定七 task 与
  key binding；唯一约束竞争返回 replay/conflict 并回滚 losing run/tasks。串行、跨日冲突和双线程 concurrent
  first claim 均证明 `1 run / 7 tasks / 1 binding`；相关 bootstrap/UoW/ports 回归 `23 passed, 1 skipped`。
- task 2.4 为兼容 store 与 PostgreSQL task repository 增加持久化 structured failure codec，并在 coordinator
  的 acquisition、Fuyao preflight、dependency、concurrency、lease fence、未分类异常和 worker restart 转换点
  写入稳定分类；success/partial 保持 `failure=null`，warning、THS diagnostic、timings 与 dataset detail 不丢失。
  SQLite 文件重启与 split repository 重建测试覆盖 success、partial、failed-retained、failed-missing、blocked、
  busy、worker-interrupted，相关采集/存储/core committer/THS DAG 联合回归 `69 passed`。
- task 2.5 新增持久 submission owner/recovery window：capacity rejection 先释放 queued-task leases 并落
  `submission-failed`，过期 `submitting`/`submitted` 仅在无 live task lease 时接管原 run；claimed task 在提交前补齐
  Fuyao preflight 与 dataset/date leases，过期同-owner lease 以新 fencing generation 接管，worker 启动时 parent
  `queued → collecting`，旧 collecting/no-lease 固化为 worker-interrupted，且 parent 只在所有 tasks terminal 后结算。
  PostgreSQL 与进程内 executor 不声称跨崩溃严格 exactly-once enqueue；单 live owner、同 run 安全重投以及
  task CAS/fencing 保证无重复 provider commit。submission/coordinator/repository 联合回归 `46 passed`。
- task 3.1 新增独立 `MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED`，运行时、Helm、Kustomize 与保留的
  TrueNAS profiles 全部默认关闭，且不改变 manual refresh 值；settings 与全部部署清单回归
  `208 passed, 1 warning`。
- task 3.2 新增 `FullCollectionCommand`：使用 `Asia/Shanghai` 解析服务端日期，周末与结算前均在 UoW、查询、
  identifier 和 submission 前返回，15:10 边界放行；固定七数据集语义、原子 claim/replay/conflict、原 run
  recoverable submission 和 provider-free 持久状态轮询均由 fake clock 覆盖。
- task 3.3 新增默认等待 900 秒的 `POST /api/market-environment/collection-runs/full`；必填
  `Idempotency-Key`，只暴露 0–900 秒 `waitTimeoutSeconds`，终态返回 200，活动态返回 202 与
  `Location`/`Retry-After`/`statusUrl`。OpenAPI 证明无 request body、`asOf`、dataset selector、credential 或
  security requirement。
- task 3.4 新增 full run/skipped 判别 envelope，并把同一 persisted structured failure 映射到手工 async POST、
  run GET、exact-date status 与 full POST；success/partial 保持 `failure=null`。3.2–3.4 聚焦 API/command/schema
  联合回归 `54 passed, 1 warning`，额外 command/bootstrap/repository 回归由实现审查运行 `57 passed, 1 warning`。
- task 3.5 endpoint 场景回归覆盖七项全成功、mixed partial/failure、全失败 HTTP 200、THS blocked、lease busy、
  failed-retained/failed-missing、周末和结算前零 I/O、client disconnect 后独立 worker 继续，以及 202 后协调器
  重启并通过 provider-free GET 读取终态；新增测试 `11 passed, 1 warning`，相关联合回归 `65 passed, 1 warning`。
- task 3.6 幂等集成覆盖 serial/concurrent/terminal/restart/uncertain replay、同 key 跨日期和 operation version conflict、
  不同 key 同日 lease 以及 executor rejection；matching replay 始终是同一 run/一次 submission，每个数据集 provider
  计数恰为 1，capacity rejection 释放七个 lease 后由重启进程恢复原 run。新增测试 `5 passed`，与 command、
  PostgreSQL idempotency 和 coordinator 联合回归 `60 passed`。
- task 3.7 访问边界回归证明 automation=1/manual=0 时仅 full POST 可匿名内网调用，automation=0 在 command、run、
  provider、wait 和 status 前阻断；OpenAPI 无 security scheme，幂等键描述明确不是身份凭据，busy/lease 为 HTTP 200
  concurrency 业务结果且无认证 header。相关 full/API 回归 `39 passed, 1 warning`。
- task 4.1 新增自包含 `scripts/hermes_market_collection.py`：固定调用 `192.168.1.20:32001`，上海 slot key、17:00
  截止、900 秒首等、一次同 key/零等待不确定重放、只读 status GET 与 600 秒轮询均为确定性状态机；所有输出先归一化，
  不跟随非固定后端或畸形 status URL，也不回显原始异常。注入 transport/fake clock 测试 `21 passed`，无真实网络。
- task 4.2 新增自包含中文 `scripts/hermes_market_collection_prompt.txt` 和七组 caller v1 golden；prompt 只消费
  `hermes-market-collection/v1`，显式分栏 success/partial/failed-retained/failed-missing/blocked/busy/missing，
  批次级 unreachable/rejected/skipped/still-running 不生成 dataset 结果。prompt contract `12 passed`，与 caller
  联合 `33 passed`；golden 明确证明 failed-retained 不计成功、endpoint failure 不伪装为 dataset failure。
- task 4.3 runbook 固定 checksum 强校验安装、`HERMES_HOME/scripts` 路径约束、顶层上海时区、1700 秒 script
  timeout、1800 秒 Agent inactivity timeout、gateway/status、`30 16 * * 1-5`、投递目标、pause/resume/remove 和
  授权后人工测试。对 Hermes v0.12.0 本机只读 `--help` 与源码审计确认 `HERMES_CRON_TIMEOUT` 会随活动刷新，
  不是总 deadline；caller/prompt/runbook contract 联合 `35 passed`，未执行任何 Hermes 写命令。
- task 6.1 为前端 collection 类型增加结构化 failure，并让页面优先显示持久化的安全 `failure.message`、无该字段时
  回退旧 `warning`；Vitest 覆盖 failed-retained、failed-missing、blocked、busy、partial 以及 390px 布局，聚焦
  `collection-api.test.ts` 与 `data-collection-view.test.ts` 为 `23 passed`。
- tasks 5.1–5.5 已删除 Helm CronJob template、native scheduled overlay、所有 scheduling values/baseline、
  schedule component、release/activate/disable modes、正向 packet validator 与 CLI `scheduled-refresh`；普通
  `all/database/service` 在 build/Helm write 前后只读检查 stored manifest、release-derived former identity 和
  legacy `market-data-collection`。active、suspended、label drift 与任何 Helm/kubectl 不确定状态均 fail closed，
  且仓库无 CronJob patch/delete/create 路径。默认 Chart、四个 retained TrueNAS profile、base Kustomize、
  Scrapling/Fuyao profile 均离线证明不含 CronJob。
- task 6.2 已同步 README、AGENTS、architecture、product spec、repository guide、runbook、TrueNAS guide、status
  与 active plan：当前态仅提供 Hermes/full endpoint、独立 automation gate、匿名内网风险、非破坏停止与两个
  former identity 负向 guard；旧 schedule 命令只保留在明确的历史审计区。Hermes prompt 的版本化文件为
  `scripts/hermes_market_collection_prompt.txt`，caller 为 `scripts/hermes_market_collection.py`。
- task 6.3 聚焦验证：后端 collection/API/PostgreSQL/idempotency/migration `155 passed, 1 warning`（Starlette
  既有弃用警告）；调度退役 render/validator/legacy guard/CLI `251 passed`；Hermes caller/prompt/runbook
  `35 passed`；前端 Vitest `145 passed`；Vite production build 成功，仅既有大 chunk warning。全部为 fake、
  fixture、临时存储或离线 render；未访问真实 provider、生产 PostgreSQL、Kubernetes API 或 Hermes 主机。
- task 6.4 全量离线门禁：`.venv/bin/python -m pytest tests -q` 为
  `1432 passed, 6 skipped, 1 warning in 346.05s`；skip 为需要外部/隔离依赖的既有条件跳过，warning 为
  Starlette `BlockingPortal` alias 的既有弃用提示。rules validate=`49`、coverage/docs sync=
  `330 documented / 49 executable`；OpenSpec strict 通过；docs-contract full 通过（代码 68 / 文档 12 / plan 3）。
- task 7.1 于 2026-10-15 完成。备份前两次只读复核确认 k3s `v1.26.6+k3s-6a894050-dirty`、Helm
  revision 113 deployed、stored manifest 只有 Deployment/PVC/2 Service/StatefulSet，两个 former CronJob
  identity、全部 live CronJob/Job 与 active writer 均不存在；Deployment/PostgreSQL 1/1，manual=0，当前旧版本
  尚无 automation env，schema=`10|0007_ths_catalog_identity`，writer=`0|0|0|0|0`，关键计数为
  `103|246|2|846|846|846`。PVC UID `6c426fc5-10e2-4e88-b534-b258c70869c4`、provider Secret UID
  `81b9d039-7d77-44bc-9c4f-41b9ce2e19b2` 与 PostgreSQL Secret UID
  `653a79bf-a881-43de-8623-2d9f69e9aa0f` 均与冻结基线一致，未读取或输出 Secret 内容。
- task 7.1 备份已发布到
  `/mnt/xiaomi/app-builds/a-stock/a-stock-pgdump-20261015T061531Z-helm113-schema10-pvc-6c426fc5-021071c.dump`：
  custom format、`2,879,102` bytes、SHA-256
  `ef8a7a0b3f40b539ac552f8e59a208032db7035d3a898f0517a346b3c5156677`，`pg_restore --list` SHA-256
  `7ac5b68759f6580d2bea57ba1fc75d2053af4d7755ed5ad654710f6efe01bacd`；dump、`.sha256` 和 `.manifest`
  sidecar 均为 mode 0400，manifest 不含凭据。
- 同一字节副本在全新容器 `a-stock-pg-recovery-hermes-7-1-20261015T061531Z` 中使用本机既有、未 pull 的
  `docker.m.daocloud.io/library/postgres:16.4`（image ID `6b14e73a48cf…69ef10`）恢复；容器
  `--network none`、无 published port，空库先证明 public table=0，再以
  `pg_restore --single-transaction --exit-on-error --no-owner --no-acl` 于 `06:17:55Z`–`06:18:09Z`
  恢复 39 张 public 表。恢复后 schema/alembic 和六项关键计数分别为
  `10|0007_ths_catalog_identity` 与 `103|246|2|846|846|846`，与生产备份前完全一致。
- `06:19:04Z` 生产后置只读复核再次确认 Helm 113、schema v10/0007、manual=0、automation env absent、
  writer=`0|0|0|0|0`、stored/live CronJob/Job absent、关键计数与 PVC/Secret UID 全部未变；没有部署、
  provider I/O、collection run 或 Kubernetes workload 写入。
- task 7.2 获授权后的部署前只读复核再次确认 revision `113|deployed`、schema/Alembic
  `10|0007_ths_catalog_identity`、manual=`0`、automation env absent、writer=`0|0|0|0|0`、关键计数
  `103|246|2|846|846|846`、stored/live 两个 former CronJob identity 与全部 CronJob/Job absent；两个 PVC 与
  两个 Secret UID、task 7.1 dump SHA-256 均与冻结基线一致。没有执行 POST、provider、Helm 或数据库写入。
- 已冻结 clean candidate `291a8debb15fcbe55f0ccd379b5dd162532aa230` 与 task 7.2 专用 manual-off values；values
  SHA-256 `fcb22ec18d9afe4e02efa350f0f065d026d67975f5346371f3685d1ac9b5a63d`，render SHA-256
  `23259033557ca3fa3a04ce95637e87e8e7ad0bd97e6f91b903d397208d2c5469`。render 为 manual=`0`、
  automation=`0`、CronJob/former identity=`0`；相对 revision 113 的 values 差异仅为新 image tag、显式
  automation=false 与删除退役的 disabled `scheduledCollection`。
- 部署脚本审计发现阻塞：`a-stock-schema-migration` 使用 `post-install,post-upgrade` 和
  `before-hook-creation,hook-succeeded`，只执行 `alembic upgrade head`；legacy SQLite migration 保持关闭。
  但普通 `--component all` 会在 database 和最终 all Helm write 各运行该 schema hook，既违反当前“全程不创建
  Job”的字面验收，也与 runbook 的单次 migration 描述不符。按文档事实源与 fail-closed 要求，task 7.2 保持
  未勾选，生产仍为 revision 113 / schema v10。
- OpenSpec proposal、scheduling delta spec、design 与 task 7.2 已协调单次 hook 合同：允许精确的 provider-free
  `a-stock-schema-migration` 在 database 阶段执行一次，legacy SQLite migration 关闭，service/final all 均
  `--no-hooks`；成功后全部 Job absent，失败则停止并保留 failed Job/安全诊断。旧候选 `291a8de` 因不满足该
  合同已 superseded，不得部署。
- `scripts/deploy-truenas-k3s.sh` 已把 database 固定为唯一 hook-enabled Helm write，把 service 与 final all 固定为
  `--no-hooks`；database/full render 只允许一个与 reviewed release 同 fullname 的 schema Job、精确命令
  `alembic upgrade head`、唯一 DB URL env、无 legacy SQLite mount。部署在起始、每个 Helm write 前及成功后
  fail closed 地要求 namespace Job absent；database Helm 失败在后置 absence check 前返回，不删除 failed Job，
  也不会进入 service/final 收敛。
- 单次 hook 聚焦 guard/manifest 回归为 `191 passed in 29.50s`；扩展 deployment/scheduling/Fuyao/Scrapling
  profile 回归为 `252 passed in 34.09s`。`bash -n scripts/deploy-truenas-k3s.sh`、
  `helm lint --strict deploy/helm/a-stock`、OpenSpec strict、docs-contract full（代码 68 / 文档 12 / plan 3）和
  `git diff --check` 均通过；全部为离线/fake/render 检查，未访问生产或 provider。
- `fix-ths-catalog-revision` 7.5 已改为由本计划 7.5 承接且保持未勾选；7.4 保留为独立盘后验证。
- `openspec validate fix-ths-catalog-revision --strict` 与
  `openspec validate replace-market-collection-scheduling-with-hermes --strict` 均通过。
- fast docs-contract 在只暂存新 plan 与索引时通过（代码 0 / 文档 2 / plan 1）；full docs-contract 覆盖全部当前
  未暂存/新建规划修改并通过（代码 0 / 文档 5 / plan 3）；`git diff --check` 通过。

## Remaining Gaps（剩余缺口）

- task 7.2 的合同、脚本、测试与离线门禁已完成，仍需冻结并审计新 immutable candidate、复核生产无漂移、
  执行 backend/schema rollout 和 provider-free 验收；完成前保持 29/34。tasks 7.3–7.6 仍未授权，不得启用 automation gate、调用 full endpoint/provider、
  写 Hermes 主机、创建 Hermes job、选择/修改投递目标或执行 provider 重采。
- 隔离恢复容器 `a-stock-pg-recovery-hermes-7-1-20261015T061531Z` 与本地只读副本
  `/tmp/a-stock-pgdump-20261015T061531Z-helm113-schema10-pvc-6c426fc5-021071c.dump` 保留为恢复证据；清理属于
  单独操作，不是 task 7.1 完成条件。
- THS 7.4 尚待独立完成；Hermes 7.5 的两个交易日和可选同日重采证据均未产生。
- `fix-ths-catalog-revision` 的一次性 legacy schedule-disable requirement 在其同步为主 spec 后，需要由本 change 在归档前显式退役；在主 spec 尚不存在时不得创建无效的 `REMOVED` delta。

## Next Step（下一步）

使用独立 Git index 与 detached worktree 重新冻结当前已验证源码，生成新的唯一 image tag、task 7.2 专用
manual=0/automation=0 values 和 render hash，并在 exact candidate 上复跑关键门禁。随后只读证明生产 revision 113、
备份 checksum、writer/Job/CronJob/PVC/Secret/计数无漂移，再执行已授权的 task 7.2 provider-free rollout；不得沿用
本授权到 gate 修改、canary、Hermes 写入或 provider 调用。
