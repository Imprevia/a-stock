# 以 Hermes 接管盘后市场数据采集调度

## 目标

将项目内 Kubernetes CronJob 调度替换为 `192.168.1.21` 上的 Hermes Agent 调度，同时由后端继续掌握上海有效日期、结算门禁、七数据集依赖、provider 调用、PostgreSQL 持久化和 lease。新增的全量自动化入口必须幂等、默认关闭，并如实保留 success、partial、failed-retained、failed-missing、blocked 与 busy。

## 范围

包含 OpenSpec `replace-market-collection-scheduling-with-hermes`、后端全量自动化 API 与持久幂等/结构化失败、Hermes caller/prompt、Helm/Kustomize/部署脚本中的 Kubernetes 调度退役、前端兼容、事实文档、离线测试和另行授权的生产迁移。tasks 7.3–7.4 原定义已按独立授权完成；用户随后在首个自然执行前明确把最终定义改为飞书当前会话、工作日 15:30，并保留 30 分钟补跑窗口至 16:00。task 7.5 已授权；该授权不包含主动运行 job/caller、另行要求 provider-write 授权的同日 THS 重采或 task 7.6 停止演练。

## Stage（阶段）

- 当前阶段：**15:30 + 飞书定义已收口，7.5 等待两个完整上海交易日自然执行证据**
- 阶段序列：事实/计划 → 持久化与 API → Hermes 资产 → Kubernetes 调度退役 → UI/文档/离线验证 → 另行授权的生产迁移与两日观察

## Status（状态）

`production-7-5-observing-feishu-15-30`（32/34） · task 7.5 已授权但尚未达到两日验收条件。2026-10-15 17:23 Asia/Shanghai 的观察前基线仍显示原 job 定义为 Weixin/16:30；17:24:50 Hermes 收到飞书入站请求改为当前会话，17:25:15 delivery 落盘，17:26:11 又收到改为 `30 15 * * 1-5` 的请求，17:26:19 schedule 落盘。用户随后明确确认采用飞书当前会话和 15:30，原 30 分钟补跑窗口相应截至 16:00；OpenSpec、caller、专用测试、文档和 runtime 安装均已同步。最终 job 仍未运行，下一次为 `2026-10-16T15:30:00+08:00`，数据库保持 `104 runs / 253 tasks / 1 binding`、无活动 run/task/lease，Kubernetes CronJob/Job absent；task 7.6 仍未授权。

架构、产品规格、仓库指南和 runbook 已在代码前改为 Hermes 持有时钟/投递、后端持有上海日期/结算/七数据集/provider/持久化的合同；full endpoint、持久幂等、structured failure、默认关闭 automation gate、匿名内网边界和两个旧 CronJob identity 的只读负向 guard 已成为实施事实基线。

原 `fix-ths-catalog-revision` 7.5 的 Kubernetes schedule restoration 已被本计划取代；旧任务保持未完成，由本计划 7.3 的 Hermes canary 和 7.5 的两个完整上海交易日证据承接。THS 7.4 的一次盘后定向验证仍是独立前置，不因调度迁移取消。旧 THS 7.1–7.5 授权不自动授权 Hermes automation gate、Hermes job、投递目标或额外同日 provider 重采。

## Acceptance（验收）

- 仓库不再渲染、安装、暂停或激活市场数据 Kubernetes CronJob；普通部署仍对两个旧 CronJob identity fail closed。
- Hermes 以 `Asia/Shanghai` 工作日 15:30 调用受独立开关控制的七数据集全量端点，并投递到已批准的飞书当前会话；16:00 后不补跑。
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
- [x] 完成已授权的任务 7.2：immutable backend/schema 部署与 provider-free 验收
- [x] 完成已授权的任务 7.3：受控 automation gate enable、唯一 key canary 与同 key replay
- [ ] 按最终定义重新收口任务 4.1、4.3、7.4：15:30/16:00 caller、文档、checksum 安装与飞书 job 读回
- [ ] 完成已授权、观察中的任务 7.5：两个完整上海交易日自然执行、通知、读回与 THS lineage
- [ ] 完成尚未授权的任务 7.6：停止演练

## Completion Evidence（完成证据）

- `openspec status --change replace-market-collection-scheduling-with-hermes --json` 显示 proposal/specs/design/tasks 均 planning complete。
- 2026-10-15 计划协调时的部署前 checkpoint 以 production revision 113、v10/0007、manual=0、writer=0、CronJob/Job absent 为当时只读事实；没有执行生产或 Hermes 外部写入。该 checkpoint 后续已由 task 7.2 的 revision 116 / v11/0008 取代。
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
- task 4.1 新增自包含 `scripts/hermes_market_collection.py`：固定调用 `192.168.1.20:32001`，15:30 上海 slot key、16:00
  截止、900 秒首等、一次同 key/零等待不确定重放、只读 status GET 与 600 秒轮询均为确定性状态机；所有输出先归一化，
  不跟随非固定后端或畸形 status URL，也不回显原始异常。注入 transport/fake clock 测试 `21 passed`，无真实网络。
- task 4.2 新增自包含中文 `scripts/hermes_market_collection_prompt.txt` 和七组 caller v1 golden；prompt 只消费
  `hermes-market-collection/v1`，显式分栏 success/partial/failed-retained/failed-missing/blocked/busy/missing，
  批次级 unreachable/rejected/skipped/still-running 不生成 dataset 结果。prompt contract `12 passed`，与 caller
  联合 `33 passed`；golden 明确证明 failed-retained 不计成功、endpoint failure 不伪装为 dataset failure。
- task 4.3 runbook 固定 checksum 强校验安装、`HERMES_HOME/scripts` 路径约束、顶层上海时区、1700 秒 script
  timeout、1800 秒 Agent inactivity timeout、gateway/status、`30 15 * * 1-5`、飞书投递目标、pause/resume/remove 和
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
- **历史阻塞记录（已解除）**：部署脚本审计曾发现 `a-stock-schema-migration` 使用 `post-install,post-upgrade` 和
  `before-hook-creation,hook-succeeded`，只执行 `alembic upgrade head`；legacy SQLite migration 保持关闭。
  但当时的普通 `--component all` 会在 database 和最终 all Helm write 各运行该 schema hook，既违反当时“全程不创建
  Job”的字面验收，也与 runbook 的单次 migration 描述不符。按文档事实源与 fail-closed 要求，task 7.2 当时保持
  未勾选，生产当时仍为 revision 113 / schema v10；后续修复、验证与 revision 116 / schema v11 完成证据见下文。
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
- 新 immutable candidate 使用不修改主分支/主 index 的独立 Git index + detached worktree 冻结：commit
  `6d96224f84e362960332ca89a8e6855e4f1c123f`，worktree
  `/tmp/a-stock-hermes-7-2-candidate-6d96224` clean，私有 `deploy/truenas/deploy.env` 与未跟踪嵌套仓库
  `a-stock/` 均不在 tree；高置信凭据模式扫描为空。image tag 为
  `20261015-150231-6d96224`；专用 values/render SHA-256 分别为
  `7678a5ecd2337c3301d9222640b914093aafe0440ed4c1c3bc7d0f6404757ba1` /
  `5022a86c485ca99fa37805c02c73dff37779c6d7c826eb84db28d98a993c0e3f`。exact candidate 扩展部署回归
  `252 passed`，render 为 manual=0、automation=0、CronJob=0、唯一 schema hook、legacy migration disabled。
- task 7.2 最后只读 preflight 再次证明 revision 113 / schema v10/0007、writer=`0|0|0|0|0`、计数
  `103|246|2|846|846|846`、former CronJob/Job absent、两个 PVC/两个 Secret UID 与 task 7.1 dump SHA-256
  `ef8a7a0b…6677` 全部无漂移，随后才进入发布。镜像 archive SHA-256 为
  `cf2fac201c57dbcc94299b19440e0a9497bc7abc0b22e1b233f6968433296de0`；containerd manifest digest 为
  `sha256:a61f6b1b4d8fb392308af00eaf6765527fa2a9706285cd50eeb9ae29a2bd7e78`。
- revisions 114/115/116 于 15:16–15:17 Asia/Shanghai 依次完成 database/service/final all。唯一 hook
  `a-stock-schema-migration` 的 UID 为 `33aea8df-dff0-4a30-8755-d797f0126b29`，监视器读到 exact image、
  `alembic upgrade head`、唯一 DB URL Secret env、无 volume/mount，并观察 Kubernetes `SuccessfulCreate` 与
  `Completed` events；`hook-succeeded` 随即自动删除。service 与 final all 日志均明确 `hookMode=disabled`，
  最终 stored/live CronJob/Job 均为 0，未发生第二次 hook。
- 生产后验收：schema/Alembic=`11|0008_collection_idempotency`；`collection_idempotency_bindings=0`；
  `collection_tasks.failure_json` nullable=`YES`；manual/automation=`0|0`；writer=`0|0|0|0|0`。GET 前后
  run/task/THS operation 与六项计数均保持 `103|246|2|846|846|846`。task 7.1 dump SHA-256、PVC UID
  `c03bc7f8…/6c426fc5…` 与 Secret UID `81b9d039…/653a79bf…` 不变。
- Deployment `a-stock` → Ready ReplicaSet `a-stock-5f584f6dc5` → Ready Pod `a-stock-5f584f6dc5-4pxpr`
  均使用 exact tag，Pod imageID `sha256:22e58af167e16e42d51bb0352145da7921ea363dcfa8bce66c03adbad7333e3d`
  且 restart=0。health、`/data-collection`、exact-date data-collection、THS catalog、core、Chapter 01 sectors
  与 OpenAPI 均 HTTP 200；OpenAPI full POST 要求 `Idempotency-Key` header、wait maximum 900，且无 request body、
  `asOf`、dataset selector 或 security。验收未发送任何 POST/provider 请求。
- task 7.3 的受控入口补丁冻结为 clean detached candidate
  `5ebe48a15b313969d06be353d9616273730c9113`；automation-on values/render SHA-256 分别为
  `d744ba6bd5ddfcf8f7f8a1c91900c4ff6c70ece610801db3f5554e5703a58086` /
  `d8a3f5aa68406ea9340b7ac27bec1cfdf4f8cfceb77dc3177a3bb3ba18b215f3`，chart SHA-256 为
  `64b95ddee1497f8f23391a414ca3303564b1d66e84fd97cc573514b0dca326fe`。validator/TrueNAS guard
  联合回归 `99 passed`，Shell syntax、Python compile、Helm lint、OpenSpec strict 与 docs-contract full 通过。
- 16:09 的受控 `--enable-automation-refresh` 写入使用 exact 7.2 image
  `localhost/a-stock-market-environment:20261015-150231-6d96224` 与 manifest digest
  `sha256:a61f6b1b4d8fb392308af00eaf6765527fa2a9706285cd50eeb9ae29a2bd7e78`，唯一 Helm write 为
  `--no-hooks --atomic --wait`，revision 117 deployed。写前/写后 active run/task/lease=`0|0|0`，manual=0、
  automation=`0→1`，stored hooks、镜像、两个 PVC/两个 Secret UID 均未漂移，former CronJob/namespace Job absent。
- 16:10 的 canary POST 返回 HTTP 200，run `93dd3c9b633b4cf5bb6d76132e3a5098`、target/asOf
  `2026-10-15`、parent `partial`、`1 binding / 1 run / 7 unique canonical tasks`。success 为 core、breadth、limits；
  partial 为 industry-ranking、sector-turnover、sector-breadth、activeDirection，均保留 warning/diagnostics 和可用结果；
  本批次没有 failed/blocked/busy，故七项 persisted `failure_json` 均为 null，failure contract 校验为 true。
- terminal replay 使用同 key 和 `waitTimeoutSeconds=0` 返回相同 runId、七个 taskId/status/failure。
  binding 的 `submission_attempts=1`、`submitted_at`、`updated_at` 不变；binding/run/tasks/snapshot/materialization
  组合 JSON 的 replay 前后 SHA-256 均为
  `b81cf3b39b0a34a9cb1d0f165cd1305c6ba39f9db8e432a53c04c5be8ec1b62f`。应用 Pod 对公网 80/443 的
  replay 窗口被动抓包排除纯 ACK 后为 `0 packets captured`，证明没有新 SYN 或有效载荷，即零新增 provider 调用。
- task 7.4 使用已批准目标 `weixin:o9cq80-TG0wuvfScOiMEGu2HpX8M@im.wechat`；Weixin adapter 已启用，home channel
  精确匹配，cron delivery 会原样传递 `@im.wechat` chat ID。仓库与安装后 caller SHA-256 均为
  `ab6b994b60a097fccc3159f002975c809910cb9793f784e7e3db16fcf771ef2c`，prompt 均为
  `f981cd0bd0c10e7eeaccb540f33e6ee08081500bbcef9814bcad8ac3b24ca8c2`；安装权限为目录 `0700`、caller `0755`、
  prompt `0644`，installed caller compile 通过。
- Hermes 顶层 timezone=`Asia/Shanghai`、`cron.script_timeout_seconds=1700`、`HERMES_CRON_TIMEOUT=1800`，无冲突
  env override；`hermes config check` 通过。重启采用预期的 graceful drain exit 75，由 `Restart=always` 在 1 分钟后
  自动拉起；最终 `systemctl --user show` 为 loaded/active/running/enabled、PID `3503128`、status 0，进程存活且
  `hermes cron status` 识别 3 个 active jobs。
- Hermes job `ef7389b87a92` 为 active/scheduled，schedule=`30 16 * * 1-5`、relative script=
  `hermes_market_collection.py`、workdir absent、精确 Weixin delivery，`next_run_at=2026-10-16T16:30:00+08:00`；
  `last_run_at`/`last_status` 均为空，未运行 caller/full endpoint。创建前后生产计数均为 `104|253|1|0|0|0`
  （run/task/binding/active run/active task/active lease），health 200，stored/live former CronJob 与全部 Job absent。
- task 7.4 文档收口后 `openspec validate replace-market-collection-scheduling-with-hermes --strict` 与
  `git diff --check` 通过；当前 shell 无 `python` 别名，原命令以 exit 127 未启动，使用同机 `python3`
  执行 `scripts/check-docs-contract.py --mode=full` 通过（代码 68 / 文档 12 / plan 3）。
- task 7.5 获批后的 2026-10-15 17:23 Asia/Shanghai 只读基线：gateway loaded/active/running/enabled，
  PID `3503128`，job `ef7389b87a92` 唯一且 active/scheduled，`last_run_at`/`last_status`/delivery error 均为空，
  `next_run_at=2026-10-16T16:30:00+08:00`；timezone=`Asia/Shanghai`、script timeout=1700、Agent inactivity
  timeout=1800。backend health 200，Helm revision 117 deployed，manual/automation=`0|1`，stored/live former
  CronJob、全部 namespace Job 均 absent；生产 `run|task|binding|active-run|active-task|lease=104|253|1|0|0|0`，
  唯一 binding 仍是 task 7.3 canary，不存在任何自然调度 slot key。该基线没有运行 job/caller 或发送 POST。
- 17:24:50 Hermes gateway 记录一条飞书入站请求，要求把 job `ef7389b87a92` 的 delivery 改为当前会话；
  `jobs.json` 于 17:25:15 更新。17:26 只读复核显示 delivery 已由已批准 Weixin target 漂移为 Feishu target，
  但 schedule=`30 16 * * 1-5`、script、enabled/state、`next_run_at` 均不变，repeat completed=0，
  `last_run_at`/`last_status`/delivery error 为空，job output 文件为 0。该外部修改未触发 caller/full endpoint。
- 17:26:11 Hermes 又收到把 schedule 改为 `30 15 * * 1-5` 的飞书入站请求，17:26:19 `jobs.json` 落盘并把
  `next_run_at` 改为 `2026-10-16T15:30:00+08:00`。操作人随后明确确认采用飞书当前会话与工作日 15:30；为保持
  原 30 分钟恢复窗口，caller 截止相应改为 16:00，slot key 后缀改为 `1530`。
- 最终定义收口后，Hermes 专用 caller/prompt/runbook 回归为 `36 passed`。仓库与 runtime caller SHA-256 均为
  `a4d996d0d68af97e9a34c5c147960d6ff2887c6f0d3150e9448541e3c18ba663`，安装权限 `0755`、compile 通过；prompt
  SHA-256 仍为 `f981cd0bd0c10e7eeaccb540f33e6ee08081500bbcef9814bcad8ac3b24ca8c2`。没有运行 caller/job 或发送 full POST。
- 重新冻结的 7.5 基线：job `ef7389b87a92` active/scheduled，Feishu target、`30 15 * * 1-5`、relative script、
  `next_run_at=2026-10-16T15:30:00+08:00`，repeat completed=0、last run/status/error/delivery error 均为空、output=0；
  gateway loaded/active/running/enabled，backend health 200。Helm revision 117、manual/automation=`0|1`，生产计数
  `104|253|1|0`（run/task/binding/active lease），run/task 均无 queued/collecting；former CronJob=0、Job=0。
- `fix-ths-catalog-revision` 7.5 已改为由本计划 7.5 承接且保持未勾选；7.4 保留为独立盘后验证。
- `openspec validate fix-ths-catalog-revision --strict` 与
  `openspec validate replace-market-collection-scheduling-with-hermes --strict` 均通过。
- fast docs-contract 在只暂存新 plan 与索引时通过（代码 0 / 文档 2 / plan 1）；full docs-contract 覆盖全部当前
  未暂存/新建规划修改并通过（代码 0 / 文档 5 / plan 3）；`git diff --check` 通过。

## Remaining Gaps（剩余缺口）

- task 7.5 已授权并按最终 Feishu/15:30 定义进入观察，进度仍为 32/34；两个完整上海交易日的自然执行、通知、
  provider-free 七项读回和 THS lineage 尚未产生。Hermes 本地状态不能单独证明接收端恰好显示一次通知，需结合
  单一 session/output、gateway delivery 日志和接收端确认。
- 隔离恢复容器 `a-stock-pg-recovery-hermes-7-1-20261015T061531Z` 与本地只读副本
  `/tmp/a-stock-pgdump-20261015T061531Z-helm113-schema10-pvc-6c426fc5-021071c.dump` 保留为恢复证据；清理属于
  单独操作，不是 task 7.1 完成条件。
- THS 7.4 尚待独立完成；Hermes 7.5 的两个交易日证据尚未产生。7.5 中可选的同日 THS 重采仍要求单独
  provider-write 授权，本次授权不包含该操作，也不得用 HTTP replay 替代。
- `fix-ths-catalog-revision` 的一次性 legacy schedule-disable requirement 在其同步为主 spec 后，需要由本 change 在归档前显式退役；在主 spec 尚不存在时不得创建无效的 `REMOVED` delta。

## Next Step（下一步）

从 `2026-10-16T15:30:00+08:00` 起逐日观察两个完整上海交易日，保存 `...-1530` slot key、单一 session/output、
gateway delivery、接收端一次通知、七数据集 provider-free 读回、THS exact-date/same-revision 与跨日不同 revision，
并持续证明 former CronJob/全部 Job absent。本阶段不主动运行 job/caller，不执行 task 7.6 或额外 THS 重采。
