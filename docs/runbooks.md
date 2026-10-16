# Runbook

## 下一交易日对照与多页看板（2026-09-14）

`GET /api/market-environment/next-session?as_of=YYYY-MM-DD` 只读本地精确交易日证据。排查时先确认 `trading_sessions` 存在严格大于请求日期的下一真实交易日，再检查该日核心指数和 materialized aggregate；缺失应保持 `pending`/`insufficient` 并记录 warning。该请求不得调用 provider、不得用自然日加一、不得回退旧日期。页面 01 和 09 共用该接口，普通研究页仍不承担采集职责。

复盘句式为临时展示与复制内容，不写入 PostgreSQL；不要添加保存按钮、复盘记录表或 20 日训练进度状态。03、04、07 的未接入证据继续显示真实 `unverified`/`insufficient`。

## AI 市场数据 v2 读取、排错与回滚（2026-10-16）

AI 或自动化客户端先读取 `GET /api/v2/market-environment/YYYY-MM-DD/overview`，保存 body 的 `snapshotRevision` 与响应 ETag，再按 `links` 请求一个细粒度资源。后续调用用 revision 前置条件固定同次研究会话；缓存探测使用 `If-None-Match`。分页只跟随响应 `pagination.nextCursor`，并保持原资源、日期、筛选和排序不变；收到 409 时丢弃旧 cursor，以响应中的当前 revision 从 overview 重启，不能把新旧页拼接。

列表限制：limits pool、sector observation/ranking、active-direction 默认 20/最大 100；index/breadth/limits history 默认 60/最大 250；operation checkpoints 默认 50/最大 200。THS catalog/bars 仍使用既有 `page`/`page_size` 合同，bars 单页不得超过 1000。不得通过并发猜 cursor、`fields`/`include`、SQL-like filter 或嵌套 expansion 绕过 closed OpenAPI contract。

PostgreSQL keyset 首页没有 cursor 时，repository 必须使用不含 cursor predicate、也不绑定 `after_*` 的独立 SQL；不得用 `:after_exchange IS NULL OR (...)` 携带无类型 `NULL`，否则 psycopg/PostgreSQL 会在执行前以 `AmbiguousParameter` 拒绝查询。后续页才绑定三个非空文本 cursor 分量，并继续按 `(exchange, code, security_id)` 严格大于比较。排查 pool 首页 500/网关 503 时，先直连 Ready Pod 核对 traceback，再分别请求首页和 `nextCursor` 后续页；这两类 GET 必须保持 provider-free、write-free。

排错按状态码和 quality 分流：

- `304`：revision 对应资源未变化，无 body；继续使用本地已缓存值。
- `404`：该 exact date 没有任何受支持本地证据；先检查本地 snapshot/aggregate 状态，不运行 provider 来修复 GET。
- `409`：revision precondition 或 cursor 已过期；重新取 overview，并整组重启本次多资源读取。
- `422`：日期格式/未来日期、未知 index/pool/selector、limit 越界或 cursor 格式不合法；按 `/openapi.json` 修正请求。
- `503` 且 `error.code=snapshot_integrity_error`：本地行存在但 checksum 或 key、payload、actual/effective date 不一致；保存请求路径、日期、应用 image、精确 row key 与脱敏 revision/checksum 引用，停止把该行作为证据。GET 不会也不得触发 provider、采集、重标、删除或数据库修复；不要将其当成 404，也不要回退 legacy 或其他日期成功数据。
- `200` 且 `quality.status=missing|insufficient|degraded|failed-retained|failed-missing`：这是证据状态，不用 0、空成功、旧日期或最新 provider 结果替换；保留 source/provider/observation/warning/freshness。

`GET /llms.txt` 用于紧凑发现，`GET /llms-full.txt` 用于完整接入说明，两者均为 UTF-8 `text/plain` 并链接 `/openapi.json`。它们不承载实时行情。若 discovery 与 OpenAPI 路径、参数、operation id、响应 model 或 limit 不一致，先视为发布阻断并运行确定性 drift tests；不得手改运行时生成文件或把生产响应复制进文档。

验证 v2 时只使用本地 fixture/测试数据库和离线测试：断言 provider 构造/调用、collection start/join、background task 与 write count 均为零；不得用真实 provider smoke、生产 NodePort、生产 PostgreSQL 或部署写来证明 GET 正常。回滚为移除 v2/discovery route 注册并让 dashboard 切回 legacy caller；不删除 PostgreSQL、snapshot、aggregate、run/task/checkpoint，不改 provider gate，不执行 migration，也不改 Hermes/部署配置。legacy 未版本化路径在整个迁移期必须保持可读。

### Core 跨日期完整性审计与受控前向修复

只读审计先在隔离 fixture/恢复库验证，再由单独获批的生产计划执行。审计只选择 `snapshot_entries(dataset='core')` 与 `materialized_market_environment` 的 key、payload `asOf`、quality `asOf/effectiveAsOf`、各指数 history 最后一日、checksum/revision 引用；不得打印数据库 URL、完整 payload、provider header 或凭据。审计必须使用只读事务并证明 write count 为零。

仓库内的 `audit_core_date_integrity(connection)` 只执行两条有界 `SELECT`，返回 snapshot/aggregate row identity、日期证据、checksum/component revision 和指数尾日，不返回完整行情 payload。先在隔离恢复库调用并保存脱敏结果；测试 `tests/test_market_environment_integrity_audit.py` 固定 SQL 全为 `SELECT` 且审计前后表行数不变。生产调用仍属于单独获批计划，不是本 change 自动执行的命令。

若发现错位，当前 change 只报告，不自动处置。生产前向修复必须另建 active plan并取得明确授权，顺序固定为：冻结 manual/automation writers 并确认无 active run/task → 完成 PostgreSQL 可恢复备份并记录目标 row key/checksum → 审阅目标日期是否已有合法成功证据和冲突 → 发布已通过离线门禁的修复版本 → 仅在 provider 能证明同一目标日期时显式重新采集 core 并通过 fenced commit/aggregate rebuild 前向覆盖 → 验证 v2 overview、legacy core、run/task、checksum/revision 与 writers 状态。禁止自动 relabel、跨日期 copy、直接编辑 payload/checksum、静默删除历史、删除 PVC、未经授权调用 provider 或用 GET 修复。

当坏 existing 本身会使普通 committer 的留存读取失败时，只能在上述门禁全部满足后使用维护 CLI：

```bash
python -m src.market_environment.cli snapshots refresh \
  --as-of YYYY-MM-DD --dataset core --force --repair-integrity
```

`--repair-integrity` 必须与 `--force`、唯一 `--dataset core` 和单日模式同时出现；它不允许 limits history、多数据集、HTTP 或 Hermes 调用。提交前仍完整验证 candidate 日期，并要求 core outcome 及五个 index result 全部 `success`、无 retained payload；否则不覆盖坏 existing。获批 replacement 在 active lease/fence 内写入 snapshot、task/index/session，并由同一任务重建 aggregate。异常路径必须把无 lease 的旧 task 标为 `worker-interrupted` 并结算 parent run，不得直接 UPDATE 目标 snapshot/aggregate 或把失败 run 改成成功。

发布后只读 smoke 不再只检查 `/api/health`：还要请求一个已知合法历史日期的 v2 overview（预期 200），请求 effective date 的 v2 overview、indices/history 和 legacy core，并按现场事实接受 200、无证据 404/missing 或稳定 503 `snapshot_integrity_error`；任何 500、跨日期 200 或 GET 触发写入均阻断发布。PostgreSQL 可选日期/cursor 参数必须显式 cast，真实 PostgreSQL smoke 需覆盖无 cursor 首页。该 smoke 不授权真实 provider、采集、数据库修复或部署写。

## 环境要求

- Python 3.11+（建议使用仓库 `.venv`）
- Node.js 18+ 与 npm
- git
- 可选：GitHub Actions（仓库 CI）
- 可访问通达信 TCP 和腾讯/百度 HTTPS 行情接口的网络
- 运行时数据库为 PostgreSQL（SQLAlchemy 2 + psycopg 3）；开发/生产必须设置 `MARKET_ENVIRONMENT_DATABASE_URL`。SQLite 仅供一次性导入工具使用，迁移输入可放在 `.artifacts/market-environment/snapshots.sqlite3`

安装依赖：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install --prefix apps/market-environment-dashboard
```

`requirements.txt` 同时安装部署文档安全测试使用的 CommonMark 与 Bash AST 解析器；不要在只安装部分依赖的环境中把命令审计结果作为发布证据。

## 启动命令

启动后端 API：

```bash
python -m uvicorn src.market_environment.api:app --reload --port 8001
```

启动前端开发服务器（另开终端）：

```bash
npm run dev --prefix apps/market-environment-dashboard
```

浏览器访问 `http://localhost:5173`；生产构建后可由 FastAPI 从 `apps/market-environment-dashboard/dist` 托管静态文件。

本机开发默认使用 8001，避免与常见的 CLodop 打印服务占用的 8000 端口冲突；Vite 会将 `/api` 代理到 `http://127.0.0.1:8001`。容器内 API 端口和 k3s Service 仍为 8000，不受此本机开发配置影响。

## k3s 部署

仓库根目录的 `Dockerfile` 使用 Node 构建前端，再将 `dist` 与 Python API 放入同一个非 root 运行镜像。构建并推送固定版本镜像：

```bash
docker build -t registry.example.com/a-stock/market-environment:2026.09.02 .
docker push registry.example.com/a-stock/market-environment:2026.09.02
```

将 `deploy/k3s/kustomization.yaml` 的 `images.newName` 和 `newTag` 改为集群可拉取的地址与固定版本，然后部署 Dashboard 基础资源；该 base 不包含 CronJob：

```bash
kubectl apply -k deploy/k3s
kubectl -n a-stock rollout status deployment/market-environment-dashboard --timeout=180s
kubectl -n a-stock get pods,pvc,service,ingress
```

k3s 单节点也可不使用镜像仓库，将默认名称的镜像直接导入节点。多节点集群必须导入每个可能调度 Pod 的节点，或改用共享镜像仓库：

```bash
docker build -t a-stock-market-environment:latest .
docker save a-stock-market-environment:latest | sudo k3s ctr images import -
kubectl apply -k deploy/k3s
```

默认 Ingress 使用 k3s 内置 Traefik 的 `web` 入口且不限定 Host，可通过任一节点 IP 访问；正式环境应增加域名、TLS 和证书配置。服务必须允许访问通达信 TCP 与腾讯、百度、新浪、东方财富 HTTPS 行情源。Deployment 默认单副本，因为当前 PostgreSQL 为单主、refresh lease/事务 fencing 与 provider limiter 仍是有界单主边界；不要直接增加副本数。

PostgreSQL StatefulSet 独占 `a-stock-postgresql-data` Retain RWO PVC（默认挂载 `/var/lib/postgresql/data`）；Dashboard Deployment 不挂载任何数据库 PVC。删除数据库 PVC 会破坏运行时状态，执行任何存储操作前必须完成 PostgreSQL 逻辑备份/物理备份并记录 PVC UID；旧 SQLite PVC 只能由迁移 Job 只读挂载并保持归档。

发布检查、日志和回滚：

```bash
curl "http://<k3s-node-ip>/api/health"
kubectl -n a-stock logs deployment/market-environment-dashboard --tail=200 -f
kubectl -n a-stock describe deployment market-environment-dashboard
kubectl -n a-stock rollout history deployment/market-environment-dashboard
kubectl -n a-stock rollout undo deployment/market-environment-dashboard
```

`/api/health` 不访问外部行情源，只用于容器启动、就绪和存活检查。健康检查成功但行情接口返回 503 时，应继续按 provider 网络和降级 warning 排查，而不是重启 Pod。不要用 `kubectl delete -k deploy/k3s` 作为回滚；它可能移除应用资源且不负责数据库恢复。回滚应用应使用相同 release 的 atomic upgrade/受审 rollback image，PostgreSQL 数据通过备份恢复或前向修复处理，禁止删除 PVC。

### 生产盘后自动采集契约（Hermes 所有权）

项目内 Kubernetes 调度已进入退役合同：Helm、Kustomize 和 TrueNAS values 不得渲染、安装、暂停或激活
application-owned market-data CronJob，也不再提供 `scheduledCollection`、schedule component、
`--release-suspended`、`--activate-schedule`、`--disable-schedule` 或 `scheduled-refresh`。历史文档中的
revision 26/70/106/107、`enabled=true` 和 `suspend=false` 仅是审计记录，不是可恢复的当前操作说明。

盘后时钟由 `192.168.1.21` 上的 Hermes Agent 持有：顶层 `timezone` 或
`HERMES_TIMEZONE=Asia/Shanghai`，cron 为 `30 15 * * 1-5`，摘要投递到已批准的飞书当前会话。Hermes 的版本化 pre-run caller 调用
`POST http://192.168.1.20:32001/api/market-environment/collection-runs/full`，不选择日期、数据集或
provider；后端固定七数据集并按上海日期与结算边界决定执行。漏跑只允许在不晚于 16:00 时用相同 schedule-slot
key 补偿，之后跳过并通知。第一版无交易所节假日日历；周末返回无 run/provider I/O 的 `skipped`，工作日
节假日必须保留真实失败/留存状态，不能用其他日期补齐。

端点合同：

- `MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED` 默认关闭且只控制 full endpoint；生产可在
  `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` 时单独开启它。
- `Idempotency-Key` 必填。同 key、同服务端日期/operation version/固定 dataset fingerprint 原子复用一个
  PostgreSQL run；wait timeout 不进入 fingerprint；同 key、不同语义返回 409。
- request wait 默认且最多 900 秒；terminal `success`/`partial`/`failed` 返回 HTTP 200；仍运行返回
  HTTP 202、`Location`、`Retry-After` 和 provider-free `statusUrl`。客户端断开不取消后台任务。
- 每个 task 暴露 nullable `failure.category/message/retryable/retained`；`failed-retained` 不算本次成功，
  `failed-missing`、`blocked`、`busy` 与 worker interruption 不得合并成通用 warning。
- 该内网接口不鉴权。开启后，任何能路由到 `192.168.1.20:32001` 的客户端都能调用；幂等、CORS、
  前端按钮和 lease 都不是访问控制。Hermes 不获得 PostgreSQL/Secret/PVC/provider/deployment 权限。

#### Hermes v0.12.0 caller、prompt 与 job 安装（仅在 7.x 获得外部写授权后执行）

仓库事实资产为 `scripts/hermes_market_collection.py` 和
`scripts/hermes_market_collection_prompt.txt`。caller 只输出一行 `hermes-market-collection/v1` 规范化 JSON；
prompt 只负责分类和中文投递。安装前在受审 checkout 记录两份源文件 SHA-256，并在 `192.168.1.21` 上把
安装后的 hash 与它们逐项比较。`HERMES_HOME` 必须先解析为该主机上的明确绝对目录；以下 `/home/hermes/.hermes`
和 `/srv/a-stock` 只是需要由操作人确认的示例，不得直接猜测：

```bash
cd /srv/a-stock
caller_sha256="$(sha256sum scripts/hermes_market_collection.py | awk '{print $1}')"
prompt_sha256="$(sha256sum scripts/hermes_market_collection_prompt.txt | awk '{print $1}')"

export HERMES_HOME=/home/hermes/.hermes
install -d -m 0700 "$HERMES_HOME/scripts"
install -m 0755 /srv/a-stock/scripts/hermes_market_collection.py "$HERMES_HOME/scripts/hermes_market_collection.py"
install -m 0644 /srv/a-stock/scripts/hermes_market_collection_prompt.txt "$HERMES_HOME/scripts/hermes_market_collection_prompt.txt"
test "$caller_sha256" = "$(sha256sum "$HERMES_HOME/scripts/hermes_market_collection.py" | awk '{print $1}')"
test "$prompt_sha256" = "$(sha256sum "$HERMES_HOME/scripts/hermes_market_collection_prompt.txt" | awk '{print $1}')"
python -m py_compile "$HERMES_HOME/scripts/hermes_market_collection.py"
```

Hermes v0.12.0 会拒绝解析到 `HERMES_HOME/scripts` 之外的 `--script`，包括路径穿越、外部绝对路径和逃逸
symlink；job 因而只使用相对值 `--script hermes_market_collection.py`。不要把仓库 checkout 路径、数据库脚本或
provider 工具作为 pre-run script。

调度时区必须用顶层 `timezone`（推荐）或 gateway 进程的 `HERMES_TIMEZONE`，不能写不存在的嵌套
`cron.timezone`。pre-run caller 最长可能经历 930 秒首请求和 600 秒状态轮询，故 script timeout 至少为
1700 秒。Hermes v0.12.0 的 `HERMES_CRON_TIMEOUT` 是 **Agent 无活动超时**：有 stream/tool 活动时计时会刷新，
它不是严格的总 job deadline，也不得在验收中这样声称。建议配置如下；环境变量文件位置必须通过 CLI 查询后
由操作人审阅编辑：

```bash
hermes --version
hermes config path
hermes config env-path
test "$(hermes config path)" = "$HERMES_HOME/config.yaml"
test "$(hermes config env-path)" = "$HERMES_HOME/.env"
hermes config set timezone Asia/Shanghai
hermes config set cron.script_timeout_seconds 1700
# 在 `hermes config env-path` 返回的文件中设置：HERMES_CRON_TIMEOUT=1800
hermes config check
hermes gateway restart
hermes gateway status --deep
hermes cron status
```

也可在 gateway 的受审 service environment 使用 `HERMES_TIMEZONE=Asia/Shanghai` 与
`HERMES_CRON_SCRIPT_TIMEOUT=1700`，但不能同时留下相互冲突的 config/env 值。变更配置和重启 gateway 都是
`192.168.1.21` 上的外部写，离线实现阶段只验证命令形态，不执行。

Hermes v0.12.0 help 接受 `origin`、`local`、`telegram`、`discord`、`signal` 或明确的
`platform:chat_id`。生产 `<approved-delivery-target>` 应优先选择并验证明确的 `platform:chat_id`；裸 platform
只有在对应 home channel 已配置时才可使用。CLI 创建不会捕获聊天 origin，`origin` 可能回退到首个可用 home
channel，不能在未核实目标时使用；`local` 只保存结果、不外发，不满足生产通知验收。提示词是 `create` 的第二个
位置参数，`--script` 只传相对 caller 文件名；Hermes 会把 caller stdout 注入该提示词。不要给 Agent HTTP、
provider、数据库、部署工具或项目 `--workdir` 上下文：

```bash
export HERMES_HOME=/home/hermes/.hermes
HERMES_PROMPT="$(cat "$HERMES_HOME/scripts/hermes_market_collection_prompt.txt")"
hermes cron create '30 15 * * 1-5' "$HERMES_PROMPT" \
  --name a-stock-after-market-collection \
  --deliver '<approved-delivery-target>' \
  --script hermes_market_collection.py
hermes cron list --all
hermes cron status
```

创建输出中的 job ID 记入 `HERMES_JOB_ID`。`hermes cron list --all` 必须显示 schedule `30 15 * * 1-5`、已批准的
Feishu delivery、相对 script 和带 `+08:00` 语义的下一次上海工作日 15:30 `next_run_at`；gateway 不健康、时区不符、
hash 不符或 automation gate 未按 7.x 单独授权时不得触发。

离线检查和只读连通检查不会调用 provider：

```bash
python -m pytest tests/test_hermes_market_collection.py tests/test_hermes_market_collection_prompt.py -q
curl --fail --silent --show-error http://192.168.1.20:32001/api/health
hermes gateway status --deep
hermes cron list --all
```

`python "$HERMES_HOME/scripts/hermes_market_collection.py"` 或 `hermes cron run "$HERMES_JOB_ID"` 会调用 full endpoint，
只能在 automation gate 已获授权、上海结算后且不晚于 16:00 的 canary/人工验证窗口执行；同一 slot 的人工重放
必须沿用 caller 生成的相同 key，不能改脚本生成第二个批次。非破坏停止、恢复和删除命令为：

```bash
export HERMES_JOB_ID='从 create 输出记录的 job ID'
hermes cron pause "$HERMES_JOB_ID"
hermes cron list --all
# 仅在另行授权恢复时：hermes cron resume "$HERMES_JOB_ID"
# 仅在明确决定移除定义时：hermes cron remove "$HERMES_JOB_ID"
```

暂停 job 后还要独立关闭 backend automation gate；两者都不得恢复 Kubernetes CronJob、删除 collection
history、snapshot、idempotency binding、PostgreSQL 数据或 PVC。

普通部署继续只读、fail closed 地检查历史资源，且不提供清理或激活能力。检查顺序：

1. `helm get manifest <release> -n <namespace>` 必须不含 CronJob kind，也不得出现 release-derived
   `a-stock-data-collection` 或 legacy `market-data-collection` metadata name。
2. `kubectl get cronjob -n <namespace> a-stock-data-collection market-data-collection --ignore-not-found`
   必须为空；任一 active 或 suspended resource 都阻断 build/Helm write/application rollback。
3. `kubectl get jobs -n <namespace>` 用于保存现场审计；普通部署不得创建 scheduling/provider-backed
   collection Job，也不得删除或重建 Job 来“证明”退役。另行授权 backend/schema rollout 的唯一临时例外
   是下文定义的精确 `a-stock-schema-migration` hook。
4. 遗留资源处置需要独立 plan、冻结 stored/live 证据和明确授权；重新引入 Kubernetes scheduling 必须另立
   OpenSpec change，不能作为 Hermes 故障时的自动回滚。

非破坏停止路径是暂停/删除 Hermes job 并关闭 automation gate；保留 run/task/idempotency/snapshot、
PostgreSQL history 和 PVC。服务版本回滚使用受审不可变镜像，不回滚到含历史 CronJob 的 Helm revision。

### 扶摇行业 fallback 盘后验证与回滚（2026-09-29）

行业 fallback 的服务基址固定为 `https://fuyao.aicubes.cn`，仅使用扶摇公开的同花顺行业指数组合：

```text
GET /api/a-share/calendar/trading-days
GET /api/a-share-index/catalog/ths-index-list?tag=industry
GET /api/a-share-index/prices/snapshot?thscodes=<comma-separated-thscodes>
```

真实 probe 只能在上海盘后、显式授权的隔离环境运行。命令必须先把当前时间归一到
`Asia/Shanghai`，并在构造 provider/client 或创建 JSON/SQLite 输出前同时证明：请求日期等于当前
effective market date、该日期为工作日、当前时间不早于 `MARKET_ENVIRONMENT_SETTLEMENT_TIME`。
15:09、日期不匹配或周末必须零 provider 请求、零输出文件，并且没有 `--force` 绕过。先确认东方财富
`push2` 与 `push2delay` 的失败证据已记录，再从独立 Secret 注入
`MARKET_ENVIRONMENT_FUYAO_API_KEY`，执行带明确日期的 probe；不要把 key 放进命令行参数、
values、shell history 或日志。probe 必须脱敏输出 endpoint、请求日期、交易日历命中、目录数量、
快照覆盖、批次时间一致性、字段覆盖、权限和限流结果；当前已知探针覆盖 320 个行业目录和
320 个行情快照。报告中不得出现 API key、Authorization header、完整响应或凭据派生值。

```bash
# 离线先验证报告结构；此命令不访问网络
python -m src.market_environment.cli fuyao capability-probe \
  --fixture tests/fixtures/market-environment/fuyao-market-data.json \
  --as-of YYYY-MM-DD --path /tmp/fuyao-capability.sqlite3

# 仅在盘后隔离环境、已获授权时运行真实探针；不得写正式 sectors 快照
python -m src.market_environment.cli fuyao real-probe --allow-real \
  --as-of YYYY-MM-DD --path /tmp/fuyao-real.sqlite3 \
  --output /tmp/fuyao-real.json
```

批准 revision 只能在离线契约与当次脱敏 real probe 通过后进入受审报告晋升流程；隔离 SQLite
中的报告本身不能打开正式运行时门禁，旧 `fuyao-market-v1` 证据也不能批准 v2。生产 revision 87
不包含 promotion CLI，因此必须先以 sectors-off 状态发布受审新镜像，不能直接从旧 Pod 晋升，也
不能先启用 sectors。以下六步分别保留审计证据；任一步失败都停止，不得跳序：

1. **冻结 packet 并 off-first 预发布**：只从 clean reviewed HEAD 构建一次不可变镜像。生产 packet
   至少绑定 `reviewedHead`、chart SHA-256、off/enabled values SHA-256、off/enabled render SHA-256、
   release、namespace、实际 Kubernetes version 和 image repository/tag/manifest digest。受控入口在
   首次网络、构建或目标写入前校验这些绑定、chart 不含 scheduling values/template、两个历史 CronJob
   identity 在 stored/live state 都 absent，以及 sectors-off；dirty source、hash 漂移、候选已启用 sectors、enrichment/shadow/Scrapling/其他
   Fuyao 数据集开启或任一 application CronJob 存在时 fail closed。完整 sectors-off release 发布后，
   核对 exact Deployment→ReplicaSet→Ready Pod owner chain、tag/imageID/containerd digest、应用和
   PostgreSQL 健康、Secret 引用、PVC UID/PV/容量、两个 exact CronJob 与 namespace Job absent；此步
   不运行 provider、promotion 或 collection。

   ```bash
   bash scripts/deploy-truenas-k3s.sh \
     --env-file /secure/path/fuyao-sectors-packet.env \
     --stage-sectors-off \
     --off-values deploy/truenas/values-fuyao-sectors-off.yaml \
     --enabled-values deploy/truenas/values-fuyao-sectors-enabled.yaml \
     --kube-version "$EXACT_K3S_VERSION" \
     --release-name "$RELEASE_NAME" --namespace "$NAMESPACE"
   ```

   `fuyao-sectors-packet.env` 是 operator-owned 审核输入，必须包含受审 HEAD、chart、两份 values、两份
   render、image repository/tag 的绑定值；stage 只构建和导入一次镜像，并在任何 Helm write 前从目标
   containerd 的 exact tag 冻结 manifest digest。该文件不得提交，也不得包含 provider 或数据库凭据。

   `component=all` 在完整 release 收敛后必须停止；仓库不再接受 schedule component。revision 91/92 曾用
   `--repair-sectors-off-release` 修复历史 schedule-only partial release，该一次性操作已完成且被 revision 113
   的完整 release/两个 CronJob absent 状态取代。该 flag 与 schedule component 同步退役，不是当前恢复入口；
   再发现类似 stored/live drift 时必须停止并建立新的受审处置计划，不能复制历史命令。
2. **盘后隔离 probe**：仅在上述 pre-I/O 时间门禁通过后运行 real probe。使用权限受限的新目录保存
   SQLite 与 JSON，记录 JSON envelope 文件 SHA-256，并人工核对 canonical checksum、
   `provider=fuyao`、`dataset=sectors`、`revision=fuyao-market-v2`、`status=eligible`、请求/日历/
   快照日期一致、320 个唯一目录与 320 个唯一快照及 1.0 覆盖率、同日批次时间、四个支持字段
   完整、五个不支持字段明确缺失、权限已配置以及 `0 < requestsUsed <= requestBudget`。标准脱敏后
   结构必须完全不变；任一不满足就保留失败证据并停止。
3. **exact Pod stdin promotion**：受控入口先解析唯一 Ready application Pod，证明它运行步骤 1 的
   frozen image、sectors 为 `0`、PostgreSQL URL 仍来自既有 Secret、两个 exact CronJob absent，且
   本地报告 SHA-256 未变；随后才允许以下受控入口。入口内部只把脱敏 envelope 送入 exact Pod 的
   stdin，不使用
   `kubectl cp`、Pod 临时文件、TTY、`sh -c` 或宿主数据库 URL。先 dry-run，审阅单行选择、masked
   backend 和 conflict state，再对完全相同的文件显式 apply：

   ```bash
   REVIEWED_REPORT_PATH=/secure/path/fuyao-real.json
   bash scripts/deploy-truenas-k3s.sh \
     --env-file /secure/path/fuyao-sectors-packet.env \
     --promote-sectors-capability \
     --off-values deploy/truenas/values-fuyao-sectors-off.yaml \
     --enabled-values deploy/truenas/values-fuyao-sectors-enabled.yaml \
     --report "$REVIEWED_REPORT_PATH" \
     --kube-version "$EXACT_K3S_VERSION" \
     --release-name "$RELEASE_NAME" --namespace "$NAMESPACE"

   # 仅在 dry-run 输出和同一 envelope SHA-256 已复核后执行
   bash scripts/deploy-truenas-k3s.sh \
     --env-file /secure/path/fuyao-sectors-packet.env \
     --promote-sectors-capability --apply \
     --off-values deploy/truenas/values-fuyao-sectors-off.yaml \
     --enabled-values deploy/truenas/values-fuyao-sectors-enabled.yaml \
     --report "$REVIEWED_REPORT_PATH" \
     --kube-version "$EXACT_K3S_VERSION" \
     --release-name "$RELEASE_NAME" --namespace "$NAMESPACE"
   ```

   `--input -` 只接受一个 JSON envelope；空、畸形或多文档输入统一脱敏拒绝且零写入。apply 只允许
   repository/UoW 在一个事务中写入所选 `provider_capability_reports` 行；同 checksum 幂等，同
   revision 不同 checksum 冲突退出。完成后核对 checksum 及 capability 行 before/after，并证明
   snapshots、collection runs、aggregates、其他 capability rows、开关和调度均未变化。
4. **same-image config-only enable**：只在匹配 eligible report 已读回后，用步骤 1 的 exact frozen image
   和受审 enabled profile 发布完整 release。该入口必须使用 hook-free Helm upgrade，不 build/save/copy/
   transfer/import 镜像，不运行 migration、Helm hook 或 provider-backed Job；写入前 live/desired 语义
   diff 只能是 `MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED: "0" -> "1"`。image、approved revision、
   Secret、PVC、Service、replica topology、调度和其他环境值任一变化都在 Helm write 前拒绝。发布后
   证明 Deployment/Pod 健康、image identity/PVC/Secret 不变、matching capability 可读、两个 CronJob
   和 Job absent，enrichment/Scrapling/shadow/其他 Fuyao 数据集仍关闭。

   ```bash
   bash scripts/deploy-truenas-k3s.sh \
     --env-file /secure/path/fuyao-sectors-packet.env \
     --enable-sectors-config \
     --off-values deploy/truenas/values-fuyao-sectors-off.yaml \
     --enabled-values deploy/truenas/values-fuyao-sectors-enabled.yaml \
     --kube-version "$EXACT_K3S_VERSION" \
     --release-name "$RELEASE_NAME" --namespace "$NAMESPACE"
   ```
5. **历史一次 sectors collection 证据**：该步骤已于 2026-10-09 通过当时存在的
   `snapshots scheduled-refresh --dataset sectors` 完成，只保留为审计事实。`scheduled-refresh` 与公共 `sectors`
   数据集现已退役，不得复制该历史命令或恢复 CronJob。新的采集验证只允许走当前七数据集 command/API 合同，
   并须取得对应的 provider-write 授权。
6. **条件 config-only off rollback**：任一 rollout 或观察失败时，使用步骤 1 的 exact same frozen image
   与受审 off profile 走同一个 hook-free config-only full-release 入口。写入前唯一允许差异是 sectors
   enabled flag `"1" -> "0"`；禁止 build/import、裸 Helm、`kubectl patch`、历史 Helm rollback、
   release uninstall 或删除资源。回退后确认 Eastmoney 双失败恢复同日期 `failed-retained`/
   `failed-missing` 和 provider-free GET，保留 capability report、同日快照、任务历史、Job、Secret 和
   PVC，不得跨日期回填或手工 SQL 修改 payload。

   ```bash
   bash scripts/deploy-truenas-k3s.sh \
     --env-file /secure/path/fuyao-sectors-packet.env \
     --disable-sectors-config \
     --off-values deploy/truenas/values-fuyao-sectors-off.yaml \
     --enabled-values deploy/truenas/values-fuyao-sectors-enabled.yaml \
     --kube-version "$EXACT_K3S_VERSION" \
     --release-name "$RELEASE_NAME" --namespace "$NAMESPACE"
   ```

promotion 不调用 provider，不创建 collection run，不写 snapshot/aggregate，不修改 Secret、调度、
enabled flag 或 approved revision。off-first、promotion、enable、collection 和条件 off 必须分别记录
实际 packet/hash/server-observed 证据；授权本身不能替代任何前置门禁或写后验收。

### THS 目录 observation revision 冲突处置（2026-10-14）

出现 `conflicting THS catalog revision checksum`，或 `industry-ranking` 失败后
`sector-turnover` / `sector-breadth` 显示依赖阻塞时，先把它视为目录身份与每日行情可用性耦合事故，停止
人工重复触发。固定 `fuyao-ths-catalog-v1` 是 capability revision，只批准接口/schema/权限/预算；新的目录
观察身份对外保持 opaque，语义为
`<provider>:<capabilityRevision>:<YYYY-MM-DD>:sha256:<full-catalog-checksum>`。checksum 必须来自行情对账前
四类完整 `(tag, thscode, name)` 关系，不能因当日 OHLC/volume/turnover 或 `changePct` 为空而裁剪目录。

事故期间禁止删除旧 revision、修改旧 checksum、重标旧 success/failed/blocked attempt、把缺失数值补 0、
裁剪关系或用其他日期数据替代。身份/日期缺失、重复或冲突继续 fail closed；在场但值为空的行分别进入
`missingLiveCodes` / `missingRankingCodes`。诊断 warning 允许使用
`THS_DIAGNOSTIC_V1 {"reasonCode":...,"message":...}`，但只能包含有界 code 样本、计数、日期、revision、
retryability 和 `blockedBy`；不得写 credential、签名 URL、敏感 header 或 raw provider payload。旧纯文本和
无法解析的 envelope 必须原样展示，不得为兼容性改写历史。

本修复包含一个窄范围 migration：数据库目标为 schema version 10，Alembic head 为
`0007_ths_catalog_identity`；该 migration 仅删除 `ths_catalog_revisions` 上不含交易日的
`UNIQUE (provider, capability_revision, checksum, fetched_at)`，不改写历史行。任何发布前先只读核对当前
release/image、两个历史 CronJob identity、active writer、PVC/Secret、schema、capability、旧 fixed revision、
排名/bar 和失败/blocked 审计。2026-10-15 revision 113 是本 change 发布前只读基线；task 7.3 完成后当前为
revision 117 / schema v11/0008，两个 CronJob 和全部 Job absent、manual=0、automation=1 且没有活动 writer；
不得为补证重建 Kubernetes schedule。

后续生产恢复已由 `replace-market-collection-scheduling-with-hermes` 7.x 接管。2026-10-15 tasks 7.1–7.4 已完成：
不可覆盖备份和 immutable backend/schema 部署、独立 automation gate、唯一 key 盘后 canary/replay，以及 approved
Weixin delivery、checksum 一致 caller/prompt 和 Hermes job `ef7389b87a92` 均已有证据。job 使用
`30 16 * * 1-5`、`Asia/Shanghai`、1700 秒 script timeout 与 1800 秒 Agent inactivity timeout，下一次为
`2026-10-16T16:30:00+08:00`；创建后未执行 caller/full endpoint，生产仍为 revision 117、manual=0、automation=1、
活动 writer=0、Kubernetes CronJob/Job absent。下一步仅在另行授权后观察两个完整上海交易日；旧 THS 7.1–7.5
授权不自动授权主动运行 job、停止演练或额外同日 provider 重采，任一步健康或数据对账失败即停止。

上述 Weixin/16:30 是 task 7.4 首次创建时的历史证据。首个自然执行前，操作人最终确认改为飞书当前会话与
`30 15 * * 1-5`；保留原 30 分钟补跑窗口，因此 caller 使用 `15:30` slot key（后缀 `1530`）并在 16:00 后跳过。
仓库与 runtime caller SHA-256 均为
`a4d996d0d68af97e9a34c5c147960d6ff2887c6f0d3150e9448541e3c18ba663`，job 下一次为
`2026-10-16T15:30:00+08:00`，投递为 `feishu:oc_3a44907a83cd2d8f7f588716e7a09d3d`；job 仍未运行，
生产 run/task/binding 计数与 Kubernetes CronJob/Job absence 未漂移。

### Fuyao THS 目录、K 线与成员导入（2026-10-12，离线实现与隔离 probe）

Fuyao 动态接口索引为 `https://fuyao.aicubes.cn/llms-full.txt`（最后核对：
2026-10-12）。它是动态更新的接口发现和契约核对入口，不是 capability 批准、数据权利证明或生产
写入授权。仓库已实现下述同步、回填、导入、本地查询和三数据集编排，但所有新 capability 开关默认关闭；
本 change 已于 2026-10-12 15:21（Asia/Shanghai）在隔离临时目录执行一次真实 probe；未执行 capability apply/promotion、生产迁移、首次正式数据写入、部署或调度激活。probe 结果：`sector-membership`（203 个成员）和 `sector-turnover-history`（24 根 K 线）通过脱敏 evidence policy 审阅；`industry-ranking` 因真实快照存在缺少 `changePct` 的 `883401.TI` 行而为 `ineligible`；daily/incremental/adjustment dump 元数据未提供 SHA-256，均为 `ineligible`。这些状态不得被手工改写为 `eligible`。

隔离 probe 命令（只在上海结算后、显式授权、临时输出路径执行；API key 仅从 Secret/环境注入，不写命令行或文件）：

```bash
python -m src.market_environment.cli fuyao ths-real-probe \
  --as-of YYYY-MM-DD --thscode 886042.TI --history-start YYYY-MM-DD \
  --max-dump-bytes 536870912 --output /tmp/fuyao-ths-report.json \
  --path /tmp/fuyao-ths-evidence.sqlite3 --allow-real
```

  - 2026-10-12 23:44（10.2 落地）盘后真实 probe 复审 `cli fuyao ths-real-probe --as-of 2026-10-12 --thscode 886042.TI --history-start 2024-10-12 --max-dump-bytes 536870912` 在 `/tmp/fuyao-ths-report-20261012.json`：catalog (`fuyao-ths-catalog-v1`, `industry-ranking`, 845/845 行) / membership (`fuyao-ths-membership-v1`, 203 人) / history (`fuyao-ths-history-v1`, 484 根 K 线) 三份 report 在 `changePctCoverage=1.0`、`changePctMissingTags=[]`、`requiredFieldsComplete=true`、`checksum` 满足下为 `eligible`；三 dump 仍 `ineligible`（SHA-256 缺失）。未触动 production PG / Helm / Secret / PVC / 调度 / CronJob，未执行 capability apply 或 promotion。

  - 2026-6-10-13 09:18（10.9 落地）`pg_dump` + 隔离 PostgreSQL 恢复演练：本地 dev box 通过 `ssh admin@192.168.1.20 → sudo k3s kubectl exec -n a-stock a-stock-postgresql-0 -- pg_dump -Fc -Z 9 --no-owner --no-privileges` 生成 dump，落到 `admin@192.168.1.20:/tmp/a-stock-pgdump-20261013.dump`，`kubectl cp` + `scp` 拉回 `/tmp/a-stock-pgdump-20261013.dump`（2,400,447 字节、sha256 `1723b24c…3ee5`）；本地起 `a-stock-pg-recovery-1791854545`（`docker.m.daocloud.io/library/postgres:16.4`，端口 55432，独立卷 `/tmp/a-stock-pgdata-1791854545`，DB `a_stock_recovery`），`pg_restore --single-transaction --clean --if-exists --exit-on-error` 0 error 完成 39 表恢复。`schema_migrations` v4–v8 全 apply、`provider_capability_reports` 仍仅 `fuyao/sectors/fuyao-market-v2` 1 行、11 张新 THS 表 schema 均存在但行数 0。未触动 production PG / Helm / Secret / PVC / 调度 / CronJob。隔离 PG 容器保留运行供 10.3 后行差对照。

  - 2026-10-13 09:54（10.3 落地）capability apply：本 change 的 capability promotion 必须从生产 Pod 镜像内跑 CLI（dev box 无 PG 直连，PG 5432 仍是 ClusterIP；Pod `/app/src/market_environment` 不在镜像默认 PYTHONPATH），通过 `ssh admin@192.168.1.20 → sudo k3s kubectl cp /tmp/fuyao-ths-report-20261012.json a-stock/a-stock-57b65c5bc6-ggt62:/tmp/fuyao-ths-report-20261012.json`（md5 `4b108bb1…f83c` 两端一致）把脱敏 envelope 放进 Pod 内 `/tmp` emptyDir（**不进 PVC**），再 `sudo k3s kubectl exec -n a-stock a-stock-57b65c5bc6-ggt62 -- bash -lc "cd /app && PYTHONPATH=/app/src python3 -m market_environment.cli capabilities promote"` 跑三条 CLI。三份 dry-run 全部 `result=validated, conflictState=absent, targetBackend=postgresql+psycopg://***@a-stock-postgresql:5432/a-stock`，exit 0；加 `--apply` 全部 `result=applied, mode=apply`，exit 0。生产 PG 行差对照 = 4 行（`fuyao|industry-ranking|fuyao-ths-catalog-v1|eligible|845|1|2026-10-12 15:44:17`、`fuyao|sector-membership|fuyao-ths-membership-v1|eligible|203|1|2026-10-12 15:44:17`、`fuyao|sectors|fuyao-market-v2|eligible|10|1|2026-10-09 12:00:00`、`fuyao|sector-turnover-history|fuyao-ths-history-v1|eligible|484|1|2026-10-12 15:44:17`），对比 10.9 隔离 PG baseline 仅多 3 行，旧 `fuyao/sectors/fuyao-market-v2` 行 `sample_count=10 / checked_at=2026-10-09 12:00:00` 未变（option (a) 承诺兑现）。Pod env 镜像前后对比（落 `/tmp/a-stock-podenv-{pre,post}state-20261013.txt`）：`MARKET_ENVIRONMENT_THS_WRITES_AUTHORIZED=0`、六个 `_THS_*_ENABLED=0`、三个 `_THS_*_REVISION=""` 与 `_FUYAO_SECTORS_ENABLED=1/APPROVED_REVISION=fuyao-market-v2` 全不变；Pod `restartCount=0`、Deployment 1/1 Ready、PVC UID `6c426fc5-…` 不变、Helm release rev 98 未动、CronJob 仍 absent；未触动任何 Secret、API key 与外发端口。离线验证：聚焦 THS/capability/fuyao 161 passed（focused set 14 个测试文件，45.63s）；`openspec validate --strict` 通过；`check-docs-contract --mode=full` 通过（代码 11 / 文档 5 / plan 1）；`git diff --check` 全过。日志落 `/tmp/a-stock-dryrun-*` + `/tmp/a-stock-apply-*` + `/tmp/a-stock-pgdiff-caps-20261013.txt`。10.4 起的 env 升级与小批采集必须按 plan 10.x "每步独立授权"继续等待用户复述才能动。
报告只能通过 `capabilities promote` 的受审路径做 dry-run/apply；本次 eligible membership/history 报告尚未 apply 到生产 PostgreSQL，原因是 9.2 的 clean reviewed commit、备份恢复演练、migration 和镜像冻结尚未满足。adjustment 永远保持 `ineligible`，直到事件推导公式、事件顺序和前收盘证据冻结。

  - 2026-10-13 10:28（10.4 落地）Helm release 升级：本 step 仅翻转 Pod env 中的 THS gate + 子数据集开关，**不**重建镜像、**不**写库、**不**触发采集、**不**激活 CronJob、**不**调 provider。Pre-state：`ssh admin@192.168.1.20 → sudo /usr/local/bin/helm get values + helm get manifest + kubectl get pvc/pods -o yaml` 落 `/tmp/a-stock-10.4-helm-values-pre-20261013.txt` + `/tmp/a-stock-manifest-pre-20261013.yaml` + `/tmp/a-stock-pvc-pre-20261013.yaml` + `/tmp/a-stock-pods-pre-20261013.yaml`（chart `tar -C deploy/helm/ -czf /tmp/a-stock-chart.tgz a-stock/` MD5 与 remote 校验一致）。Audit packet：新建 `deploy/truenas/values-ths-capabilities-on.yaml` 完整镜像 live release values + 仅 `marketEnvironment.fuyao.ths` 新增（`writesAuthorized: true`、`catalog.enabled: true/revision: fuyao-ths-catalog-v1`、`membership.enabled: true/revision: fuyao-ths-membership-v1`、`history.enabled: true/revision: fuyao-ths-history-v1`、`dumps.{daily,incremental,adjustment}Enabled: true`），保持图像 tag `20261012-172238-c53705f`、Secret 引用 `a-stock-market-provider`、PVC `a-stock-data + a-stock-postgresql-data`、`sectors.enabled: true, approvedRevision: fuyao-market-v2`、`scheduledCollection.enabled: false, suspend: true`；本地 `helm template` 渲染 `/tmp/a-stock-manifest-desired-10.4-20261013.yaml` 与 live 仅有 10 处 env 值差异（`THS_WRITES_AUTHORIZED 0→1`、六个 `_THS_*_ENABLED 0→1`、三个 `_THS_*_REVISION ""→revision`）、其它 line-for-line 一致。Helm 执行：`sudo /usr/local/bin/helm upgrade a-stock /tmp/a-stock -n a-stock --kubeconfig /etc/rancher/k3s/k3s.yaml --values /tmp/values-ths-capabilities-on.yaml --no-hooks --atomic --wait --timeout 5m`，先 `--dry-run` 校验无钩子 `Happy Helming`，再 `--atomic --wait` 真实 upgrade，Helm release 98 → 99。后置验证：`kubectl exec a-stock-776d4bf97c-zt9ss -- env | grep MARKET_ENVIRONMENT` 落 `/tmp/a-stock-10.4-podenv-poststate-20261013.txt`：`THS_WRITES_AUTHORIZED=1` + 六个 `_ENABLED=1`（CATALOG/MEMBERSHIP/HISTORY/DAILY_DUMP/INCREMENTAL_DUMP/ADJUSTMENT_DUMP）+ 三个 `_REVISION` 与 10.3 capability revision 完全对齐，`FUYAO_SECTORS_ENABLED=1/APPROVED_REVISION=fuyao-market-v2` 保留；`helm get manifest` pre→post diff 仅 10 处 env 变化（落 `/tmp/a-stock-manifest-post-20261013.yaml`），其它 line-for-line 一致；`helm get values` 仅新增 `marketEnvironment.fuyao.ths` 块（落 `/tmp/a-stock-10.4-helm-values-post-20261013.txt`）；Dashboard `1/1 Ready`、dashboard pod `a-stock-776d4bf97c-zt9ss` 0 重启、PostgreSQL 0 重启、PVC UID `a-stock-data=c03bc7f8-…` 与 `a-stock-postgresql-data=6c426fc5-…` 未变；`schema_migrations` v4-v8 `applied_at` 仍是 `2026-10-12 09:34:56`（`--no-hooks` 未触发 schema-migration Job）；`provider_capability_reports` 行差仍是 4 行（10.3 三新增 + 旧 `fuyao/sectors/fuyao-market-v2` 保持）；`/api/health` HTTP 200、`/api/market-environment/ths/catalog` 仍返回空 catalog（首次 sync 未执行）；`MARKET_ENVIRONMENT_FUYAO_API_KEY` 仅来自 Secret、不进入 values/manifest；CronJob 仍 absent、`scheduledCollection.enabled=false/suspend=true` 保留。离线：聚焦 THS/capability 套件 88 passed、`vitest 139 passed`、`openspec validate --strict` 通过、`check-docs-contract --mode=full` 通过、`git diff --check` 全过。10.5–10.8 必须按 plan 10.x "每步独立授权"顺序继续等待用户复述才能动；清理隔离 PG 容器仍需用户复述。
  - 2026-10-13 10:59（10.5 dry-run 落地，apply 待盘后）catalog sync dry-run：dev box 经 `ssh admin@192.168.1.20 → sudo k3s kubectl exec -n a-stock a-stock-776d4bf97c-zt9ss -- bash -lc "cd /app && PYTHONPATH=/app/src python3 -m market_environment.cli ths catalog-sync --as-of 2026-10-13 --capability-revision fuyao-ths-catalog-v1 --membership-capability-revision fuyao-ths-membership-v1 --membership-thscode 886042.TI --request-budget 60"` 跑 dry-run（不加 `--apply`）。CLI stdout 单行 JSON `{"asOf":"2026-10-13","formalWrites":0,"membershipCodes":1,"operation":"catalog-sync","providerCalls":0,"status":"planned","warning":"dry-run only; --apply requires manual-write, settlement, permission, budget, and capability gates"}`、exit 0；dry-run 路径不调用 provider、不写库、只输出 planned payload。Pre-state 抓取：pod 镜像仍是 `20261012-172238-c53705f`、Pod env 注入 10 个 THS 标志（落 `/tmp/a-stock-10.5-podenv-20261013.txt`：`MARKET_ENVIRONMENT_THS_WRITES_AUTHORIZED=1` + 6 个 `_THS_*_ENABLED=1` + 三个 `_THS_*_REVISION` 与 10.3 capability revision 对齐、`MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1`、`MARKET_ENVIRONMENT_SETTLEMENT_TIME=15:10`），Helm release 99、`provider_capability_reports` 行差仍是 4 行（10.3 三新增 + 旧 `fuyao/sectors/fuyao-market-v2` 保持，落 `/tmp/a-stock-10.5-caps-row-20261013.txt`），11 张新 THS 表 `count(*)=0`（落 `/tmp/a-stock-10.5-ths-tables-20261013.txt`），CronJob 仍 absent，pod 时钟 10:59 Asia/Shanghai。Apply 时机：必须等上海盘后 15:10 settlement 之后用户单独复述才能跑（CLI `_is_settled(as_of)` 闸门 + `effective_date` 比对 + `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1` + `MARKET_ENVIRONMENT_THS_WRITES_AUTHORIZED=1` + `MARKET_ENVIRONMENT_FUYAO_THS_CATALOG_ENABLED=1` + eligible revision 一致 + `request_budget` ≥ minimum_budget 且 ≤ capability 预算 80）。10.5-apply 命令与 dry-run 完全一致只需加 `--apply`，三个 eligible revision 与 10.3 capability apply 完全对齐。离线：focused THS/capability 套件 161 passed、`vitest 139 passed`、`openspec validate --strict` 通过、`check-docs-contract --mode=full` 通过、`git diff --check` 全过。dry-run 日志落 `/tmp/a-stock-10.5-dryrun-20261013.txt`；其余 10.6–10.8 仍按 plan 顺序等待用户分别复述。

  - 2026-10-13 17:28（10.5 apply 修复后完成）首次 apply 在旧镜像 `20261012-172238-c53705f` 上因 `883401.TI` 缺 `changePct` 失败且 normalized 表零写入；从已审 commit `8f0a6bc` 构建 `localhost/a-stock-market-environment:20261013-162900-8f0a6bc`（containerd digest `sha256:d6339966…98600`），本地 health smoke 与远端归档 SHA-256 校验通过。使用完整 `values-ths-capabilities-on.yaml` 做 `--no-hooks --atomic --wait` Helm upgrade，仅 image tag 变化，release 99 → 100；Pod 1/1 Ready、0 重启，PostgreSQL/PVC/Secret/migration 未变，CronJob/Job absent，Pod 内 health 200。新 Pod 重试同一命令成功，runId `8226a1b725d74d1a81829372736be4b3`，45/45 items、56/60 requests、0 failed/0 conflict；生产写入 846 catalog/relation/ranking/bar/identity rows + 2,376 membership facts（`886042.TI=203`）。`/api/market-environment/ths/catalog` 返回 `revision=fuyao-ths-catalog-v1,total=846`。失败 run `4c1e51239ffb4cdb881299e74d5da379` 保留为审计记录；10.6–10.8 仍需分步授权，调度保持 `enabled=false/suspend=true`。

  - 2026-10-14 11:04（0006 + 幂等修复生产发布完成）从 clean detached commit `b0a7c35` 发布。切换前用 hook-free Helm revision 101 将 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 临时置 0，确认无 active run/task；新建 `/mnt/xiaomi/app-builds/a-stock/a-stock-pgdump-20261014-1040-b0a7c35.dump`（2,800,385 bytes，SHA-256 `82286ef44b31c41a6c255c1011c342359ed716c6d608e0cc3f07cd2d5ae6e52c`），拉回本机并通过 `pg_restore --list` 与临时 PostgreSQL 16.4 单事务恢复，读回 schema v8、846 catalog relations、846 rankings。普通发布入口使用 `/dev/shm` 作为临时归档目录以规避本机根分区余量不足，未删除用户文件；`scripts/deploy-truenas-k3s.sh --component all --baseline-values values-ths-manual-off.yaml` 保持 THS on 与 schedule off，revisions 102/103/104 依次完成 migration/service/完整 release，revision 105 再以 `--no-hooks` 恢复 manual refresh。最终 schema v9、Alembic `0006_ths_rank_null_pct`、`change_pct nullable=YES`；镜像 `localhost/a-stock-market-environment:20261014-104800-b0a7c35`，containerd digest `sha256:ef8b524bf3e143ec68348100ed9384be8bd21048637a03cd1c358fcaaf7a2ae7`，Pod imageID `sha256:67089878f5d654a7dc7f6e8337bb0c6db11a3536a8d887dec720e2bed555f0f0`。Dashboard/PostgreSQL 1/1 Ready、0 restart；PVC UID、Secret UID、4 条 capability、846 ranking/bar/identity/catalog 与 2,376 membership 行均不变；health、首页、`/data-collection`、status、catalog GET 均 HTTP 200；CronJob/Job absent，调度仍 `enabled=false/suspend=true`。本次未调用 provider 或重新采集；旧 `2026-10-13` failed/blocked attempt 必须保留，当前日采集只可在上海 15:10 后再次明确授权执行。

已核对的契约范围：

- `GET /api/a-share-index/catalog/ths-index-list?tag=<tag>` 支持 `industry`、
  `cn_concept`、`region`、`tszs` 四类全量目录，每行使用完整 `*.TI` `thscode`
  和展示名称。
- `GET /api/a-share-index/prices/snapshot?thscodes=...` 批量返回最新 OHLC、`volume`
  和 `turnover`；它只能用于已证明的当日增量，不得重标为历史数据。
- `GET /api/a-share-index/prices/historical` 每次只接受一个 `thscode`，仅支持
  `interval=1d` 和 `start/end` 毫秒时间窗口，单窗口最长 10 年，返回 OHLC、
  `volume` 和 `turnover`。
- 全市场 10 年日 K、最近 10 交易日日 K 和复权因子 dump 由
  `/api/dump/market-dumps/**` 的 API-key 路径获取短时预签名下载链接；链接通常约
  5 分钟失效，不得持久化、缓存、记录或放入证据。导入证据只保留脱敏的
  `dump_id`、schema、日期范围、文件 checksum、行数和 capability revision。

实施后的显式操作门禁固定如下：

1. **目录同步**：只允许显式 CLI/受保护 POST 触发；在 provider I/O 前同时校验
   上海盘后窗口、`--allow-real`、API key、已批准的 `industry-ranking` 与
   `sector-membership` 精确 capability revisions 和正数请求预算。预算在 provider I/O
   前按 4 次目录请求、capability 证明的 snapshot 分片数、四类 Top 10 上界和显式
   点选编号计算；不足时零 provider I/O。四个 tag 各自校验非空、唯一 `*.TI` 代码、
   名称冲突、provider 时间戳、数量和 canonical checksum；完整目录先独立提交，再按
   去重后的每类 Top 10 与显式点选编号逐个同步 current membership。单编号失败使
   operation 为 `partial`，但不得回滚已验证目录或兄弟 membership。普通 GET、启动和
   默认调度始终零 provider I/O。对应开关/版本为
   `MARKET_ENVIRONMENT_FUYAO_THS_MEMBERSHIP_ENABLED` 与
   `MARKET_ENVIRONMENT_FUYAO_THS_MEMBERSHIP_REVISION`，默认关闭/空值。
2. **历史 K 线回填**：请求必须明示有限 `thscode` 集合、`start/end`、请求预算和
   可恢复 run identity；回填按单代码/单窗口记录 checkpoint，已成功且 revision/checksum
   兼容的窗口在恢复时跳过。验收时同时核对最后有效日期、重复日期、OHLC 范围、
   `volume >= 0` 和 `turnover >= 0`；两字段分开保存，缺失用 `null`/`insufficient`
   表示，不得互相替代或补0。
3. **成员事实导入**：只允许显式导入已下载的本地 Parquet/manifest。先验证文件
   checksum、`dump_id`、schema、精确日期、`Asia/Shanghai` 时间戳、规范证券代码、
   重复业务键和字段单位，再写入隔离于 THS 指数日线的成员事实表。任一检查失败
   整批拒绝，不得把部分文件宣称为完整成员证据。
   官方 daily/incremental schema 使用 `thscode`、`currency`、`interval`、`adjusted`、
   `date_ms`、`open_price`、`high_price`、`low_price`、`close_price`、`volume`、`turnover`；adjustment dump
   提供除权除息事件项而不是现成 `adjustment_factor`。在复权公式、事件顺序和前收盘
   证据未冻结并验证前，adjustment capability 必须保持 `ineligible`，不得用 synthetic
   fixture 或未复权价格替代。
4. **身份隔离与审计保留**：THS `industry`/`cn_concept`/`region`/`tszs` 都是
   provider observation，不得因名称相似写入申万一级 taxonomy、membership 或
   `QTS-01-05-*` 输入。历史 `sectors` snapshot、collection task、warning、checksum 和
   `fuyao/sectors/fuyao-market-v2` capability report 保持原 dataset identity，不删除、重标、复制
   或当作新数据集成功证据。仓库公共运行时已退役 `sectors`；当前生产 release 在未获部署授权前保持原状，
   其切换、回滚和历史兼容开关清理必须通过独立受审发布完成。

失败恢复与排错：

- 若在 capability、时间、API key、权限、限流或请求预算门禁失败，要求零 provider I/O
  或零权威写入；先保留脱敏失败分类，再修正报告/配置，禁止降低校验来继续。
- 目录同步出现缺 tag、重复代码、冲突名称或 checksum 变化时，将新 revision 保持
  `insufficient`/冲突审计，不得覆盖上一个完整目录；先比较 provider 时间戳、规范排序
  后的 code/name 清单和 capability revision。
- 历史回填的单代码失败不回滚其他已成功代码；parent run 标记 `partial`，只把
  失败/未完成 checkpoint 保持为可重试。同业务键同 checksum 幂等，不同 checksum
  必须显式冲突并保留旧证据，不得执行 overwrite 式“修复”。
- dump 下载中断或预签名过期时重新申请新链接，不得重用、打印或持久化旧 URL；文件
  checksum/schema/日期失败时拒绝该文件，保留上一个已验证 revision。
- 回滚只关闭新同步、回填、导入或查询暴露开关，保留 PostgreSQL 新表、run/checkpoint、
  旧 `sectors` 证据、capability reports、Secret 和 PVC；禁止通过删表、删快照、卸载 release
  或手工 SQL 清理失败。

### 扶摇行业字段补充（东方财富同供应商 dataapi）

该能力不是新的行业 provider，也不改变 `push2` → `push2delay` → capability-gated 扶摇的正式顺序。
只有扶摇行业基础结果已被接受后，且明确设置
`MARKET_ENVIRONMENT_EASTMONEY_SECTOR_ENRICHMENT_ENABLED=1`，才允许调用：

```text
GET https://data.eastmoney.com/dataapi/bkzj/getbkzj
  ?key=f3,f6,f62,f104,f105,f128,f184
  &code=m:90+s:4
```

接口为 latest-only、没有可靠业务日期；因此只允许当前上海市场日且达到
`MARKET_ENVIRONMENT_SETTLEMENT_TIME` 后调用，历史日期、结算前或日期证据不足时必须为零次补充请求。
dataapi 的东方财富 `BK` 代码不能直接当作扶摇 THS 代码。映射 revision
`fuyao-eastmoney-sector-map-v1` 只允许审阅后的显式映射，其他行只能通过唯一的严格规范化名称匹配；
重复名称、分类冲突、变动/成交额 sanity check 失败均保持未匹配。

`f62`、`f104`、`f105`、`f128` 和 `f184` 先校验原始类型；`f3`/`f184` 的整数化百分比只有在与扶摇
涨跌幅一致时才按确认的 scale 归一化，无法判定时拒绝。合并是 fill-only，扶摇代码、名称、涨跌幅、成交额
永远权威，未匹配或无效值继续为 `null`。快照和 collection task 的
`quality.sectorEnrichment`/`timings.sectorEnrichment` 保留 source、sameVendor、mapping revision、
匹配/字段覆盖、`fieldMatched`/`fieldFilled`、日期证据和 warnings；部分匹配保持 `fallback`/`partial`，
补充失败保留扶摇基础快照，不改成 `failed-missing`，也不跨日期留存。

默认开关为 `0`，代码缺少该环境变量时 fail closed。回滚只需关闭该开关并重启/重新发布应用，保留已有
快照、PVC、任务审计和 provider-free GET；禁止删除快照、PVC 或用其他日期响应修复。普通 status、run、
materialized aggregate 和 chapter-01 GET 只能读取已存 metadata，不得触发任何 Eastmoney、Fuyao 或
Tushare 请求。当前 Tushare token 已检查但无 `moneyflow_ind_ths`、`moneyflow_ind_dc`、`ths_index`、
`ths_daily`、`dc_index`、`dc_member`、`index_member`、`index_dailybasic` 权限；`index_daily` 不含所需行业
资金流/宽度/领涨股字段，本变更不引入 Tushare 运行时依赖。

### 统一 provider 请求层排错（2026-09-29，实施中）

provider 失败排查先区分传输层和契约层：检查 host、请求日期、最终来源、错误类别、重试次数、退避等待、熔断状态和 `Retry-After` 处理结果；不要仅凭一次 429/5xx 直接扩大采集并发。连接/读取异常、408、429、5xx 属于有界重试范围；401/403、其他 4xx 或响应字段/日期校验失败应快速失败并沿既有降级链继续，403 不得通过循环重试规避限制。

同一 host 的 UA 应在 session 生命周期内保持一致。若日志显示同一请求被重复发起，先确认 single-flight、按 host 请求门和成功短缓存是否命中；实时数据的短缓存约为 10 秒，历史数据和 TDX 盘后包必须按完整参数及目标日期隔离。缓存命中不能掩盖陈旧状态，响应仍须展示抓取时间、实际日期、来源和质量 warning。

连续可重试失败后，host 会进入短暂冷却并触发既有 provider 降级；冷却结束只允许一次受控探测。排错时记录冷却开始/结束、探测结果和请求预算消耗，不手工清除缓存、绕过请求门、伪造 Cookie/UA、配置代理池或把其他日期响应写入当前日期。真实 provider probe 仍只能在盘后、显式授权的隔离环境执行；普通 GET、status 和 provider-free 读取不得触发探测。

### 统一 acquisition adapter 与可选 Scrapling 排错（2026-10-08）

采集问题按四层定位：coordinator/task、dataset acquisition plan、source adapter、transport policy/engine。先读取本地 task metadata 中的 dataset、requested/actual date、plan/source/capability revision、ordered attempts、failure category、field availability、timings、evidence fingerprint 和脱敏 provenance；不要从异常字符串猜测 provider 成功，也不要通过普通 GET 重放采集。

- coordinator 只应出现一次 lease、一次合法 task transition 序列和最多一次 aggregate rebuild。若同一 dataset/date 出现嵌套 run、第二把 lease 或重复提交，检查 compatibility adapter 是否错误构造 coordinator 或调用旧 `collect_task`。
- formal/fallback attempt 可以决定 candidate；shadow 只记录差异，不得改变正式 payload、source、checksum 或 task state；enrichment 只能 fill-only 写入计划批准字段。任何角色越权都视为契约失败。
- success 必须同时存在有效 candidate、dataset/date/source identity 和 evidence fingerprint；permission、challenge、date-mismatch、insufficient 等失败不得改写为 success。失败留存只查询同一日期本地快照。
- HTTP adapter 必须共享 composition root 创建的同一 policy gateway。重试总数只看 gateway budget；engine 内部重试、adapter 自行 sleep 或为同 host 创建独立 limiter 都是配置/架构错误。
- 请求诊断不得记录 API key、Authorization、Cookie、secret query、proxy credential、完整 challenge page 或敏感 body。排错只保留规范化且脱敏的请求身份、状态、允许的响应 header、字节数、final URL、engine 和失败类别。

默认运行环境只安装并选择 `requests` engine。离线 enhanced 环境使用 `.venv/bin/python -m pip install -r requirements-scrapling.txt` 安装精确版本的可选 profile；基础 `requirements.txt` 和默认镜像不引用该文件。Scrapling static engine 必须同时满足：配置选择已注册 engine、source/host 位于显式 allowlist、方法/body 能力受支持、可选依赖可导入。默认 allowlist 为空；任何条件不满足都在外部 I/O 前 fail closed，不回退到更宽松 engine。

Scrapling engine 只允许静态单次 HTTP 请求，必须关闭内部 retries、blocked-request escalation、proxy rotation、challenge solving 与浏览器功能；不得执行 `scrapling install` 或下载 Chromium。401/403、登录墙、CAPTCHA/interstitial challenge 立即返回 non-retryable permission/challenge failure，禁止从 requests 自动升级到 Scrapling。启用或回滚只允许在独立受审部署计划中修改 enhanced profile/allowlist；关闭 enhanced profile 即恢复 requests-only，保留快照和审计，不删除 PVC 或任务历史。

本变更的离线验证只能使用 fixture/fake engine、依赖解析、镜像/Helm 离线 render 和资源测量；禁止真实 provider probe、生产 PostgreSQL 写入、生产部署或自动化触发。无论是否渲染 enhanced profile，render 都不得包含 application-owned CronJob 或 scheduling values。

增强容器以基础镜像为父层构建，不能跳过基础镜像，也不能把 `requirements-scrapling.txt` 加入默认 `Dockerfile`：

```bash
podman build --format docker --tag localhost/a-stock-market-environment:local-base --file Dockerfile .
podman build --format docker --build-arg BASE_IMAGE=localhost/a-stock-market-environment:local-base --tag localhost/a-stock-market-environment:local-scrapling --file Dockerfile.scrapling .
helm lint deploy/helm/a-stock --set database.existingSecret=a-stock-postgresql
helm template a-stock deploy/helm/a-stock --namespace a-stock --set database.existingSecret=a-stock-postgresql
helm template a-stock deploy/helm/a-stock --namespace a-stock --set database.existingSecret=a-stock-postgresql --set marketEnvironment.scrapling.enabled=true
```

Chart 的 `marketEnvironment.scrapling.enabled=false` 默认选择顶层 `image`；只有显式设为 `true` 才选择 `marketEnvironment.scrapling.image`，并把结构化 `allowlist` 作为 JSON 注入 Dashboard workload。allowlist 条目必须是精确 `host` + `sourceId`，不能使用通配符；仓库默认值保持 `[]`。两个 profile 都不创建 Secret，资源 request/limit 与 `/tmp` `emptyDir` 契约一致。回滚开关是把 `marketEnvironment.scrapling.enabled` 恢复为 `false` 并保持 allowlist 为空；这会重新选择基础镜像和 requests-only registry，不改快照、数据库、PVC 或 task history。若同一进程已按另一 profile 初始化，composition 会 fail closed，必须通过受审 workload replacement 完成切换，不能在进程内热替换 gateway。

2026-10-08 本地 Podman 实测（Linux amd64，5 次禁网、只读 rootfs、64 MiB `/tmp` tmpfs，统计完整 settings + composition-root 冷启动中位数）：最终 base/enhanced 镜像为 `457408146 / 808329793` bytes（`436.218 / 770.883 MiB`），增强增量 `350921647` bytes（`334.665 MiB`, `+76.720%`）；启动 `1.343 / 1.308s`，CPU user+system `1.350 / 1.321s`，峰值 RSS `74588 / 74948 KiB`，`/tmp` 增量均为 `0`。首轮另有一个受共享磁盘 D-state 影响的 base `25.218s` 异常样本，未纳入最终 5 次有 15 秒 timeout 的测量；稳定中位数未显示增强 profile 的启动回归。

同次 SBOM/漏洞测量中，`pip inspect --local` 的 Python 包数为 `72 / 87`，enhanced 新增 15 个包；base/enhanced 的 CycloneDX 1.4 组件数为 `71 / 86`（生成器不把 pip 自身列为组件），`pip-audit` 使用 2026-10-08 当时的 PyPI advisory 数据均报告 0 个已知 Python 漏洞。Debian 包均为 87 个，排序后 `package=version` 清单 SHA-256 都是 `2b78937be57e2aedcf5515e4877b2d79590bb6569cdcd414b7ddaca6a77af5b4`，证明增强层未增加 OS 包。宿主未安装 Syft/Trivy/Grype，因此这不是全文件系统或供应链二进制 CVE 扫描；生产 rollout 前仍需用组织批准且带冻结数据库版本的 scanner 复核，不能把当前的 0 当作未来或全镜像零漏洞。验证没有执行真实 provider probe、生产部署、Secret 变更或调度激活。

### 末层 HTML 静态源（2026-10-09）

`sectors` 数据集在最末层新增两个静态 HTML source adapter（`sectors-sina-html`、`sectors-xueqiu-html`），目的严格限制在兜底 web-visible 字段：`name` / `changePct` / `amount` / `leader 名`。Engine 复用现有 `Scrapling static engine`，但**绝不**用作爬虫、SPA 渲染或登录墙绕过。本节取代先前任何相关 changelog。

适配的硬规则：

- 仅在 Eastmoney 主域 + 延迟域 + `dataapi` 增强 + Tushare + Fuyao **全部**失败后尝试；任一上层成功立即短路，禁止替换现有 fallback 顺序。
- `mainNet` / `mainNetPct` / `upCount` / `downCount` 永远 `null + dom-source-unsupported:<field>` warning，禁止用成分股数、计数、`inflow` 文本或任何数值字段组装。
- `leader` 字段必须是文本（龙头 / 领涨 / 领先股标签去掉后的名），遇到 6 位代码或数字徽标立刻降为 `null` 并附 `leader-identifier-not-name` warning，绝不把代码当成名字。
- 401 / 403 / 登录墙 / 验证码 / interstitial challenge 立刻分类为 non-retryable `permission` / `challenge`，**不**重试、**不**切换 engine、**不**自动绕到 `requests`。
- DOM 选择器漂移必须被 `DriftDetector` 触发 `dom-drift`，quality 降级为 `fallback` / `degraded`，绝不从无关 DOM 字符串拼出 name / changePct / amount / leader。
- Chart 不提供 `scheduledCollection` 或 CronJob；HTML 末层上线不改变 backend automation gate 或 Hermes job。

环境与编排：

- `MARKET_ENVIRONMENT_CRAWL_FALLBACK_ENABLED=0` 是默认；`=1` 时 plan 注册并启用末层步骤。
- `MARKET_ENVIRONMENT_CRAWL_FALLBACK_HOSTS` 接受逗号分隔的 `sina` 与 `xueqiu`；任何其他值都被 settings 校验拒绝。
- Helm: `marketEnvironment.crawlFallback.enabled=false`、`marketEnvironment.crawlFallback.hosts=[sina, xueqiu]`；渲染 profile 时，`MARKET_ENVIRONMENT_CRAWL_FALLBACK_*` env 只注入 Deployment；token / cookie / secret 都不进入 manifest。
- `crawlFallback.enabled` 与 `MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED` **互不依赖**：crawl 启用不等于允许自动化采集。
- Scrapling engine 范围：`scrapling.enabled=false` 默认；`crawlFallback.enabled=true` 时只把 `(host, source_id)` allowlist 暴露给 sina / xueqiu adapter，**不**扩散给其他 source。

排错与回滚：

- 失效标志：浏览器或 collection 日志里 sina / xueqiu 持续出现 `host-permission-denied`、`host-challenge-detected`、`dom-drift` 或 `row-extraction-error`；dashboard 上对应行的 quality 经常是 `degraded` / `fallback`。
- 立即回滚：把 `marketEnvironment.crawlFallback.enabled` 改回 `false` 并 roll 一份 Helm release（或运行 `bash scripts/deploy-truenas-k3s.sh`），不允许在 enabled 状态下临时禁用 host。回滚只翻转开关，**不**删除 PVC / capability report / snapshot / 历史 fixture。
- 真实 probe：仅在 `--allow-real` + `MARKET_ENVIRONMENT_PROBE_ALLOW_REAL=1` + 盘后窗口下执行 `python -m src.market_environment.cli sectors-html real-probe --source <sina|xueqiu>-html --as-of <date> --output <redacted.json>`；probe 默认 dry-run 且零网络 I/O，输出 envelope 永不包含 token / cookie / body。
- capability promote：probe 通过后，操作发起人执行 `python -m src.market_environment.cli capabilities promote --input <report> --provider <sina|xueqiu> --dataset sectors --revision <crawl-html-<host>-v1> --apply`，与 `activate-fuyao-sector-fallback` 复用同一条 promotion 边界，**不**引入第二条路径。
- 若同一进程已按 `scrapling.enabled=false` 初始化，之后切到 `crawlFallback.enabled=true` 时 composition 会 fail closed，按受审 workload replacement 流程走，不允许进程内热替换 gateway。

绝对禁止：

- 把任意中间件重新解释的 sina / xueqiu 数字（成分股数、计数、`inflow` 徽标、装饰性数值）写入 `SectorRow.mainNet` / `upCount` 等。
- 把 leader code（如 `600519`）作为 `leader` 字段值。
- 把第三方资产（CSS/JS/字体）从站点搬运到生产容器或 fixture；fixture 是手写合成，禁止从线上 `view-source` 拷贝完整骨架。
- 启用 host 时附带默认 allowlist 之外的其他 host / source_id。
- 因启用 crawl fallback 而同时开启 automation gate 或创建 Hermes job。

### Helm Chart 与受控发布入口

`deploy/helm/a-stock/` 提供与原生 k3s 清单等价的参数化 Chart，但生产写操作不直接调用 Helm。TrueNAS 上唯一受支持的通用 install/upgrade/application rollback 入口是 `scripts/deploy-truenas-k3s.sh`；仓库没有通用 uninstall 入口，退役必须另建受审 exact-resource 操作包。先从 `deploy/truenas/deploy.env.example` 创建私有环境文件，核对完整 baseline values、release、namespace 与不可变镜像后执行：

```bash
cp deploy/truenas/deploy.env.example deploy/truenas/deploy.env
editor deploy/truenas/deploy.env
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env
```

Chart 可安装在 Kubernetes 1.26+，且不再包含盘后 CronJob 或时区策略。没有 Ingress Controller 时可设置 `ingress.enabled=false`、`service.type=NodePort` 和 `service.nodePort=<未占用端口>`。没有动态 StorageClass 时，应由运维人员先为 PostgreSQL StatefulSet 创建可由 `database.persistence.storageClass` 选择和绑定的静态 PV/PVC；只有 PostgreSQL 容器需要数据库卷写权限，Dashboard 不得通过旧 `persistence.existingClaim` 或其他应用卷重新挂载 SQLite/数据库目录。

TrueNAS 直连部署使用受版本控制的 `deploy/truenas/values-secure-manual-collection.yaml`：固定 `NodePort:32001`、关闭 Ingress/CronJob，并仅保留一个 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1`。该 values 必须引用部署前创建的 `database.existingSecret`（至少 `DATABASE_URL`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`）；Dashboard 只通过 PostgreSQL ClusterIP Service 访问数据库，不挂载 SQLite 或 PostgreSQL PVC。匿名 NodePort 写入口是负责人显式接受的例外；任何能路由到节点端口的客户端都能触发 provider 调用和 PostgreSQL 写入。NodePort 不提供身份认证、客户端授权或子网隔离，禁止公网端口映射，发布前必须核对数据库 Secret、PostgreSQL claim、镜像 tag、集群版本和实际网络边界。

普通入口在首次 Helm render、构建、镜像传输/导入、SSH 或目标 API 访问前，先验证 chart/baseline 不含
`scheduledCollection` 或 CronJob template。入口按历史 Helm helper 规则直接计算 release-derived former name，
不再通过渲染 CronJob 求名；随后同时扫描 stored manifest，并对 release-derived name 与固定
`market-data-collection` 做 exact live GET（同名时去重）。任一 active 或 suspended 资源存在、API/认证/传输
不确定、stored manifest 不可判定都在 build/Helm write/application rollback 前 fail closed。普通入口只读取和
拒绝，不 patch、删除、接管或激活旧资源；成功写入后再次证明两者 absent。不得继承目标历史 values、恢复历史
revision、执行原始 uninstall 或绕过入口直接执行 Helm write。

TrueNAS 的普通组件只包含 `all`、`database` 和 `service`。历史 `schedule` component、
`--release-suspended`、`--activate-schedule`、`--disable-schedule`、offline/server schedule render 与
`--repair-sectors-off-release` 已全部退役；不得恢复独立 operator override 或使用裸 Helm/kubectl 创建同名 CronJob。

冻结手工采集必须使用专用 `--disable-manual-refresh` 入口和一份从当前完整 release 基线生成、已审阅且只把 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 从 literal `"1"` 改为 `"0"` 的 full values packet。该入口必须绑定 clean worktree、full `REVIEWED_GIT_HEAD`、chart/values/render SHA-256 与当前冻结镜像三元组；写前验证 stored/live release 与 stored hooks 一致、所有 full packet 管理资源（至少包含 Dashboard Deployment/Service 与 PostgreSQL StatefulSet/PVC）在 Kubernetes server defaults 归一化后零漂移且均不处于 deletion 中、两个 application CronJob absent、namespace 中每个 retained Job 都有 `Complete=True` 或 `Failed=True` 终态、PostgreSQL 健康、PVC/Secret identity 已冻结，并证明 packet 除该 env value 外零漂移。Failed/Complete/Error Job 属于审计证据，必须保留，不能为了满足停写门禁而删除；queued、pending、retrying、active、conditions 缺失或其它未证明终态的 Job 一律视为潜在 writer。唯一 Helm 写入使用 `--no-hooks --atomic --wait`，不得构建/导入镜像、运行 schema migration、调用 provider 或提交 collection POST；写后必须证明 stored hooks 未漂移、Ready Pod 仍使用原 manifest digest、manual refresh 为 `0`、PVC/Secret/image、terminal-Job 和无 CronJob 条件均未漂移。失败不得自动把 manual refresh 恢复为 `1`。

启用 Hermes full endpoint 必须使用专用 `--enable-automation-refresh` 入口和一份从当前完整 release 基线生成、
已审阅且只把 `MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED` 从 literal `"0"` 改为 `"1"` 的 full values
packet。该入口复用上述 clean worktree、reviewed HEAD、chart/values/render hash、exact frozen image、stored/live
release/hook、PostgreSQL、PVC/Secret、terminal Job 与 former CronJob 门禁，并额外要求 manual refresh 在写前写后
均为 `0`、活动 collection run/task/lease 均为 0。唯一 Helm 写入使用 `--no-hooks --atomic --wait`，不得
build/import 镜像、执行 migration、创建 Job 或调用 provider；写后 stored manifest 必须与 reviewed full release
精确一致且唯一语义差异是 automation `0→1`。该入口只启用 gate，不自动发送 full POST；canary 必须在独立的
盘后步骤使用唯一 `Idempotency-Key` 执行。任一 packet/live/identity/writer 漂移都在 Helm write 前停止，失败不
自动执行 provider 或进入 Hermes job 安装。

关闭 backend automation gate 必须先暂停对应 Hermes job，再使用对称的 `--disable-automation-refresh` 入口和只把 automation literal `"1"` 改为 `"0"` 的完整 reviewed values packet。该入口同样要求 manual=`0`、活动 run/task/lease 全为零、同一 frozen image、stored/live release 与 hooks 零漂移、CronJob/Job absent、PVC/Secret identity 不变，并使用 `--no-hooks --atomic --wait`。设置 `REVIEWED_AUTOMATION_OFF_VALUES_SHA256` 与 `REVIEWED_AUTOMATION_OFF_RENDER_SHA256` 后执行；失败保持 gate 的现场状态，不自动恢复 Hermes 或触发 provider。启停两种入口都不得构建/导入镜像、运行 migration 或发送 collection POST。

```bash
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --disable-automation-refresh \
  --baseline-values <REVIEWED_CURRENT_FULL_AUTOMATION_OFF_VALUES> \
  --kube-version <ACTUAL_KUBERNETES_VERSION> --release-name a-stock --namespace a-stock
```

如果只读发现显示任一历史 CronJob，普通应用发布和回退必须停止。仓库不再提供 schedule mutation 或清理
模式；处置必须新建 exact-resource 计划，冻结 stored/live/Job 证据并另获授权。证明两个 identity 都 absent 后，
才可生成并审阅当前完整 manual-off values packet，设置
`REVIEWED_GIT_HEAD`、`REVIEWED_CHART_SHA256`、`REVIEWED_MANUAL_OFF_VALUES_SHA256`、
`REVIEWED_MANUAL_OFF_RENDER_SHA256` 与 `FROZEN_IMAGE_REPOSITORY/TAG/DIGEST`，再执行：

```bash
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --disable-manual-refresh \
  --baseline-values <REVIEWED_CURRENT_FULL_MANUAL_OFF_VALUES> \
  --kube-version <ACTUAL_KUBERNETES_VERSION> --release-name a-stock --namespace a-stock
```

该入口只允许 stored release 中 manual refresh 为 literal `"1"`，候选为 literal `"0"`；已经为 `0`、
缺失、重复、`valueFrom` 或伴随任意其它资源/env/hook 漂移均拒绝且不得进入 Helm write。

只有另行审核的处置证据与随后普通入口的 server-observed readback 都证明 stored/live 两个 identity absent，才能
恢复普通部署。label 缺失或漂移不是“资源不存在”的证据，API/认证/传输失败也不能降级为 absent。任何 write、
rollout 或写后状态读取失败都不得报告成功或尝试修改遗留 CronJob。

渲染和检查：

```bash
helm lint deploy/helm/a-stock
helm template a-stock deploy/helm/a-stock --namespace a-stock --set database.existingSecret=a-stock-postgresql
helm get values a-stock --namespace a-stock
helm history a-stock --namespace a-stock
```

启用 `persistence.existingClaim` 时 Helm 不创建或删除该 PVC。Chart 创建的 PVC 默认设置
`helm.sh/resource-policy: keep`，但 keep policy 不能把原始 uninstall 变成受支持操作；退役必须先冻结
release、PVC/PV 和恢复证据。Chart 支持 Kubernetes 1.26+，`deploy/k3s/` 与 Helm 所有 retained profile 都只
渲染 PostgreSQL/migration/Dashboard，不包含 market-data CronJob。原生 Kustomize 与 Helm 的 catch-all Ingress
会发生冲突，单个环境只选择一条发布路径。

### TrueNAS 1.20 + VM 1.21 一键发布

TrueNAS 节点的 k3s 服务需要启用 systemd 开机自启；部署前确认并在维护窗口执行：

```bash
ssh admin@<truenas-host> 'sudo systemctl enable k3s'
ssh admin@<truenas-host> 'systemctl is-enabled k3s && systemctl is-active k3s'
```

若节点显示 `NotReady` 且原因为 `NetworkPluginNotReady: cni plugin not initialized`，不要继续
发布或重试 Helm rollout；先恢复 TrueNAS 管理的 CNI/Multus 清单和网络服务，再重新执行部署。

当项目已经 clone 到 1.21 的 `/home/gyt/a-stock`，可使用 `scripts/deploy-truenas-k3s.sh` 完成构建、镜像传输、containerd 导入和 Helm 发布。该脚本假设 1.21 上有 Podman、Helm、kubectl、SSH、SCP 和 netcat，且 SSH 用户在 1.20 具有无需交互密码的受控 `sudo` 权限；它不会修改 1.21 的 NGINX/Tailscale 配置。默认 `K3S_API_SSH_TUNNEL=true`，脚本把临时 kubeconfig 指向 1.21 回环端口，并经 SSH 转发到 TrueNAS `127.0.0.1:6443`；SSH 服务必须允许该目标的 TCP forwarding。脚本退出时自动关闭隧道，不要求也不建议向局域网开放 `6443/tcp`。

`all` / `service` 会在本地生成完整镜像归档。脚本在 `podman save` 前按镜像实际大小加 25%（最低 256 MiB）安全余量检查临时文件系统；若 `deploy.env` 显式设置 `DEPLOY_TMP_ROOT`，该路径必须是可写绝对目录且容量足够，否则立即失败。未设置时依次检查 `TMPDIR`、`/dev/shm`、`/tmp` 并选择首个满足条件的位置，退出时删除本次 `a-stock-deploy-image.*` 目录。内存较小的机器不要盲目使用 `/dev/shm`，应指向专用大盘。`database` 不导出镜像，不执行该门禁；已退役的 `schedule` component 不再是有效参数。发布前后可用 `df -h / /dev/shm "${DEPLOY_TMP_ROOT:-/tmp}"` 核对容量；禁止用 `podman system prune -a --volumes` 腾空间，因为这会破坏回滚镜像或本地恢复环境。该门禁只保护本地镜像归档，不替代 Podman graphRoot 与远端 `REMOTE_IMAGE_DIR` 的容量监控。

首次配置：

```bash
cd /home/gyt/a-stock
cp deploy/truenas/deploy.env.example deploy/truenas/deploy.env
editor deploy/truenas/deploy.env
```

至少修改 `TRUENAS_HOST`、`TRUENAS_SSH_USER`、`REMOTE_IMAGE_DIR`，并根据 1.20 的实际输出设置 `TRUENAS_INGRESS_PORT`。动态存储与 Traefik 环境可设置 `STORAGE_CLASS`、`INGRESS_CLASS`；TrueNAS 24.04 无 StorageClass/IngressClass 的静态 PVC 环境使用 `deploy/truenas/values-secure-manual-collection.yaml` 作为 baseline。仓库不再包含或接受 scheduling overlay。`REMOTE_IMAGE_DIR` 应是 1.20 上允许该 SSH 用户写入的专用数据集目录。`INGRESS_HOST` 默认使用 `a-stock.k3s.lan`，NGINX 反代时必须发送相同的 `Host` 值。若本机 `K3S_API_LOCAL_PORT` 已占用，应换成其他 1024–65535 端口；只有在 TrueNAS 已将 6443 精确放行给管理机时才设置 `K3S_API_SSH_TUNNEL=false`。仓库更新必须作为独立前置步骤完成并重新审阅；部署脚本固定拒绝 `GIT_UPDATE=true`，不会在校验与发布之间 fetch、checkout 或 pull。

执行一键发布：

```bash
bash scripts/deploy-truenas-k3s.sh
```

#### 组件化部署（TrueNAS k3s）

同一 Helm release 支持一键和分项操作，组件依赖固定为：

```text
postgresql（namespace + existingSecret + PostgreSQL StatefulSet/PVC/Service） -> schema migration（Alembic Job） -> service（Deployment/Service/Ingress）
```

使用前确认 `deploy/truenas/deploy.env` 已设置 `TRUENAS_HOST`、`TRUENAS_SSH_USER`、
`REMOTE_IMAGE_DIR`（仅 `all`/`service` 需要）、`NAMESPACE`、`RELEASE_NAME`，并提供完整
baseline values 及预先创建的 `database.existingSecret`。PostgreSQL 数据使用独立 Retain RWO
claim；旧 SQLite claim 仅作为迁移输入保留。不要让 Dashboard 或采集 task 挂载旧 claim，也不要在
组件操作中删除、替换、扩容或重新绑定 PostgreSQL claim。

```bash
# 一键：database -> service，再以完整 component=all packet 收敛 release
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component all
# 只处理存储契约；existingClaim 只读验证，chart-managed PVC 才允许首次创建
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component database
# 只更新 Dashboard 服务；会复用不可变镜像并等待单副本 rollout
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component service
```

`service` 在写入前必须观察到 namespace、PostgreSQL StatefulSet/Service 就绪、数据库 PVC
为 `Bound` 和目标镜像。任一依赖失败都在
后续写入前返回非零。`all` 按上述顺序逐组件执行，输出每个组件的 `completed`/`failed`
状态和唯一重试目标；前一组件成功后即使后一组件失败，也保留 PVC 和已成功资源。`database` 阶段的 render
必须只有精确的 `a-stock-schema-migration` Job，命令为 `alembic upgrade head`，`database.schemaEnabled=true`
且 legacy SQLite `database.migration.enabled=false`。本合同中的“一次”限定为一次 hook-enabled Helm upgrade
和一次 schema-hook execution，不表示组件化发布总共只有一个 Helm revision：`--component all` 仍按
database → service → final full-release convergence 推进，只有 database write 允许 hooks，service write 与
最终 full-release write 都必须传入 `--no-hooks`；任一步失败即停止，不能进入后一阶段。成功并自动清理后
才能 rollout service；发布前和成功后 namespace Job 都必须为空。hook 失败时停止后续阶段并保留失败 Job
与安全诊断，不得删除证据来满足 absent 检查。

所有普通组件都在 build 和 Helm write 前检查 stored manifest 与两个 former live identity；发现任一
active/suspended CronJob 或无法确定状态即停止，不提供 mutation/cleanup。回滚使用受审 rollback commit 和新的
不可变镜像 tag 重跑 `service` 或 `all` 组件。不要执行 `helm uninstall`、`kubectl delete pvc` 或
任何隐式 resize。迁移前恢复 SQLite 时才使用 `sqlite3.Connection.backup()` 导出副本；运行时
数据库恢复必须使用 PostgreSQL 备份/恢复工具，并保留 PostgreSQL PVC UID、PV、容量、备份
校验和及恢复时间线。

普通应用发布脚本可使用新 tag（时间戳 + Git SHA），但 `all` / `service` 候选在任何 SSH、目标 API、构建或镜像工作前必须要求 clean worktree，且 full `REVIEWED_GIT_HEAD` 与当前 HEAD 完全一致。本地检查 `/api/health` 和首页，生成 archive SHA-256 后通过 SCP 传输，在 1.20 执行 `k3s ctr --namespace k8s.io images import`；导入后必须解析并冻结该 exact tag 的 containerd manifest digest，在 Helm write 前重新验证 tag→digest 映射，写后经 Deployment→current ReplicaSet→唯一 Ready Pod owner chain 验证 repo/tag 与 runtime imageID，并再次核对 target manifest digest。本地容器 smoke 会注入仅满足启动配置校验的 loopback PostgreSQL URL `127.0.0.1:1`；健康和首页检查不得访问数据库、provider 或生产网络，实际 Deployment 仍只从既有 Kubernetes Secret 获取数据库连接。普通模式会冻结已验证的 chart/values，在所有构建/目标写操作前验证 stored/live 两个历史 CronJob identity 与 namespace Job absent，在 database Helm write 前重验 live state 与 frozen render hash，只允许上述 schema hook 短暂存在；成功后再次验证 CronJob/Job absent。入口不会自动创建 canary、CronJob 或 provider-backed Job；migration 失败时不会删除 failed Job 或继续 service/final 收敛。

普通应用发布的 live declarative 比较会忽略 API server 生成的状态字段、分配字段和已批准的默认值；对于 Kubernetes 1.26 读回时省略的可选 EnvVar 空字符串（包括扶摇 revision），仅当 desired 明确为 `value: ""` 且 live 同名 EnvVar 同时没有 `value`/`valueFrom` 时视为等价。任何非空值、Secret 引用、变量缺失或其他 Deployment 字段差异仍会 fail closed，不得用裸 patch 绕过比较器。

后续更新只需在 1.21 检出审阅后的 clean commit 并重新执行同一命令；如需明确指定版本，可在环境文件设置新的唯一 `IMAGE_TAG`。脚本不使用 `kubectl port-forward` 作为长期入口，也不会删除远端镜像归档。应用回退检出受审 rollback commit，并使用新的不可变 rollback tag 运行同一普通入口；不直接恢复历史 Helm revision。若 stored/live 中存在任一历史 CronJob，必须停止并建立独立遗留资源处置计划。

一键发布完成后，1.21 NGINX 建议新增独立 TLS 端口，例如 `8443`，反代到 1.20 的 Traefik HTTP 入口（若 Traefik 是 NodePort，使用其实际 HTTP NodePort）：

```nginx
location / {
    proxy_pass http://<1.20的IP>:<Traefik_HTTP端口>;
    proxy_set_header Host a-stock.k3s.lan;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Host $host;
}
```

当前 `gyt.tail0007b1.ts.net/` 根路径已用于 multica，本项目应访问 `https://gyt.tail0007b1.ts.net:8443/` 或使用另一个独立 hostname；不要未经前端 base path 改造就直接挂载 `/a-stock/`。1.20 的 `6443` 只供集群本机访问；1.21 的 Helm/kubectl 默认经临时 SSH 回环隧道管理，不应把该端口暴露给局域网、公网或普通 Tailnet 客户端。

### TrueNAS NodePort 与采集写入口

当前生产事实必须在每次发布前只读复核，历史 revision 不能替代 live evidence。task 7.2 发布前基线为 revision 113；
2026-10-17 API/core 修复收口后当前为 revision 144 / schema v11/0008、两个旧 CronJob identity 与 namespace Job absent、
manual=1、automation=1、active writer=0。Dashboard Service 固定为
`NodePort:32001`；镜像、单副本、PostgreSQL StatefulSet/Service、数据库 Secret、安全上下文与 CronJob
absent 均不得被普通写入口变更。

离线检查候选：

```bash
helm lint --strict deploy/helm/a-stock
helm template a-stock deploy/helm/a-stock --namespace a-stock \
  --kube-version 1.26.6 -f deploy/truenas/values-secure-manual-collection.yaml
```

获准发布前，确认节点/集群没有占用 `32001`，并保存 Helm history、现场 current revision、完整 values、
Service、Deployment、Endpoint/EndpointSlice、运行镜像、Pod 安全上下文、PVC 名称/UID/PV/容量/使用量，
以及两个旧 CronJob 和全部 Job absent 的 stored/live 证据。检查节点和路由器/防火墙不存在公网映射；没有
ACL 证据时只能把边界描述为“所有可路由网络”。

发布前对 PostgreSQL 执行 `pg_dump --format=custom`（必要时配合受控物理备份），记录数据库 Service、PVC UID/PV、备份路径、SHA-256、schema 版本和恢复演练结果；旧 SQLite before-image 仅在迁移窗口按 `sqlite3.Connection.backup()` 创建。对现场捕获的当前 values 与候选执行 Helm diff，任何 PostgreSQL PVC 删除/替换、Secret 漂移或不变量变化都必须停止发布。

发布只能在单独批准的维护窗口执行一次受审 `--component all` 工作流：database Helm write 等待 PostgreSQL
StatefulSet ready 和唯一 schema migration hook 成功，service Helm write 使用 `--no-hooks` 并等待单个 Dashboard
Deployment ready，最终完整 release 收敛同样使用 `--no-hooks`，不得再次运行 migration。成功证据至少绑定冻结
chart/values/render hash、唯一 hook-enabled database invocation、hook manifest 与 `alembic upgrade head` 命令、
Job UID/Complete condition/安全日志或等价生命周期记录、schema v11 / Alembic
`0008_collection_idempotency` 读回、后续 service/final `--no-hooks` invocation，以及最终 namespace Job empty；
`alembic_version` 读回只能证明目标 schema，不单独证明 hook 只执行一次。automation 和 manual gate 必须先保持关闭；随后从预期 LAN 客户端验证
`/api/health`、`/data-collection`、OpenAPI 和 provider-free status GET。启用 automation、执行 canary 或提交
任何 provider-backed POST 均属于另外的明确写授权，不能作为部署健康检查。观察 collection run/task、provider
warning/限流、PostgreSQL lock/连接池、任务时长与数据库 PVC 增长，并记录实际可达边界和最终 revision。

2026-10-15 task 7.2 按该合同完成：candidate `6d96224f84e362960332ca89a8e6855e4f1c123f`，image
`20261015-150231-6d96224`，archive SHA-256 `cf2fac20…6de0`，containerd manifest digest
`sha256:a61f6b1b…7e78`。revision 114 的唯一 schema hook UID `33aea8df-dff0-4a30-8755-d797f0126b29`
产生 `SuccessfulCreate`/`Completed` events 后按 `hook-succeeded` 清理；revisions 115/116 分别以 `--no-hooks`
完成 service/final convergence。最终 v11/0008、manual/automation=0、writer/CronJob/Job=0，provider-free GET
与 OpenAPI 通过，旧计数、PVC/Secret UID 和备份 hash 未漂移。该证据不授权 task 7.3 的 gate 或 provider 写入。

2026-10-15 task 7.3 使用 clean candidate `5ebe48a15b313969d06be353d9616273730c9113` 的专用
`--enable-automation-refresh` 入口完成。revision 117 的唯一 release 差异是 automation `0→1`；manual=0、
同一 image/tag/digest、stored hooks、schema、PVC/Secret identity、former CronJob/Job absent 均不变。随后从
`192.168.1.21` 以 `hermes-canary-2026-10-15-t7.3-01` 调用 full endpoint：run
`93dd3c9b633b4cf5bb6d76132e3a5098` 为 `partial`，exact date `2026-10-15`，七个唯一 task 全部终态；三项
success、四项带可用证据的 partial，没有 terminal failure，因此 persisted failure 均为 null。终态同 key replay
保持 submission attempts/timestamps 与 binding/run/task/snapshot/materialization 指纹
`b81cf3b39b0a34a9cb1d0f165cd1305c6ba39f9db8e432a53c04c5be8ec1b62f` 不变；应用 Pod 对公网 80/443 的
replay 窗口没有新 SYN/有效载荷。该证据只完成 7.3，不授权安装 Hermes caller/prompt、选择投递目标或创建 job。

2026-10-17 市场 API/core 前向修复使用 clean reviewed HEAD
`d12dae330e91c7e58500188acfd45a6d91516ddd` 完成。生产写前暂停 Hermes job `ef7389b87a92`，以专用入口依次关闭
manual/automation 并证明 writer=`0|0|0`；PostgreSQL custom dump SHA-256 为
`abf58de8b5e11bde1e30069af8161ad2b3528118b650858bec95985515535bf8`，已在全新 PostgreSQL 16.4 隔离容器中单事务恢复。
最终镜像 `localhost/a-stock-market-environment:20261017-005702-d12dae3` 的 archive SHA-256 为
`4a4273de698dfaa1a710999f420cf2152e354835c3685dec84985faa6cfcf219`，containerd manifest digest 为
`sha256:28644467836cb5048e9be96005cdcb75bbaaf1334521c840655d685e4618d7e0`。受控 core repair 只执行一次真实 provider
调用，五个指数 history 尾日均为 `2026-10-16`；snapshot/aggregate payload `asOf` 均为 `2026-10-16`，对应 checksum
分别为 `3bb13c87…a122`、`68dd5ef7…c79`。index-history 可选日期参数修复后重新发布，overview、limit-up pool 和 legacy
core 均为 HTTP 200；limit-up 的 36 条事实因 `missing-board` 被合同过滤，空 items 不是接口错误。revision 141 以
同镜像无 hook 恢复 automation，revisions 142/143/144 通过普通 `component=all` 流程恢复 manual 并完成完整 release
收敛；最终两个 gate=`1|1`、writer=`0|0|0`、Pod Ready/0 restart、CronJob/Job absent，PVC/Secret UID 未漂移。
Hermes job 随后恢复为 active，下一次自然运行是 `2026-10-19T15:30:00+08:00`；未执行人工 `cron run`。

若出现异常请求、provider 压力、PostgreSQL 锁等待或数据库 PVC 增长，第一步暂停 Hermes job 并设置
`MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED=0`；manual 继续为 0。验证两个写入口都拒绝且没有新 run/provider
工作，同时保留 NodePort health 与 provider-free 读取。第二步从现场捕获的 pre-release chart、完整 values 与
不可变镜像 tag 执行新的 atomic upgrade；不得恢复含历史 CronJob 的 revision、uninstall release 或删除/替换
PVC。恢复后复核镜像、副本、安全上下文、PostgreSQL PVC UID、Secret 引用、schema、幂等/task 历史和快照读取。

前端可读性基线：全部可见文字（包括 ECharts 图例、坐标轴和 tooltip）不得小于 `14px`。修改页面样式后需检查 01 至 09 视图，并在桌面与移动宽度确认没有文字重叠、控件截断或页面级横向溢出；宽表自身的横向滚动属于预期行为。

前端时间显示由 `src/timezone.ts` 统一处理，禁止组件自行调用 `Intl.DateTimeFormat` 或 `toLocaleString` 渲染 ISO 时间。`/data-collection` 的“最近尝试”属于市场运行审计字段，固定按 `Asia/Shanghai` 显示，避免部署浏览器使用 UTC 时把盘后采集时间显示成非北京时间；其他页面时间继续按生效时区展示。`/settings` 的日期与时间页通过可选 `GET/PUT /api/preferences/timezone` 读取/保存个人和工作区 IANA 偏好；后端未部署时个人偏好使用浏览器 localStorage fallback，并在页面提示“接口尚未接入/离线”，不伪造工作区保存成功。验证时间层和设置状态：

```bash
npm run test --prefix apps/market-environment-dashboard
npm run build --prefix apps/market-environment-dashboard
```

新增或调整页面时，布局、组件、颜色、图表、状态和响应式验收遵循 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。

接口检查：

```bash
curl "http://127.0.0.1:8001/api/health"
curl "http://127.0.0.1:8001/api/market-environment?as_of=2026-08-28"
curl "http://127.0.0.1:8001/api/market-environment/core?as_of=2026-08-28"
curl "http://127.0.0.1:8001/api/market-environment/chapter-01?as_of=2026-08-28&section=breadth"
curl "http://127.0.0.1:8001/api/market-environment/data-collection"
curl "http://127.0.0.1:8001/api/market-environment/data-collection?as_of=2026-08-28"
```

`/api/market-environment` 保留完整聚合响应用于兼容；网页首屏使用 `/api/market-environment/core`，该接口不访问全 A、涨跌停池和行业 provider。章节接口的 `section` 支持 `breadth`、`limits`、`sectors`、`activeDirection` 和 `summary`，其中 `summary` 用于第 08、09 页并加载全部已接入章节证据。`chapter01` 仍是向后兼容的可选扩展。`breadth`、`sectors` 和 `activeDirection` 只在请求上海时区当前日期、且其实际交易日与最新市场快照一致时读取；查询历史日期时这些当前快照型数据集返回 `missing`，不得拿今日数据回填。`limits` 使用实际交易日查询日期化涨停/跌停/炸板池。所有数据集检查 `quality.status` 和 `quality.warnings`；缺失值保持 `null`，不要在前端转换为 0。`/api/market-environment/collection-runs/{run_id}` 的 task `timings` 同时承载数值耗时和 provider fallback 的来源、revision、失败证据字符串，客户端不得把该对象强制解析为纯数值表。

普通市场环境 GET 优先读取 PostgreSQL 中精确日期的数据集快照或 materialized aggregate，不自动启动 provider 采集。七类数据 `core`、`breadth`、`limits`、`industry-ranking`、`sector-turnover`、`sector-breadth` 和 `activeDirection` 分别使用 `(dataset, as_of)` lease；三项 THS 任务按依赖顺序运行，失败尝试保留同日期成功值并记录 warning，一键采集中的单项失败不会阻止无关结果保存。排查加载慢时分别查看 snapshot lookup、collection lease、provider collection、aggregate validation 和 PostgreSQL transaction/store write 计时。

盘后预计算：

```bash
python -m src.market_environment.cli snapshots refresh --as-of 2026-09-02
python -m src.market_environment.cli snapshots refresh --as-of 2026-09-02 --dataset core --dataset breadth --dataset limits --dataset sectors --dataset activeDirection
```

当前快照型 provider 默认只允许在上海时区目标市场日且达到结算时间后刷新；`--force` 用于显式本地诊断，并且是历史 latest-only 精确日期修复的唯一 CLI 许可。对已审计的 `2026-09-23` / `2026-09-24` 等错误快照，必须在生产 Pod 或其他明确绑定生产数据库的受控上下文中按原日期、指定 `breadth` / `activeDirection` 运行；逐日期核对 snapshot checksum、aggregate checksum、质量过滤统计和 collection run。普通 API、CronJob 与 provider-free GET 不获得该许可，也不得直接 SQL 修改 payload。命令输出每个数据集的 source、observations、duration、cache result 和 quality。单个数据集失败不会回滚其他成功数据集，也不会覆盖该日期上一次成功快照。

容量方向单项验证可运行 `python -m src.market_environment.cli snapshots refresh --as-of <上海市场当天> --dataset activeDirection --force`。采集先请求 `push2` 主域；连接/读取错误、429 或 5xx 在共享客户端有界恢复后仍失败，或主域载荷不满足契约时，再请求 `push2delay`。两个端点都必须返回至少 30 个含代码、名称和成交额的有效样本，并保持成交额非递增排序；数组、键值对象和已登记字段别名统一进入同一校验。延迟域成功时应看到 `source=eastmoney-clist-delay`、`quality.status=fallback` 和包含主域错误的 warning；两个端点都失败时，只有显式开启 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED=1` 才会尝试 TDX 派生路径，否则只保留同日期旧快照。派生成功应看到 `source=tdx-daily-package-derived`、`quality.status=fallback-derived`、`rankingMethod=local-turnover-desc-identity-asc` 和 TDX revision；同额记录按规范证券身份升序稳定排序。

### 通达信盘后包备用 probe

通达信备用只允许在上海市场收盘后、隔离网络输出目录中执行显式只读 probe。probe 不创建 collection run，不写 PostgreSQL、SQLite 或快照；`--allow-real` 是额外的本地授权开关，feature flag 仍保持默认关闭。示例：

```bash
.venv/bin/python -m src.market_environment.cli tdx real-probe \
  --as-of <已结算交易日> \
  --output <隔离输出目录>/tdx-probe.json \
  --allow-real
```

报告必须检查并记录 `requestedDate` 与 `sourceDate`、沪深北市场行数、总行数、有效行数、Top-N 名称覆盖率、`rankingMethod`、行业映射 revision/覆盖率、耗时、`sourceRevision` 和最终 `quality`。404 或空响应通常表示非交易日或盘后包尚未发布，应等待下一次获批盘后重试；不得用当前报价、前一日快照或零值把未发布包转成成功。probe 只写隔离的脱敏 JSON 报告，不创建 snapshot/database；`--allow-real` 是必要授权，报告不打印请求凭据。若 `breadth` 需要前收而当前包没有可用前收，只能使用精确交易日历指向的相邻上一交易日包，覆盖率不足即保持 `insufficient`。

probe 成功也不等于生产启用资格；启用前需审阅脱敏报告，并分别设置 `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED=1` 或 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED=1`。发现包格式、日期、排序或名称问题时，先将两个 TDX 开关保持为 `0`，重试或回滚不涉及数据库 schema、CronJob 或快照删除。activeDirection 派生路径的回滚只关闭 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED`，不改变 breadth 开关；恢复路径是重启采集进程并确认 Eastmoney 主/延迟链路和 provider-free 状态读取正常。禁止跨日期回填、删除 PVC、卸载 release 或执行生产写入命令。

2026-09-23 的 TrueNAS 发布已完成生产开关评审：`values-secure-manual-collection.yaml` 显式设置
`MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED=1`，仅用于 Eastmoney 两条广度路径失败后的
`breadth` 备用。真实包虽然通过日期、完整性、市场覆盖、名称和成交额字段验证，但原始成交额记录存在逆序，
因此 `activeDirection` 仍拒绝 TDX candidate，不得本地排序后伪造 Top-30 证据。该次发布使用
`20260923-185132-9a4910f` 镜像；当时曾通过现已退役的受控入口恢复 Kubernetes CronJob，并以
2026-09-24 自然触发 Job 作为首个生产验证。该段只保留历史事实：当前回滚只关闭对应 feature flag、
暂停 Hermes 并关闭 automation gate，再发布新的受审不可变 packet；不得执行旧 `--disable-schedule`
或恢复历史 CronJob。

### 第 02 页市场广度派生边界（2026-09-16）

第 02 页 "上涨家数、下跌家数和涨跌幅中位数" 在 provider 抓取的全 A 快照之上，由 `domain.analysis.breadth` 与 `BreadthHistoryReader` 串接派生指标：涨跌家数差、涨跌差率、4 条 250 日滚动分位（上涨占比 / 涨跌差率 / 中位数 / 5 日动量）、5 日动量、5 个指数与广度同向判定、6 档宽度标签（含自然语言依据）。历史来源固定为 PostgreSQL read repository 的精确日期 snapshot list/get，与第 01 章 `syncPattern` / `next-session` 共用同一 provider-free 读取路径；物化重建由 `MaterializationSupport` 复用同一纯分析组合。派生过程只读取本地快照，不调用 provider、不引入新的 API 路由、不修改 PostgreSQL schema、不增加新采集任务。`QTS-01-02-01..05` 规则 ID、阈值、权重与 YAML 保持不变；`rules validate` 仍输出 49 条规则。

排查 02 页 5 日趋势或 250 日分位缺失时：
- `breadth.history.validObservations` < 60 → 标注 `quality.status=insufficient`，3 个分位字段保持 `null`，不要补 0。
- `breadth.history.points` < 5 → 趋势表与折线图按已有天数渲染，不要用最近日期回填。
- `breadth.indexConsistent` 为 `null` → 5 个指数当日 `changePct` 全缺失时如实展示，不强行判定。
- `breadth.widthLabel="数据不足"` → 检查当日 `validCount == 0` 或 `quality.status in {missing, failed, insufficient}`。

### 第 03 页 limits 生态采集与验证

limits detail/V1 是独立于旧五字段池聚合的增量能力，由 `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED` 控制，默认值为 `0`。关闭时只提供既有 `limitUpCount`、`limitDownCount`、`failedLimitUpCount`、`failedLimitUpRatio`、`maxStreak` 和 PostgreSQL 快照读取；开启前必须在固定 fixture 上通过契约、Alembic schema、幂等、lease/CAS、失败保留、SQLite 导入源 `PRAGMA quick_check` 和 provider-free GET 验证。

扶摇作为三类池 membership 主源，必须校验交易日历、响应信封、逐页 `total/pages`、去重规范身份和日期冲突；池不回显日期时记录 `dateEvidence=request-parameter` warning。客户端在单个采集实例内串行控制扶摇请求间隔；HTTP 429、响应 `code=4001` 和 `code=5003` 使用较慢的有界指数退避，最终错误保留脱敏 `code`、`message` 和 `request_id`，不得记录 API key、请求头或完整响应体。东方财富用于降级和交叉核对，两源集合差异按规范身份取并集并标记 degraded。基础晋级只要求精确相邻交易日、两日完整涨停集合和规范身份；ST、上市窗口、制度和板块缺失只降低对应分层，不得阻断基础晋级。不得使用证券名称匹配、自然日减一或固定涨跌幅制度推断。

状态排查应同时查看 `/api/market-environment/data-collection?as_of=<date>` 和 limits snapshot：状态 GET 只读 PostgreSQL、provider 调用数为 0；每个 limits task 显示当前/前一样本日期、实际日期、observations、排除数、checksum、晋级依赖和 warning。单项重试只启动 limits task，不重跑 `core`、`breadth`、`sectors` 或 `activeDirection`。刷新失败只记录 attempt，并保留同日期最后成功值为 `failed-retained` / `degraded`；没有旧值才为 `failed-missing`。

晋级验证必须能审计昨日完整涨停 membership 集合与今日同 `security_id` 集合的交集。分母为 0 时晋级率为 `null`、质量为 `insufficient`，不得显示 `0%`。`--history-sessions 6` 按交易日历升序采集六日并生成最近五个晋级点；有效观测不足 60 时 250 日分位和规则周期结论保持 `insufficient`。`QTS-01-03-01` 至 `QTS-01-03-05` 继续为 `needs-backtest`。

真实 provider smoke 不属于普通测试，只能在获得明确授权的盘后窗口、隔离 PostgreSQL 数据库和本地命令中执行。SQLite fixture（例如 `.artifacts/market-environment/limits-smoke.sqlite3`）仅用于导入回归，不承载 smoke 运行时状态。示例命令必须替换为获批的两日参数，并记录 provider 请求预算、每池主/延迟来源、`dateEvidence`、实际/前一交易日、来源、字段覆盖、排除数、warning、dataset/row checksum、耗时和最终 `ok`/`fallback`/`degraded`/`insufficient`/`failed` 质量；缺少日期绑定或存在日期冲突时只保留失败审计，不写生产数据库；禁止复用生产数据库或将失败转成成功。

```bash
# 仅限已授权的盘后隔离 smoke；普通离线/PR 验证不得执行真实 provider
MARKET_ENVIRONMENT_LIMITS_V1_ENABLED=1 \
MARKET_ENVIRONMENT_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<isolated_db> \
MARKET_ENVIRONMENT_FUYAO_API_KEY=<secret> \
.venv/bin/python -m src.market_environment.cli snapshots refresh \
  --as-of <获批当前交易日> --dataset limits --history-sessions 6 --force
```

回滚时先将 `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED=0` 并重启 API/采集进程，再恢复应用版本。保留 PVC、旧五字段快照、`trading_sessions`、`limit_security_datasets`、`limit_security_facts` 和 checksum；不删除数据库、不回填其他日期，也不因回滚修改规则 ID、权重或校准状态。

盘后自动采集不再部署在 Kubernetes 内。当前唯一自动化合同是本 runbook 开头的 Hermes caller → full endpoint；
Chart/TrueNAS 脚本不提供 CronJob template、scheduling values、schedule component、offline/server schedule render
或 release/activate/disable mode。通用入口只允许 `--component all|database|service`，并在任何 build/write 前及
写后对 release-derived former name 与 `market-data-collection` 做 stored/live 只读 fail-closed 检查。

部署文档安全测试把 CommonMark shell fence 与 Bash AST 作为发布门禁。brace/glob executable expansion、`eval`、stdin-fed `bash`/`sh`/`dash`/`zsh`、`source`/`.`、`alias`/`hash -p` command-resolution mutation、动态 executable/action 和未知 Helm plugin/action 都必须返回 violation；无法解析或无法证明只读时 fail closed，不能因缺少字面量 `helm` 而跳过。

脚本把审阅后的 chart/baseline 复制到本次运行专属只读快照，重新校验 render hash，后续 Helm upgrade 只读取
该快照。实际 release 前验证 Helm 记录与 API server live Deployment/Service、两个 former CronJob identity，
绑定 Dashboard Pod 的 Deployment→ReplicaSet owner chain、ready 状态、精确镜像 tag、合法 CRI imageID，以及
目标 containerd tag→reviewed manifest digest；任一 drift 或状态不确定都拒绝。写操作使用 `helm upgrade --atomic`，
随后再次读取 live 资源并与冻结 manifest 比较；失败不修改遗留 CronJob，也不得把无法证明 absent 报告为成功。

第一版只用 cron 周范围排除周末，不维护交易所节假日日历。工作日节假日可能产生 failed/partial run；这是可审计的失败安全行为，任何 provider 无法证明属于当天的数据都不得落入当天快照。不要用 `--force` 或跨日期复制规避该限制。

配置：

### PostgreSQL 迁移与运行时边界

生产 Dashboard Deployment 与进程内采集 task 只通过 Helm 创建的 PostgreSQL ClusterIP Service 访问数据库，
不挂载 SQLite 或 PostgreSQL PVC。PostgreSQL StatefulSet 单副本独占 Retain RWO claim；数据库凭据必须由
部署前置步骤创建 existing Secret，至少包含 `DATABASE_URL`、`POSTGRES_USER`、`POSTGRES_PASSWORD` 和
`POSTGRES_DB`，Chart 不渲染明文凭据或外部监听器。

迁移前先暂停 Hermes job、关闭 automation/manual 两个写入开关，并证明两个历史 CronJob identity 与活动
collection writer 均不存在，再创建 SQLite before-image；迁移 Job 只读挂载旧 SQLite claim，执行
`python -m src.market_environment.cli database migrate --source /data/snapshots.sqlite3 --backup /tmp/snapshots-before-postgresql.sqlite3`
进行 dry-run。完成 quick-check、表统计、日期覆盖和 checksum 审核后，才显式增加 `--apply` 并切换
`MARKET_ENVIRONMENT_DATABASE_URL`。active lease 不迁移为有效所有权，改为可重试状态；旧 SQLite PVC 和备份
保留但脱离 Dashboard workload，禁止在普通发布中删除。

迁移 Job 必须继承 chart 的 Pod 级 `runAsUser/runAsGroup/fsGroup=10001`，否则 root-owned `emptyDir /tmp`
无法写入 before-image。CLI 对该已停写、只读挂载且已固定 SHA-256 的源使用 SQLite `immutable=1`，避免 WAL
数据库在只读卷上尝试创建锁或共享内存 sidecar；普通仍可能写入的 SQLite 读路径禁止使用该选项。
导入事实表会触发 PostgreSQL revision trigger；`materialization_component_versions` 冲突时必须保留源/目标中较大的
revision，不能使用通用 `DO NOTHING` 降低版本。导入重试应保持幂等，并再次通过逐表子集 checksum 校验。

PostgreSQL 首次写入前失败可恢复旧镜像和 SQLite PVC；首次写入后禁止回切过期 SQLite，必须使用 PostgreSQL
备份/恢复或前向修复。数据库不可达时服务 fail closed，不创建本地 SQLite 回退文件。

#### Secret、初始化和依赖顺序

Chart 不生成或渲染明文凭据。部署前由受控凭据系统或管理员创建 existing Secret（以下命令仅为本地示例，
不要把真实密码写入 shell history）：

```bash
kubectl -n a-stock create secret generic a-stock-postgresql \
  --from-literal=DATABASE_URL='postgresql+psycopg://<user>:<password>@a-stock-postgresql:5432/<db>' \
  --from-literal=POSTGRES_USER='<user>' \
  --from-literal=POSTGRES_PASSWORD='<password>' \
  --from-literal=POSTGRES_DB='<db>'
```

Helm render/deploy 必须提供 `database.existingSecret=a-stock-postgresql`（或等价 Secret 名称），并 fail closed
于缺失 Secret、缺失 key 或 URL 不合法。组件依赖固定为：

```text
PostgreSQL StatefulSet/ClusterIP Service ready
  -> Alembic schema migration Job (`alembic upgrade head`) 成功
  -> Dashboard Deployment rollout
  -> provider-free GET 与 automation gate 默认关闭验证
```

当前 runtime schema 最低版本为 11；`alembic upgrade head` 必须依次应用到
`0008_collection_idempotency`。Alembic revision ID 必须保持不超过默认
`alembic_version.version_num VARCHAR(32)`，不得为命名便利扩大版本表。`0004_sector_continuity`、
`0005_ths_sector_datasets` 和 `0006_ths_ranking_nullable_change_pct` 均不重写旧 `sectors` 快照、task、
capability 或聚合证据；0006 只解除 `ths_industry_rankings.change_pct` 的 NOT NULL 约束，0007 只删除不含
交易日的 `ths_catalog_revisions(provider, capability_revision, checksum, fetched_at)` 冗余唯一约束；0008
只增加 full-collection 幂等 binding、索引和 nullable structured failure，不删除 collection 历史。若 migration
Job 未达到 version 11，Dashboard service 与采集 command 必须保持 fail closed；不得通过应用启动时调用
`create_schema` 绕过 migration。

StatefulSet 未 ready 或 migration Job 失败时不得 rollout service 或开启 automation gate；migration Job 使用同一 URL Secret。
task 7.2 只执行 additive Alembic schema hook，不是 SQLite data-import Job；旧 SQLite migration/input/mount 必须关闭。
成功 hook 因 `hook-succeeded` 自动清理，以 database Helm write 成功、冻结 hook manifest hash、schema v11/`0008_collection_idempotency`
和成功后 namespace Job absent 共同作为切换证据；失败时保存脱敏的 Job YAML、UID、conditions/reason/timestamps、
Pod exit/status/logs、events、Helm status/history/revision、render/manifest hash 和 schema before/after，保持 manual、
automation 与 provider work 关闭。不得删除、重建或重试该 Job 来满足 absent check，task 7.2 保持未完成并等待
另行审核的修复。

#### 备份、恢复与切换边界

切换前暂停 Hermes job，设置 `MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED=0` 与
`MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`，证明两个历史 CronJob identity 不存在并等待正在进行的
collection task 结束；创建不可覆盖的 PostgreSQL `pg_dump --format=custom` 备份，记录 Service、PVC UID/PV、数据库版本、
`alembic_version`、文件 SHA-256 和恢复演练结果。SQLite before-image 仅由迁移工具在线 `backup()` 生成，
执行 `quick_check`、行数/主键范围/payload checksum 与日期覆盖校验后才可 `--apply` 导入。

迁移 Job 只读挂载旧 SQLite PVC，导入完成后执行逐表统计与 checksum 校验；active lease 不导入为有效所有权，
而是标记为过期/可重试并保留 fencing 审计。所有校验通过后才更新 Deployment 的 Secret 引用并 rollout，
执行 provider-free GET 与并发 lease/collection 离线验证；full endpoint canary 和 Hermes job 只能在另行授权的
生产阶段开启 automation gate 后执行。旧 SQLite PVC 与 before-image
继续保留但脱离应用挂载，清理另行授权。

PostgreSQL 首次写入前失败时，可恢复旧镜像并继续使用旧 SQLite（仅在尚未产生 PostgreSQL 事实写入的窗口内）；
一旦 PostgreSQL 产生新写入，禁止把过期 SQLite 当作事实源回切。此后只能从 PostgreSQL 备份恢复或执行前向修复，
并重新运行 checksum/日期/aggregate 校验。任何恢复都不得删除或覆盖原备份、PVC 或迁移 before-image。

恢复示例（仅对隔离目标执行，禁止指向生产数据库）：

```bash
export PGHOST="db.example.internal" PGUSER="restore_admin" PGDATABASE="market_restore"
createdb --host "$PGHOST" --username "$PGUSER" "$PGDATABASE"
pg_restore --clean --if-exists --no-owner \
  --dbname="postgresql://${PGUSER:?set PGUSER}:${PGPASSWORD:?set PGPASSWORD}@${PGHOST:?set PGHOST}:5432/${PGDATABASE:?set PGDATABASE}" \
  "${BACKUP_FILE:?set BACKUP_FILE}"
```

- `MARKET_ENVIRONMENT_DATABASE_URL`：PostgreSQL 运行时连接 URL（生产必需，通过 Secret 注入）。
- `MARKET_ENVIRONMENT_DB_POOL_SIZE`、`MARKET_ENVIRONMENT_DB_MAX_OVERFLOW`、`MARKET_ENVIRONMENT_DB_POOL_TIMEOUT`、`MARKET_ENVIRONMENT_DB_STATEMENT_TIMEOUT_MS`：PostgreSQL 连接池和语句超时。
- `MARKET_ENVIRONMENT_SNAPSHOT_PATH`：仅供一次性 SQLite 导入/日期审计工具使用，不是运行时存储配置。
- `MARKET_ENVIRONMENT_PERSISTENT_CACHE=0`：关闭持久缓存并回退到直接 provider 路径，用于紧急回滚。
- `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`：显式关闭数据采集页面写操作和 collection POST；默认开启。TrueNAS 固定 NodePort 是经负责人接受的例外，启用时向所有可路由客户端匿名开放写操作；出现异常时先将此项设为 `0`，再按现场捕获的回退基线决定网络入口。
- `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED=0`：关闭 limits detail/V1 事实写入和晋级扩展，继续服务旧五字段与 PostgreSQL 快照；开启前须完成离线门禁，真实 smoke 只能写隔离 PostgreSQL 数据库。
- `MARKET_ENVIRONMENT_FUYAO_API_KEY`：扶摇 provider 密钥，只能通过独立 Secret/进程环境注入；不得写入 values、日志、API 响应或仓库文件。V1 开启但变量缺失时采集失败并保留旧快照，普通 GET 仍可用。
- `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED=0` / `MARKET_ENVIRONMENT_FUYAO_BREADTH_ENABLED=0`：v2 core/breadth 主源开关，默认关闭；开启前必须存在状态为 `eligible` 且 revision 为 `fuyao-market-v2` 的 capability report。
- `MARKET_ENVIRONMENT_FUYAO_CORE_APPROVED_REVISION` / `MARKET_ENVIRONMENT_FUYAO_BREADTH_APPROVED_REVISION`：分别绑定 v2 capability report；为空、未知或与报告不匹配时 fail closed，不能用旧 `fuyao-market-v1` 绕过门禁。
- `MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED=0` / `MARKET_ENVIRONMENT_FUYAO_BREADTH_SHADOW_ENABLED=0`：只写 collection task shadow 元数据，不改变正式 source、快照或 checksum。
- `MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED=0`：行业扶摇 fallback 的数据集开关，默认关闭；只有 Eastmoney 两端点失败、capability report 为 `eligible` 且批准 revision 完全匹配时才可设为 `1`。
- `MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION`：显式绑定脱敏 capability report 的批准 revision；为空、未知或不匹配时 fail closed。该值不是 Secret，也不能替代 real probe/shadow 审批。
- `MARKET_ENVIRONMENT_FUYAO_SECTORS_SHADOW_ENABLED=0`：仅启用隔离 shadow 对账观测；shadow 失败只降低质量/可观测性，不得阻断已通过 capability 门禁的正式 fallback，也不得写入凭据。
- `MARKET_ENVIRONMENT_THS_WRITES_AUTHORIZED=0`：THS 目录同步、历史回填和成员事实导入的总写授权，默认关闭；只有显式 POST/CLI 还必须同时通过 manual-write、盘后、预算和 capability revision 门禁。
- `MARKET_ENVIRONMENT_FUYAO_THS_CATALOG_ENABLED=0` / `MARKET_ENVIRONMENT_FUYAO_THS_CATALOG_REVISION`：四类目录和完整快照能力开关及精确批准 revision，默认关闭/空；不匹配时在 provider I/O 前 fail closed。
- `MARKET_ENVIRONMENT_FUYAO_THS_HISTORY_ENABLED=0` / `MARKET_ENVIRONMENT_FUYAO_THS_HISTORY_REVISION`：单编号历史日 K 能力开关及精确批准 revision，默认关闭/空；最多近五年、单批最多 60 编号，按代码/窗口 checkpoint 恢复。
- `MARKET_ENVIRONMENT_FUYAO_THS_MEMBERSHIP_ENABLED=0` / `MARKET_ENVIRONMENT_FUYAO_THS_MEMBERSHIP_REVISION`：current membership 能力开关及精确批准 revision，默认关闭/空值；目录同步必须同时通过 catalog 与 membership capability，Top 10 与显式点选编号逐代码隔离失败。
- `MARKET_ENVIRONMENT_FUYAO_THS_DAILY_DUMP_ENABLED=0`、`MARKET_ENVIRONMENT_FUYAO_THS_INCREMENTAL_DUMP_ENABLED=0`、`MARKET_ENVIRONMENT_FUYAO_THS_ADJUSTMENT_DUMP_ENABLED=0`：三类成员事实导入能力分别门禁，默认全部关闭；revision 从受审 manifest 提供，预签名 URL、API key 和原始响应不得持久化或输出。官方 dump 必须逐行证明 `currency=CNY`、日 K `interval=1d`、`adjusted=none`、业务键唯一和 metadata checksum；未提供 SHA-256 时保持 `ineligible`。
- `MARKET_ENVIRONMENT_FUYAO_SECTORS_*` 仅保留给尚未切换的历史部署兼容和旧证据审计；新七数据集 coordinator、公共 API、CLI 每日 dataset selector 和前端不会读取或列出 `sectors`。
- `MARKET_ENVIRONMENT_EASTMONEY_SECTOR_ENRICHMENT_ENABLED=0`：扶摇行业基础结果的东方财富 dataapi 同供应商字段补充开关，默认关闭；开启仍需满足当前上海市场日、结算后、扶摇结果已接受和严格身份/口径门禁，不引入新 Secret。
- `MARKET_ENVIRONMENT_SETTLEMENT_TIME=15:10`：上海时区盘后结算边界；full automation endpoint 与显式维护采集在该时间前拒绝 provider I/O，Hermes 固定在 15:30 调用。
- 运行时不依赖 SQLite 文件；旧 SQLite 文件只能作为停写迁移源和归档，不能挂载给 Dashboard 或采集 task 作为共享协调边界。

开发期手工采集 API：

```bash
curl -X POST "http://127.0.0.1:8001/api/market-environment/collection-runs" -H "Content-Type: application/json" -d '{"asOf":"2026-09-03"}'
curl "http://127.0.0.1:8001/api/market-environment/collection-runs/<run-id>"
```

POST 立即返回 `202` 和 `runId`；省略 datasets 时创建七个独立 task，传 `{"datasets":["breadth"]}` 时只采集单项；请求依赖型 THS 任务会复用兼容本地前置结果或补入最小依赖链。父批次允许 `partial`，每个成功 task 独立提交；失败 task 不覆盖同日期旧值。显式请求 `sectors` 返回包含三个迁移目标的不支持错误且零 provider I/O。数据采集页 `/data-collection` 只通过 GET 查询本地状态，所有 provider 故障时仍应可打开。历史日期仅允许采集 provider 能验证日期的数据集；历史 THS 日线只能通过显式 backfill，历史 `sector-breadth` 不支持。服务重启后，遗留 collecting task 在 lease 过期后可重新采集。

数据采集页首次加载调用不带 `as_of` 的状态 GET，并用响应 `asOf` 初始化日期控件；后端按 `Asia/Shanghai` 解析有效市场日：开市前（09:30 前）返回上一工作日对应的真实交易日并跳过周末，节假日或没有可证明实际日期时返回 `insufficient`/拒绝，不猜测日期；开市后才返回上海当天。provider 返回的实际日期必须与目标 `as_of` 一致，无法证明时保持 `insufficient`/`failed`，不得通过改名或复制跨日期数据。用户手工切换日期后使用显式 `as_of`，历史限制继续生效。研究看板仍使用下述 15:00 结算日期逻辑，两者不要重新合并。

研究看板日期控件使用浏览器本地时间计算默认值：15:00 前为前一天，达到 15:00 后为当天；首次核心响应若确认候选日为非交易日，日期控件同步为响应的有效交易日；用户手工选择后不得自动改写。最大值始终为浏览器本地当天。不要改回 `new Date().toISOString().slice(0, 10)`，否则 UTC 转换可能导致日期错位。API 的默认日期与未来日期校验使用 `Asia/Shanghai`。市场广度直接从 `push2delay` 按涨跌幅排序分页定位边界与中位数，成功时 `chapter01.breadth.quality.source` 为 `eastmoney-clist-delay`、状态为 `fallback`。行业板块先请求 `push2`，连接/读取错误、429 和 5xx 有界重试后仍失败再请求 `push2delay`；403 不重试。延迟域成功时保留主域 warning，领涨股名称使用 `f128`，不得显示 `f140` 证券代码。容量方向的 Top-N 响应必须验证排序、最小样本和必需字段。任一采集失败时保留 `null` 或上一次精确日期成功值，并在 `quality.warnings` / `refreshWarning` 记录错误，不能用 0 填充。

指数 `history` 契约中的每个点应包含 `date`、`open`、`close`、`low`、`high`、`ma5`、`ma10`、`ma20`、`ma60` 和 `amount`。浏览器 QA 必须确认 60 日图存在非空 K 线实体、红涨绿跌、均线叠加和 OHLC tooltip；禁止用收盘价复制生成开高低。

指数 provider 默认拉取 280 根 K 线：mootdx `offset`、新浪 `datalen`、东方财富 `lmt`、腾讯 `param` 数量均按 280 请求，百度响应在本地最多保留 280 根。盘后显式冒烟应逐一记录五指数返回数量与冷缓存耗时；不足 280 根时不得伪造，只能按实际观测降置信。升级前已落 SQLite 的历史核心快照通常只含旧版 160 根输入，本次不回填，相关 250 日分位应保持 `insufficient-history` 或 reduced confidence。

指数卡的量价区域应先展示 `amountRatio5`，再展示可选的 `volumePriceState`。量价状态为 `null` 表示价格与成交额组合未命中任何明确规则，不是接口错误，前端不得改写为“量价平稳”；只有比值缺失时显示 `--` / “数据不足”。

每个指数的 `combination` 契约应包含 `key`、`state`、`matched`、`tone`、`evidence` 和 `tradingMode`。`chapter01.combinationOverview` 汇总 `strength`、`stage`、`capitalAcceptance`、`tradingMode`、`confidence` 和 `evidence`。浏览器 QA 必须切换至少两个指数，确认组合状态和证据同步变化；未命中状态显示“未命中明确组合”，不得补成六类中的任意一类。

第 01 页每张指数卡的收盘指数值与右侧涨跌幅必须分别可复制；复制控件不得触发卡片选中，成功状态需可访问。涨跌幅在页面上保留百分号，写入剪贴板时去掉百分号并保留正负号和两位小数。浏览器或权限不支持剪贴板时只能显示明确失败或受控降级，不得显示“已复制”。桌面和 390px 检查均需确认复制控件、反馈文字和卡片内容不重叠。

`summary.syncPattern` 只记录五指数当日方向模式；`summary.synchronizationAssessment` 是独立的联合研判，返回总状态、稳定结论码、中文结论、置信度，以及 `breadth`、`trend`、`turnover` 三项确认维度。排查结论时先核对原始模式，再逐项核对上涨占比/中位数、MA20 上下方指数数和 5 日成交额比值/放量下跌数，不能只看最终文案。权重指数领涨不等于个股偏弱，普遍走弱也不自动等于系统性下降。

广度改善或恶化只比较精确上一交易日：服务从核心指数历史取得前一交易日期，再读取该日期的 PostgreSQL `breadth` 快照。上一日记录缺失时 `previousAsOf` 与变化值保持 `null`、维度标记不足且整体置信度不高于中；不得向更早日期回退，普通 GET 的 provider 调用数必须仍为 0。需要补齐时先显式采集缺失交易日，再通过既有 collection/rebuild 路径重建目标日期聚合，不要直接修改数据库行或复制其他日期 payload。

第 01 页第四部分使用四问结论条、五指数乘六组合矩阵、选中行证据与盘后收束句。移动端矩阵允许组件内横向滚动，但页面本身不得横向溢出。`dataGaps` 四种 reason 必须显示差异化文案；风险相关缺失不能按安全处理。

本地门禁：

```bash
# 手动验证文档契约（快速 / 完整）
python scripts/check-docs-contract.py --mode=fast
python scripts/check-docs-contract.py --mode=full
python scripts/check_market_environment_architecture.py

# （重）安装本地 hooks
python scripts/install-hooks.py
```

`src/market_environment/AGENTS.md` 是该目录的导航文档，记录分层职责、稳定入口、legacy 兼容面、根级 shim 退役矩阵和“是否仍被运行时传递使用”的判断；它不能替代本文件中的生产操作边界。实现文件已按 `domain/analysis|policies`、`interfaces/http/schemas`、`infrastructure/persistence`、`infrastructure/providers/fuyao|tdx` 和 `infrastructure/collection` 归类，根级旧名仅用于明确登记的兼容导入。删除或迁移目录内大文件前，先按该文件的调用链清单执行 `rg` 检查，并建立或更新对应 active plan；不得把目录重构验证替换成真实 provider、生产数据库、Helm、Kubernetes 或调度写操作。

交易规则平台离线命令：

```bash
python -m src.trading_system.cli rules validate
python -m src.trading_system.cli rules coverage
python -m src.trading_system.cli docs sync-check
python -m src.trading_system.cli evaluate --rule-set market-environment --snapshot tests/fixtures/trading-system/market-environment-complete.json --output .artifacts/evidence
python -m src.trading_system.cli evidence verify .artifacts/evidence
```

创建快照与回测：

```bash
python -m src.trading_system.cli snapshot create --as-of 2026-08-31 --output .artifacts/snapshot.json
python -m src.trading_system.cli backtest --rule-set market-environment --snapshots .artifacts/history --output .artifacts/backtest.json
```

PR 验证必须只使用 `tests/fixtures/trading-system/`，不得访问外部网络。盘后 workflow 可访问真实数据；任何 provider 失败必须写入 snapshot 的质量状态，并上传 `degraded` 或 `insufficient` 证据，不能用 0 填充缺失数据。

### 交易知识 MCP（本地离线）

知识库索引只消费 `搭建交易系统/`、`搭建交易系统-量化版/`、`trading-rules/` 和 Git 中的 `evidence/` 摘要。索引文件位于被忽略的 `.artifacts/knowledge-base/knowledge.sqlite3`，可以删除后重建，不是生产数据库或市场环境快照。

首次构建或源文件变更后重建：

```bash
python -m src.trading_knowledge.cli index build --repo-root /home/gyt/a-stock
python -m src.trading_knowledge.cli index status --repo-root /home/gyt/a-stock
python -m src.trading_knowledge.cli search --repo-root /home/gyt/a-stock "防守或空仓" --source-layer quantified
python -m src.trading_knowledge.cli rule --repo-root /home/gyt/a-stock QTS-01-01-01
python -m src.trading_knowledge.cli evidence --repo-root /home/gyt/a-stock --rule-id QTS-01-01-01
```

索引构建会先执行规则注册和覆盖校验，再写入临时 SQLite 文件并原子替换；解析失败、重复规则 ID、文档引用断裂或校验失败时返回非零，不替换旧索引。查询发现源文件 hash 漂移会返回 `stale`，必须重新构建，不能手工修改 SQLite。

将本地服务注册到 Codex（只修改当前用户的 Codex 配置，不提交配置文件）：

```bash
codex mcp add trading-knowledge -- \
  /home/gyt/a-stock/.venv/bin/python -m src.trading_knowledge.mcp_server \
  --repo-root /home/gyt/a-stock
codex mcp list
```

服务通过 stdio 暴露且只有五个只读工具：`search_trading_knowledge`、`get_source_excerpt`、`get_rule`、`get_evidence_status`、`get_index_status`。它不访问网络、行情 provider、生产 PostgreSQL、交易账户或 shell；`documented-only`、`needs-backtest`、`unverified`、`insufficient` 和 `degraded` 不会被改写成 `validated`。

### 历史审计：Helm schedule 组件（已退役，不可执行）

本节仅保留 revision 20、106、107 的历史操作与验收语义，下面出现的 template、values、overlay、
`--release-suspended`、`--activate-schedule`、`--disable-schedule` 和 schedule component 均已从当前仓库删除，
不得复制执行或作为回滚路径。当前合同以本 runbook 开头的 Hermes 所有权章节为准；普通部署只做两个 former
CronJob identity 的 stored/live 只读拒绝。

适用：TrueNAS k3s 1.26.6 上的盘后采集调度。release-derived `a-stock-data-collection` 与 Dashboard / PostgreSQL 同属 Helm release `a-stock`；仓库不再保留独立 operator override 清单、脚本或 `market-environment-data` PVC/PV/StorageClass。CronJob 通过 `a-stock-postgresql` ClusterIP Service 和同名 Secret 访问 PostgreSQL，不挂载数据库 PVC。

**fail-closed 默认：**

- 当时 chart 的 fail-closed 默认是 `scheduledCollection.enabled=false / suspend=true`；当前 chart 已删除该 values 块，普通 `all` / `database` / `service` 发布不得渲染 CronJob。
- `deploy/truenas/values-scheduled-baseline-20260917.yaml` 是 2026-09-17 合并所有权使用的受版本控制 baseline：冻结镜像 `localhost/a-stock-market-environment:20260917-113516-b5be526`，引用 `a-stock-postgresql` Secret 与 `a-stock-data` existingClaim，调度为 `enabled=true / suspend=true`。
- k3s 1.26.6 使用 `timezoneStrategy: controller`，省略 `spec.timeZone`。目标 controller 已验证为 `Asia/Shanghai`，因此上海 16:30 使用 `30 16 * * 1-5`。任何时区证据变化都必须停止 schedule write；不得把该值静默改成 `30 8`。
- `controllerCanaryVerified=false` 保持 suspended release；激活 overlay 只有在 canary evidence 完整并由本次操作责任人书面确认后才允许设为 `true`。

**独立 CronJob 迁移到 Helm（一次性）：**

迁移必须在 16:30 之外执行；先确认无 active Job。下列命令只描述受控顺序，任何失败都停止并保留 `suspend=true`：

```bash
# 1. 只读快照；保留到本次 plan 的 Completion Evidence
kubectl get cronjob,pvc,pv,sc,job -n a-stock
helm list -n a-stock
kubectl get cronjob market-data-collection -n a-stock -o yaml \
  > /tmp/legacy-cronjob-snapshot.yaml

# 2. 确认没有 active Job 后，删除非 Helm-owned 同名对象
kubectl delete cronjob market-data-collection -n a-stock

# 3. 由专用入口重新创建为 Helm-owned 且 suspended
bash scripts/deploy-truenas-k3s.sh \
  --release-suspended \
  --baseline-values deploy/truenas/values-scheduled-baseline-20260917.yaml \
  --scheduling-overlay deploy/truenas/values-scheduled-suspended.yaml \
  --kube-version 1.26.6

# 4. 精确读回
kubectl get cronjob a-stock-data-collection -n a-stock -o yaml
helm get manifest a-stock -n a-stock
```

读回必须同时满足：`app.kubernetes.io/managed-by=Helm`、`SUSPEND=True`、schedule `30 16 * * 1-5`、无 `spec.timeZone`、`concurrencyPolicy=Forbid`、deadlines 1800/3600、镜像与 baseline 一致、安全上下文完整。任一不满足都停止，使用 `/tmp/legacy-cronjob-snapshot.yaml` 与合并前 Helm revision 分析回滚；不得临时裸 apply。

**孤立存储清理：**

只有在 Helm-owned CronJob 已读回且确认没有 Pod 引用 `market-environment-data` 后，才按 exact 名称删除旧资源；这些资源不是 PostgreSQL PVC，也不是 `a-stock-data`：

```bash
kubectl delete job market-data-verify -n a-stock
kubectl delete pvc market-environment-data -n a-stock
kubectl delete pv a-stock-market-environment-data
```

`manual-local` StorageClass 不是孤立资源：现场只读发现确认 `a-stock-data` 与其它 namespace 的 `manual-postgres-pv` 都使用它，因此必须保留。删除主机目录前先记录 `/mnt/xiaomi/app-data` 与目标子目录权限；再删除 exact `/mnt/xiaomi/app-data/a-stock-market-environment` 子目录并把父目录权限恢复到与同级一致。禁止使用未展开变量、glob 或宽范围递归删除。

**当时的后续激活与回退（历史合同，不可执行）：**

- 激活只允许专用 `--activate-schedule` 入口，使用 `deploy/truenas/values-scheduled-active.yaml`，要求 `controllerCanaryVerified=true`、完整 `FROZEN_IMAGE_*` 三元组和明确 catch-up 策略。
- 回退只允许 `--disable-schedule` 或 `helm rollback a-stock <合并前 revision>`。不得执行 raw `helm uninstall`，不得重建独立 CronJob。
- 激活后第一次交易日 16:30 必须观察 Job/Pod、PostgreSQL collection run、dataset quality 与 `/api/market-environment` 响应；provider 失败保留 `partial` / `degraded` / `insufficient`，不得伪造 success。

2026-09-17 生产基线为 Helm revision 20：`a-stock-postgresql` 与 Dashboard 均 Ready，唯一 CronJob
`a-stock-data-collection` 为 Helm-owned 且 `suspend=true`。SQLite 历史已导入 PostgreSQL；验收读取使用
`/api/market-environment?as_of=2026-09-16` 和 `/api/market-environment/core?as_of=2026-09-16`，均返回
200、5 个指数且无顶层 data gap。盘中默认当天尚未采集时返回 503 属于 exact-date fail-closed，不得改为静默回退。

2026-10-14 历史 THS change 的生产激活曾沿用同一受控入口：revision 105 的完整 THS-on/schedule-off release 先经
`--release-suspended` 创建 revision 106，再以 `ACTIVATION_CATCH_UP_MODE=next-schedule` 经
`--activate-schedule` 生成 revision 107。两次时间窗校验均指向当日 16:30（Asia/Shanghai）；106 到 107
的 stored manifest 只允许 `spec.suspend: true -> false`。写后必须确认 CronJob UID 不变、ACTIVE=0、
LAST SCHEDULE 为空、namespace Job 为空、冻结镜像/PVC/Secret/schema/活动 run-task 均不漂移。首次自然
触发后再验收七数据集和 Chapter 01；provider 失败保留真实质量状态，禁止通过一次性 Job 或手工 provider
调用补造成功记录。

## 第 05 页申万一级行业持续性与历史回填（规划 runbook）

本能力尚处文档与离线设计阶段。以下流程只定义未来实施的 fail-closed 边界，不代表已批准任何新数据源、生产迁移或回填。

### 离线 fixture 与 capability report

- PR/CI 只使用固定、脱敏 fixture，覆盖申万 taxonomy 变迁、股票跨行业生效区间、北交所 `920xxx`、退市/停牌、除权除息、TDX 原始成交额、benchmark 缺日、重复身份和混合日期；不得提交真实生产快照。
- `shenwan-taxonomy`、`shenwan-point-in-time-membership`、`stock-adjusted-price`、`tdx-original-daily-facts`、`benchmark-history` 必须分别出具 capability report，包含精确日期语义、沪深北覆盖、字段解释、source/revision/checksum、分页/重复处理、权限/限频、数据权利和失败负例。报告状态仅允许 `eligible`、`ineligible`、`unverified`；缺报告、过期、冲突或未批准时零 provider I/O、零正式事实写入。
- 附件 `a-share-free-data-api.html` 及其中列出的 Baostock、mootdx、Tushare/JQData 等只作为候选源目录，不构成批准证据、数据权利证明或生产接入许可。客户端代码许可证与底层数据使用条款必须分开审阅；自动采集、长期存储和派生展示均需单独确认。
- 真实 probe 只能由明确授权的盘后隔离命令执行，输出脱敏 capability evidence，不写正式 snapshot、analysis、PostgreSQL 或 SQLite 运行时状态；不得把 probe 成功自动升级为 capability 或打开 feature flag。
- 当前离线契约可用以下命令生成零网络、零正式写入的脱敏 dry-run 报告；`--allow-real` 仅用于后续另行授权的盘后隔离 probe，且仍需环境门禁、上海时间 15:30 后和显式 provider-neutral adapter：

  ```bash
  python -m src.market_environment.cli industry-capability-probe \
    --dataset stock-adjusted-price \
    --source baostock \
    --revision baostock-adjusted-v1 \
    --as-of YYYY-MM-DD \
    --output /tmp/industry-capability-dry-run.json
  ```

  该命令默认 `status=dry-run`、`networkCalls=0`、`formalWrites=0`；当前仓库未配置正式 source adapter，不能把命令成功当作任何来源已批准。
- 数据权利审阅必须拆分记录：Baostock/mootdx/Tushare/JQData 的客户端代码许可证不等于底层行情、申万分类或衍生展示授权；申万公开表还需单独核对自动采集、长期存储、历史成员重放和对外派生展示边界。任何一项未获书面确认时，报告保持 `unverified`，不允许回填或生产写入。

### additive migration 与运行时边界

- 新 taxonomy/membership/security fact/benchmark/aggregate/continuity/backfill 表只能通过 PostgreSQL additive migration 增加，必须演练 upgrade、rollback、migrate-again 和现有五数据集不变性；禁止覆写旧 snapshot、task、aggregate、PVC 或历史 checksum。
- PostgreSQL repository 与 `MarketEnvironmentUnitOfWork` 负责精确业务键、revision/checksum、事务、lease/fencing 和 CAS；普通 GET、状态读取和启动必须保持 provider-free，七数据集“全部采集”和默认调度不得隐式触发历史 backfill 或 dump 导入。
- `SectorEvidence.analysis` 为可选字段。observation、analysis、attempt 三套 quality/status 独立保存；同日兼容结果可标记 `failed-retained`，无兼容结果才是 `failed-missing`，不得跨日期替代。
- snapshot v2 的 closed `metricProvenance` 只从同日 materialized analysis 复制五项 canonical 指标；冻结 v1 replay 继续有效。任何 provenance/data revision 变化都形成新 identity；输出 evidence bundle ID 不得自引用 snapshot hash。

### 显式 backfill、恢复与回滚

- backfill 是独立、有界、可恢复的 application/CLI workflow，不是第六个 collection dataset。请求必须包含权威交易日历解析出的有限交易日范围、批准的 source/domain/classification/calculation revisions 和可恢复 run identity；首次预热默认 272 个交易日，也可请求小范围修复或更长研究区间。
- 运行按交易日逐日执行输入 → 聚合 → 分析，记录 parent run 与 per-date attempt、coverage、warnings、retry eligibility 和 `success` / `partial` / `failed-retained` / `failed-missing` / `insufficient`。已成功且版本兼容的日期跳过；中断后只重试未完成日期；新 revision 不静默重写旧证据。
- 数据管理页只读展示 readiness、required/available history、missing sessions、版本、最近 attempt 和重试资格，不提供普通 backfill 按钮；任何运维启动、生产非 fixture 回填、数据库 migration、部署或调度激活均需额外明确授权和 plan Completion Evidence。
- 失败恢复先保留同日成功值与 attempt 审计，再按原 revision 重试；不得删除证据、PVC、Secret、Job 或旧 checksum，不得用当前 membership、其他日期排名、零值或最新-only provider 补齐历史。回滚只关闭新 feature/版本并保留数据与审计，禁止回切过期 SQLite，也不得恢复 Kubernetes 调度。

### 预热生产路径（需另行授权）

生产前顺序固定为：固定 clean reviewed source/fixture/capability packet → 离线 schema/fixture replay → 隔离数据库 additive migration 演练 → 小范围交易日回填 → 60 日覆盖 → 272 日默认预热 → 更长研究范围。每一步都需核对 exact-date、taxonomy/membership、universe、adjustment、benchmark、input checksum 和 quality；任一失败保持 `insufficient`/`failed-*`，不扩大范围。真实 provider probe、PostgreSQL migration、非 fixture 回填、部署、Secret 变更、automation gate 或 Hermes job 变更均不得混入普通测试。

## 验证矩阵

| 检查 | 命令 / 方法 | 证据位置 | 必需 |
|------|-------------|----------|------|
| docs-contract | `python scripts/check-docs-contract.py --mode=full` | 终端输出 / plan 的 Completion Evidence | 是 |
| hooks 连通 | `git config core.hooksPath`（应为 `.githooks`） | 终端输出 | 是 |
| Build | `npm run build --prefix apps/market-environment-dashboard` | 终端输出 / plan | 是 |
| Backend tests | `.venv` Python 下运行 `python -m pytest tests -q` | 终端输出 / plan | 是 |
| Acquisition/registry | typed outcome、完整 registry、formal/fallback/shadow/enrichment、exact-date、redaction 和 provider-free projector 离线 fixture | pytest / plan | 是 |
| Transport engines | requests/Scrapling 共用 success/rate-limit/permission/challenge/malformed/date-mismatch fixture；验证单一 retry budget、无自动升级和敏感信息脱敏 | pytest / plan | 启用本变更时是 |
| Enhanced profile | base/enhanced 依赖解析、镜像构建、Helm 离线 render、镜像体积/启动/CPU/内存/临时存储/SBOM/漏洞差异；不得运行真实 provider | 终端输出 / plan | 引入 Scrapling profile 时是 |
| k3s manifests | `kubectl kustomize deploy/k3s` 与所有保留的 Helm/TrueNAS profile 都不含 application CronJob；仓库搜索不存在 native scheduled overlay 或正向 schedule manifest，普通部署仅保留两个 former identity 的负向检测 | 终端输出 / plan | 是 |
| Helm chart | `helm lint deploy/helm/a-stock` 与 `helm template a-stock deploy/helm/a-stock --namespace a-stock` | 终端输出 / plan | 是 |
| Snapshot refresh | 普通 PR/本变更只用 fake provider/临时存储验证 `python -m src.market_environment.cli snapshots refresh --as-of <date>` 等价路径；真实 provider 命令仅在另行授权的盘后隔离环境运行 | CLI JSON / plan | 是 |
| Collection management | 启用开发开关后验证状态 GET、单项 POST、全部 POST、轮询和 partial 结果 | pytest / 浏览器 / plan | 是 |
| Automated collection | full endpoint 的 success/partial/failed/skipped/settlement/lease/idempotency/202/restart 固定 fake-provider 回归；Hermes caller/prompt fake-server/golden 测试；所有 Helm/Kustomize profile 无 CronJob，部署 guard 能拒绝两个旧 identity | pytest / render / plan | 是 |
| Warm cache | 对已预计算日期请求 Chapter 01，确认 provider 0 调用且 <500ms | pytest / plan | 是 |
| Frontend build | `npm run build --prefix apps/market-environment-dashboard` | 终端输出 / plan | 是 |
| Browser QA | 启动前后端后检查 01 至 09 视图的桌面与移动宽度、最小 `14px` 字号和溢出；01 页检查真实 OHLC K 线、均线和 tooltip；确认首屏先于章节数据出现、章节失败不清空核心数据 | 截图 / plan | 是 |
| Rule registry | `python -m src.trading_system.cli rules validate` | 终端输出 / PR workflow | 是 |
| Rule coverage | `python -m src.trading_system.cli rules coverage` | `trading-rules/coverage.yaml` / PR workflow | 是 |
| Deterministic replay | 固定 fixture 执行两次并比较 canonical result | pytest / golden fixture | 是 |
| Evidence verification | `python -m src.trading_system.cli evidence verify <bundle>` | manifest / CI Artifact | 是 |

## 常见调试路径

- **pre-commit / pre-push 未触发**：`git config core.hooksPath` 是否为 `.githooks`；不是则跑 `python scripts/install-hooks.py`。
- **API 返回 503**：先检查 `/api/health`，再查看服务日志中的各指数数据源错误；mootdx 失败时应看到百度或腾讯降级 warning。
- **核心接口冷启动仍较慢**：分别计时 `/api/market-environment/core` 与章节接口。若核心接口慢且 warning 显示通达信不可用，当前实现仍会为五个指数串行执行既定降级链；不要通过跳过价格交叉校验换速度，后续应以独立熔断或线程安全并发方案处理。
- **成交额比值显示 `--`**：腾讯历史 K 线公共接口可能只提供成交量而无成交额；服务会先尝试新浪指数 K 线（用腾讯实时成交额校准），再尝试东方财富显式指数 K 线，最后降级到腾讯。若所有历史成交额源均不可用，保留 `--`，不要把缺失成交额当成 0。
- **有 5 日成交额比值但没有量价状态**：该日价格变化与比值处于已定义规则之间的空档，属于预期的未分类状态；不要在 API 或前端增加兜底分类。
- **组合判断显示“未命中明确组合”**：先核对 API 的 `combination.evidence` 和量化版 `0.2` 映射。六类条件要求同时成立，单独处于高位、放量或站上均线都不足以形成组合状态。
- **同步模式与最终结论不同**：这是两阶段模型的预期行为。`syncPattern` 记录指数方向，`synchronizationAssessment.status` 说明广度、趋势和成交额是否确认；查看 `dimensions` 中的实际值和 reason，不要改写原始模式。
- **同步上涨但显示“反驳”**：检查上涨占比是否不高于 45% 且中位数小于 0；这代表指数上涨没有得到多数个股确认，不应改成全面强势。
- **普遍走弱但未显示系统性下降**：必须同时满足弱广度、至少三个指数位于 MA20 下方和至少三个指数放量下跌。缺少或未命中任一维度时只保留普遍走弱风险提示。
- **上一交易日广度为不足**：从指数 history 确认 `previousAsOf`，再检查 PostgreSQL 是否存在该精确日期的 `breadth` 成功快照；更早快照不会被采用，GET 也不会自动联网补采。
- **第 01 章证据显示 `missing` / `partial`**：先看对应对象的 `quality.warnings`。历史日期缺少广度、板块或成交额榜是当前快照源的预期边界；东方财富 403 或空 `data` 也必须保留缺失状态，不能用空数组伪造为 0。只有接口成功且明确返回空 `pool` 时，涨跌停计数才可为 0。
- **章节显示 `cacheState=stale`**：查看 `snapshotFetchedAt` 和 `refreshWarning`；旧值仍对应同一交易日，但后台刷新失败或尚在进行。不要删除旧快照后用其他日期数据替代。
- **refresh 一直显示被占用**：检查 PostgreSQL 中同 dataset/date 的 lease；正常 lease 会在有界时间后过期。仅在确认没有刷新进程后使用 CLI 强制重试，不要直接修改 lease/fencing 字段。
- **数据采集批次显示 `partial`**：查看每个 task 的 warning；成功 task 已独立保存，只对失败行执行重新采集，不要删除整批成功快照。
- **最近采集失败但数据仍可用**：这是 `failed-retained`，页面继续服务同日期最后成功值并展示刷新错误；只有 `failed-missing` 才表示该日期没有可用数据。
- **数据采集按钮不可用**：检查 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 是否被显式设为 `0`，并检查所选日期和 provider 日期能力；不要用强制参数把最新快照写成历史日期。
- **Hermes 没有触发**：先检查 gateway health、顶层 `timezone`/`HERMES_TIMEZONE`、cron `30 15 * * 1-5`、
  `next_run_at`、caller checksum 和 automation gate。16:00 后不得补跑该 slot，也不得创建 Kubernetes Job 代替。
- **full endpoint 返回 partial/failed**：读取同一 run 的七个 task `failure` 与 warning；terminal 业务失败仍是 HTTP 200，
  成功兄弟任务已经落盘。不要用新 key 自动整批重试，针对性恢复需要另行明确操作。
- **Hermes 超时或返回 still running**：按响应的 `statusUrl` 做 provider-free 读取；重放必须沿用相同
  `Idempotency-Key` 且不得启动替代批次。若需停止后续触发，暂停 Hermes 并关闭 automation gate，不删除活动历史。
- **节假日出现 failed/partial**：第一版预期会在周一至周五节假日触发；确认没有跨日期 snapshot 后保留审计记录，不要伪造当天成功。
- **行业板块采集偶发 `RemoteDisconnected`**：确认请求经过共享串行门；主域会先执行有限连接重试，再降级到 `push2delay`。若两个域都失败，查看 task warning 和同日期 snapshot 是否触发 `failed-retained`，不要删除旧值或跨日期回填。
- **容量方向采集为 `failed-missing`**：先检查 warning 是否为 `push2` 主域断连，并确认实现已继续请求 `push2delay`。延迟域成功应记录 `eastmoney-clist-delay` / `fallback`；若延迟域少于 30 个有效样本、缺少代码/名称/成交额或排序异常，必须继续视为失败。存在同日期成功值时应为 `failed-retained`，不要用其他日期或零值替代。
- **容量方向采集为 `failed-missing`**：先检查 warning 是否为 `push2` 主域断连或载荷无效，并确认实现已继续请求 `push2delay`。延迟域成功应记录 `eastmoney-clist-delay` / `fallback`；若延迟域少于 30 个有效样本、缺少代码/名称/成交额或排序异常，必须继续视为失败。存在同日期成功值时应为 `failed-retained`，不要用其他日期或零值替代。
- **TDX breadth/activeDirection 样本异常**：先查看 `quality.stockUniversePolicyVersion`、`stockUniverseRawCount`、`stockUniverseRetainedCount`、`stockUniverseExcludedCount`、`stockUniverseUnclassifiedCount`、`stockUniverseRetainedByMarket` 和 `stockUniverseExcludedByReason`。`observations`、`validCount`、上涨/下跌/平盘计数和 TDX 派生成交额 Top-N 只能来自保留普通 A 股；约 5 万行通常表示把基金、债券或指数混入了全证券包，不能按前端重复计算处理。
- **TDX 过滤后不足或分类未知**：确认请求日期、包日期、三地市场覆盖和 `tdx-stock-universe-v1` 规则版本；缺少市场、未分类行超阈值或过滤后样本不足时必须为 `insufficient`/`failed`。不要根据名称、价格、成交额猜股票类型，也不要把原始 `marketCounts` 当作普通股票数。
- **修复 2026-09-23/2026-09-24 错误 breadth 快照**：先完成应用离线验证和只读 probe，再经单独授权对原日期分别执行精确日期重采集；成功才原子替换同日期 payload 并核对 checksum/聚合，失败记录 `failed-retained` 或 `failed-missing`。普通 GET 不联网修复，不直接 SQL 改 payload，不跨日期改名或回填；回滚只关闭对应 TDX 开关并保留快照和审计记录。
- **涨跌停生态采集为 `failed-missing`**：逐池检查 `push2ex` 主域和兼容延迟域的请求记录。延迟池成功时必须在池证据中记录 fallback 来源和主域错误；缺少顶层日期但请求 `date` 明确时应记录 `dateEvidence=request-parameter`，显式行日期冲突、池格式无效或两端点均失败时仍保持 `failed`/`insufficient`，不得把空响应当作 0 或跨日期回填。
- **需要紧急回滚持久缓存**：设置 `MARKET_ENVIRONMENT_PERSISTENT_CACHE=0` 并重启 API；PostgreSQL 数据库和旧 SQLite 归档均保留用于诊断，不需要删除。
- **指数价格异常**：检查实时腾讯报价是否可用。沪市歧义代码没有实时交叉校验时，mootdx/百度结果会被拒绝，避免错误股票数据进入页面。
- **hook 报 `\r` 相关错误**：`.githooks/*` 行尾被改为 CRLF，恢复 LF（`.gitattributes` 已强制 `eol=lf`，重新 checkout 即可）。
- **gate 误报需要紧急绕过**：优先修文档；确需绕过用 commit message 标记（`[skip-plan]` / `[no-docs]` + 理由）或环境变量（见 `AGENTS.md` 逃生口）。
- **规则加载失败**：先运行 `rules validate`；重复 ID、未知字段、未知 evaluator、阈值无来源或非法生命周期都会在执行前失败。
- **盘后证据显示 degraded/insufficient**：检查 manifest 的 provider 状态和 warnings。东方财富 403 不应循环重试；切换到降级源或等待下一次运行。
- **证据校验失败**：不要手改证据文件。重新从原 snapshot、规则版本和 Git SHA 执行；manifest 中任一 SHA-256 不一致都视为证据失效。

## 运维控制

- hook 逃生开关：`SKIP_DOCS_CONTRACT=1`（仅应急，须在 plan 或 commit message 记录原因）。

## 看板图表空白排障

- 第 01 章出现有高度但无内容的价格或成交额图表时，先确认 `GET /api/market-environment/core?as_of=<date>` 返回 `indices[*].history`，且每个指数至少有一条历史记录。
- 若 API 数据完整，检查浏览器页面是否刚结束“正在读取本节证据”状态。图表容器会随该加载态被替换，前端应在加载开始时释放旧实例，并在加载结束后的下一轮 DOM 更新中重新初始化 ECharts。
- 浏览器验收应确认 `.price-chart canvas` 和 `.volume-chart canvas` 均存在，容器尺寸非零，且截图中同时可见 K 线、均线和成交额柱状图；仅看到空白容器不算通过。

## 失败解读指引

gate 输出的每条错误消息都自带修复指引（对应 `AGENTS.md` 硬规则编号语义）。修改 `scripts/check-docs-contract.py` 的消息文案时必须同步 `AGENTS.md`。


## 前端路由 history mode SPA fallback（2026-09-16）

市场环境看板从单一 App.vue 路由壳演进为
ue-router history mode 后，直接刷新或通过 URL 直接访问非根路径会先打到后端静态服务，必须配置 SPA fallback，否则返回 404。

### 触发条件

用户访问任一非 / 路径并触发浏览器刷新：

- http://host/dashboard/03 → 直接 404（如果未配置 fallback）
- http://host/settings → 直接 404
- http://host/data-collection → 直接 404

内部 <RouterLink> 与
outer.push 不会触发此问题，因为它们走 pushState / popstate，不重新加载 HTML。

### 部署侧要求

- 开发环境（Vite dev server）：自动 fallback，无需额外配置。
ite.config.ts 已配置 server.proxy 到 /api。
- TrueNAS k3s Ingress 部署：Ingress 必须配置
ginx.ingress.kubernetes.io/rewrite-target: / 或同等的 fallback annotation；Helm chart 尚未升级此配置（属于
rontend-component-split change 的 Phase 4 任务 4.8）。
- TrueNAS NodePort 直连：使用 kubectl port-forward 或 NodePort 直连 Vite 静态构建产物（pps/market-environment-dashboard/dist/index.html），需要在静态文件服务器（nginx / caddy）侧配置 SPA fallback：
  - nginx: 	ry_files \ \/ /index.html;
  - caddy: 	ry_files {path} /index.html
- 本地纯静态托管：同上，静态文件服务器需配置 SPA fallback。

### 与现有部署路径的交叉

- 当前 pps/market-environment-dashboard/dist/ 不存在（本次提交未构建），待首次
pm run build 后产出。
- Ingress / NodePort 部署清单（deploy/truenas/、deploy/k3s/）暂未升级 Vue 路由 + SPA fallback 配置；属于后续 Phase 4 任务 4.8 范围，本次提交不交付。

### 验证

- 部署后手动刷新任一 /dashboard/03 / /settings / /data-collection URL，必须返回 200 与前端 HTML。
- 测试命令（开发）：
pm run dev --prefix apps/market-environment-dashboard 后浏览器访问 http://localhost:5173/dashboard/03，应渲染 03 章节占位内容（本次提交占位为 DashboardPlaceholder）。

## legacy hash 重定向（2026-09-16）

旧版看板使用 #document-03 锚点定位章节。
outer/legacy-redirect.ts 在
outer.beforeEach 钩子里检测 window.location.hash，匹配 #document-(0[1-9])$ 时调用
outer.replace('/dashboard/N') 重写路径并清空 hash。

### 行为

- https://host/#document-03 → 重写为 https://host/dashboard/03，hash 清空，不留历史记录
- https://host/#some-anchor → 不动（路由按当前路径解析）
- 已经处于 /dashboard/03 的链接 → 不重复重写
- SPA fallback 不会与 legacy hash 冲突：fallback 服务返回 index.html 后前端 router 接管，legacy-redirect 在路由解析的 eforeEach 阶段生效。

## ECharts 生命周期（2026-09-16 frontend-component-split Phase A）

市场环境看板前端 ECharts 实例通过 composables/useChartLifecycle.ts 统一管理。每个图表面板组件（IndexPriceChartPanel / VolumeChartPanel / BreadthHistoryChartPanel）在 <script setup> 顶层调：

`	s
const lc = useChartLifecycle(elementRef, () => optionFactory(props))
``n
### 行为

- onMounted 调 echarts.init(elementRef.value) + setOption(optionFactory())。
- 若传入第三个参数 watchSources，则 watch(watchSources, () => setOption(optionFactory())))) 在数据源变化时重画（不重建实例）。
- window.addEventListener('resize', resize) 监听浏览器 resize，触发 chart.resize()，不 dispose。
- onBeforeUnmount 调 chart.dispose() 并清空引用——实例随组件生命周期一起销毁，不再有全局协调。

### 调用方约束

- **绝不**在组件外持有 let chart: echarts.ECharts | null = null 闭包变量；composable 自己负责。
- **绝不**在父组件里同时存在多个 chart 实例共享一个 DOM 节点——每个 panel 一个 ref + 一个 composable。
- 旧版 App.vue 里的 chart / volumeChart / breadthChart 三个全局闭包变量与 renderChart / disposeCharts / resizeCharts / renderBreadthChart / disposeBreadthChart 函数在 Phase C（App.vue 收尾）时删除。Phase A 只新增 composable，不动 App.vue。

### 调试

- 图表不显示：检查 elementRef.value 在 onMounted 时是否非 null（happy-dom 下 <div ref=...> 立即可用）。
- 图表不响应数据变化：检查 watchSources 是否返回 reactive 引用；直接传对象会丢失响应性。
- 图表 resize 后位置错乱：检查 chart.setOption(optionFactory(), { notMerge: true }) —— notMerge 确保选项整体替换而非合并。

## useDocumentContext 边界（2026-09-16 frontend-component-split Phase A）

composables/useDocumentContext.ts 是 9 章节组件的公共派生与 label 字典聚合。

### 边界

- **仅暴露** ComputedRef 与纯函数：breadth / limits 派生、quality / reason / environment / gap label 字典、formatRatioDelta / formatReturnDelta。
- **绝不暴露**任何 setXxx / loadXxx 写操作。章节组件如需触发刷新 / 日期变更等写操作，必须通过 defineExpose / emit 委托给 DashboardLayout 或 App.vue 路由壳。
- useMarketStore() 仅在 setup 顶层调用一次（不暴露给外部）。

### 调试

- 章节测试报错 Cannot read properties of undefined：检查 setActivePinia(createPinia()) 后是否手动 market.data = fixture 预填；composable 派生全部基于 market.breadth / market.limits，store 为 null 时返回空数组/默认值。
- 测试通过但运行时报 isSupportedTimeZone 异常：检查 fixtures 里的 timezone 字段是否使用 IANA 标准名（如 Asia/Shanghai），而非 CST / GMT+8。

## 章节页面组件（2026-09-16 frontend-component-split Phase B-01/B-02）

第 01、02 章已拆为独立页面组件（Document01IndexPricePage / Document02BreadthPage），配套三个 chart panel。

### 章节 fixture 预填约定

- 独立挂载页面组件时，fetch mock 不会自动生效——必须在 setActivePinia 后显式调用 market.loadCore()（或手动赋值 market.data）预填数据，再 mount。直接 mount 页面组件而 store 为 null 时，页面只渲染 page-flow-label 与空 section，测试会拿到空 DOM。
- 溢出断言：页面组件挂载后没有 App.vue 的 .content-shell 节点，390px 视口检查应针对 wrapper.element（页面根元素）而非壳层节点。

### chart panel 调试

- IndexPriceChartPanel 的 K 线 tooltip 由组件内 formatPriceTooltip 提供，从 App.vue 迁移时签名保持一致（接受 echarts params 数组）。
- BreadthHistoryChartPanel 的当日标记：advanceRatio / medianReturn props 非空且历史 points 为空时，图上只画当日单点；历史 points 非空时当日数据以 props 追加判断，与旧 App.vue renderBreadthChart 行为一致。
- 三个 panel 均 useChartLifecycle 持有实例；测试里 vi.mock('echarts') 后可断言 init/setOption/dispose 调用次数。

## Document03 预填与刷新约定（2026-09-16 frontend-component-split Phase B-03）

第 03 章（涨跌停）数据来自 chapter-01?section=limits，与第 01、02 章的 core 直出不同。独立挂载 Document03LimitsPage 时 fixture 预填必须走两步：先 market.loadCore()（满足 store 的 coreRequestedDate 前置条件），再 market.loadSection('limits')（拉取章节合并进 chapter01）。只调 loadCore 的话 market.limits 为 undefined，页面会渲染全部空态。

### section 刷新 emit 边界

- 组件内刷新按钮不直接调 store action，只 emit('refreshSection')。
- 测试在 mount 时通过 onRefreshSection prop 接线回 market.loadSection('limits', true)，验证 emit 边界的完整性。
- 刷新失败场景（fixture 第二次 chapter-01 返回 502）：store 的 sectionStates.limits 落入 error phase，组件的 limits-refresh-error 块显示 detail 并保留旧证据，与原 App.vue 行为一致。

## Document04 fixture 约定

第 04 章与第 03 章共享 `chapter-01?section=limits`：高/中/低位 fixture 写入 `limits.stratifications` 的 `risk_tier` 行，修复率写入 `limits.riskEvidence` 的 `failure-repair` 行。独立挂载时先 `market.loadCore()` 再 `market.loadSection('limits')`；每项缺失独立显示 `--`。

## Document05-09 章节组件约定（2026-09-16 frontend-component-split Phase B-05..B-09）

第 05 至 09 章均为 core 直出章节：独立挂载时 market.data = fixture 即可，无需 loadSection。第 09 章 meta.section = null，页面依赖已加载状态，不触发自己的预拉；NextSessionPanel(mode=summary) 读 market.nextSessionComparison。

### 事件时间显示

Document07EventsPage 的事件时间用纯 formatDateTime 并显式传入 preferences.effectiveTimeZone；fixture 的 publishedAt 必须带时区后缀（Z 或 +08:00），否则 parseTimestamp 按 '--' 处理，页面显示"时间未标注"。

### 09 章空态语义

assessment.state=insufficient 时页面显示：分数不足 / 暂无完整证据链 / 当前未返回已触发的风险否决 / 数据不足，等待新增证据。测试与 UI 均按这四个固定文案断言，改动文案需同步 Document09AssessmentPage.test.ts。

## 嵌套路由守卫与章节预拉（2026-09-16 frontend-component-split Phase C）

/dashboard 现为嵌套路由：父级 DashboardLayout，9 个 children 各带 meta.section。守卫在 router/guards.ts 的 registerRouterGuards(router) 工厂中注册，生产入口与测试共用。

### 守卫行为

- legacy hash（#document-N）一次性重写为 /dashboard/N。
- 进入 /dashboard/* 且 market.data 为空 → await market.loadCore()（阻塞，首次进入必须有核心数据）。
- 目标章节 meta.section 非空且未在 market.loadedSections → void market.loadSection(section)（不阻塞，fire-and-forget）。
- 07、09 两章 meta.section = null，不触发预拉。

### 章节写操作边界

章节组件唯一允许的 store 写通道是 emit 上抛：selectIndex（01 章选指数）与 refreshSection（03 章刷新）由 DashboardLayout 在 RouterView 的 slot props 上统一接线。剪贴板复制（01 章指数值/涨跌幅/复盘句、02 章验证项）为纯 UI 行为，组件内部消化，不经过 store。

### 测试挂载约定（更新）

- app.test.ts 挂 App 时必须 createRouter + registerRouterGuards（守卫不再挂在测试自建 router 上会直接导致 loadCore 不执行、页面停在 loading 态）。
- chart lifecycle 测试语义已更新：路由切换时旧章节组件卸载（dispose 其 echarts 实例）、新章节挂载（init 新实例），断言 init/dispose 累计次数（01→02→01 为 init 2→3→5、dispose 0→2→3）。
- 扶摇能力验证：使用脱敏 fixture 执行 `python -m src.market_environment.cli fuyao capability-probe --fixture tests/fixtures/market-environment/fuyao-market-data.json --as-of YYYY-MM-DD --path /tmp/fuyao-capability.sqlite3`。该命令不访问网络；core 报告必须同时证明五个指数和至少 280 根有效 K 线，breadth 报告必须证明完整分页与稳定 timestamp；报告为 `ineligible`/`unverified` 时不得填写批准 revision。当前通用能力 revision 为 `fuyao-market-v2`，旧 `fuyao-market-v1` 不得用于 core/breadth/activeDirection 的批准。
- v2 数据集边界：`core` 使用 `/api/a-share-index/prices/historical`，逐指数传 `thscode`、`interval=1d`、上海时区 `start/end` 毫秒时间戳；每项必须有 OHLC、成交额且最后有效 `date_ms` 等于 `as_of`。当前日期还必须有独立腾讯报价校验，历史日期不得调用实时报价。`breadth` 使用 `/api/a-share/prices/snapshot`，按 `limit/offset` 拉完 `total`；所有页的 `total` 和规范身份集合必须稳定，每页 `timestamp` 均须存在且映射到同一上海交易日；原始值允许漂移但要保留 exact/date stability 与 span 证据。历史 breadth 只读本地精确快照，Fuyao latest-only 接口不得回填历史。
- 分数据集切换：批准并启用 `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED=1` 或 `MARKET_ENVIRONMENT_FUYAO_BREADTH_ENABLED=1` 后，core 链为 `Fuyao -> mootdx -> baidu -> sina -> tencent -> Eastmoney`，breadth 链为 `Fuyao -> TDX`（仅在 `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED=1` 时）`-> Eastmoney`。`limits` 仍为 Fuyao 主源加东方财富交叉核对/降级；旧 `sectors` fallback 仅属于历史部署与审计契约，仓库公共运行时改用三个独立 THS 数据集；`activeDirection` 不进入 Fuyao 切换，继续 Eastmoney/TDX。
- 请求预算和回滚：limits 与通用 Fuyao 客户端共享 composition root 的进程级 policy gateway、host budget、single-flight、熔断和最小间隔；网络/408/429/5xx 只由 gateway 重试，HTTP 200 内 `4001`/`5003` 等业务码只由 adapter 有界慢退避，不能叠加第二套 transport limiter/retry。缺 API key 时零 I/O，401/403 快速失败，最终错误只记录脱敏 `code/message/request_id`。出现 429、权限、字段、日期或分页异常时，先关闭对应 `MARKET_ENVIRONMENT_FUYAO_<DATASET>_ENABLED` 或移除批准 revision，保留旧快照与 task 记录，不删除 PVC、不跨日期回填。
- 真实验证只能在盘后、显式本地隔离路径执行：`python -m src.market_environment.cli fuyao real-probe --allow-real --as-of YYYY-MM-DD --path /tmp/fuyao-real.sqlite3 --output /tmp/fuyao-real.json`，API key 仅来自 `MARKET_ENVIRONMENT_FUYAO_API_KEY`。缺 key、日期不一致、权限/限流错误均 fail closed。
- 行业 real probe 必须明确记录扶摇的交易日历、同花顺行业目录和行业快照三个 endpoint，以及目录/快照覆盖和快照时间戳日期一致性；快照 `data.timestamp` 是响应时间戳，分批原始毫秒值可以不同，但必须全部映射到同一精确上海交易日。报告必须说明行业 fallback 不提供主力净流入、上涨/下跌家数或领涨股，缺失字段保持 `null`，不得以代码或零值填充。
- 回滚按数据集清除 `MARKET_ENVIRONMENT_FUYAO_<DATASET>_ENABLED` 或批准 revision；保留能力报告、任务元数据和同日期旧快照，不跨日期回填。Secret 不写入 values、日志、fixture 或 API 响应。
