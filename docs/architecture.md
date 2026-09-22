# 架构

## 多页市场研判重构边界（2026-09-14）

市场环境 Dashboard 保持 01–09 独立路由和按需章节加载。第 01 页的七项复盘证据与 `ReviewSentence` 在计算层由五项指数和精确市场广度聚合生成；第 09 页仅消费综合摘要。`GET /api/market-environment/next-session` 是 provider-free 只读路径：服务从 `trading_sessions` 解析严格大于 `as_of` 的最小真实交易日，并读取该日核心/广度 materialized aggregate，缺失返回 `pending` 或 `insufficient`，不触发采集、不跨日期回退。新增 schema 为 additive，旧 `summarySentence`、`syncPattern` 和组合矩阵字段继续兼容。看板不保存用户复盘记录、输入或训练进度。

### PostgreSQL 运行时存储边界（2026-09-16）

生产运行时状态统一保存到 Helm/k3s 管理的单主 PostgreSQL StatefulSet。Dashboard Deployment 与盘后 CronJob 通过内部 ClusterIP Service 和 `MARKET_ENVIRONMENT_DATABASE_URL` Secret 连接，不挂载数据库 PVC，也不创建或读取共享 SQLite 文件。PostgreSQL 独占自己的 Retain RWO PVC；单主、无复制和自动故障切换是当前明确边界。SQLite 只作为停写迁移的只读输入和归档，不是运行时回退路径。

> 状态：**已落地第 01 章市场环境看板与交易规则工程平台首期**。产品范围见 `docs/product-specs/market-environment-dashboard.md` 与 `docs/product-specs/trading-rule-engineering.md`；看板视觉与交互约束见 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。

### 第 02 页市场广度派生边界（2026-09-16）

第 02 页 "上涨家数、下跌家数和涨跌幅中位数" 在 provider 抓取的全 A 快照基础上，由 `MarketEnvironmentService._enrich_breadth` 在每次章节请求时串接派生指标：涨跌家数差、涨跌差率、4 条 250 日滚动分位（上涨占比 / 涨跌差率 / 中位数 / 5 日动量）、5 日动量、5 个指数与广度同向判定、6 档宽度标签（含自然语言依据）。历史来源固定为 `SnapshotStore.list_snapshot_dates("breadth")` + `SnapshotStore.get("breadth", date)`，与第 01 章 `syncPattern` / `next-session` 共用同一快照读取路径；不引入新的 provider、API 路由、PostgreSQL schema 或采集任务。所有新字段为可空，缺失样本数 < 60 时整段标注 `insufficient`，不补 0。前端 02 页由 2 section 替换为 5 section（复盘卡 / 量化证据 / 近 5 日趋势 / 指数一致性矩阵 / 次交易日验证项 + 质量元数据）；新增独立 `breadthChart` ECharts 实例，与指数 K 线 `chart` / 成交量 `volumeChart` 数据源和生命周期独立。`QTS-01-02-01..05` 的规则 ID、阈值、权重与 YAML 保持不变。

## 系统角色

市场环境看板面向盘后研究，前端用于选择交易日、比较指数、查看解释和在开发阶段管理数据采集；后端负责行情获取、指标计算、数据质量标记、独立任务协调、快照持久化和降级。

交易规则平台面向盘后研究、规则维护和审计。YAML 注册表是机器执行事实源，量化版 Markdown 是人读解释层；执行器只读取规范化快照，不直接依赖网络 provider。

## 交易规则平台

```text
trading-rules/ YAML + schema + coverage
        │
        ▼
src/trading_system/rules/ ── evaluator registry
        │
snapshot JSON ──► evaluation ──► trace + aggregate result
        │                              │
        └──────────────────────────────► evidence manifest + SHA-256
                                               │
                                      backtest / CI Artifact
```

- `rules`：闭合 schema、类型化加载、规则生命周期、文档同步和覆盖检查。
- `data`：规范化快照、结构化人工事件、provider 质量和 canonical hashing。
- `evaluation`：稳定 evaluator 注册表、五档评分、缺失策略、置信度、否决和逐规则 trace。
- `evidence`：manifest、输入与结果哈希、Git SHA、provider 状态和篡改校验。
- `backtest`：按交易日回放、样本切分、成本、覆盖缺口和验证证据。
- `cli`：提供规则校验、快照、执行、回测、证据和文档同步命令。

## 主要数据源

| 优先级 | 数据源 | 用途 |
|---|---|---|
| 1 | mootdx（通达信 TCP） | 历史日线、均线、区间和成交额 |
| 2 | 百度股市通 K 线 | mootdx 失败时的历史降级 |
| 3 | 新浪指数 K 线 | 指数历史成交量；按腾讯实时成交额校准历史成交额 |
| 4 | 东方财富历史 K 线 | 显式市场 `secid` 降级源；提供指数历史成交额 |
| 5 | 腾讯历史 K 线 | 最后历史降级；可能没有成交额 |
| 6 | 腾讯财经实时行情 | 当前报价、涨跌幅、成交额和历史价格交叉校验 |

市场环境 API 通过可选的 `chapter01` 对象扩展第 01 章证据。市场广度直接使用东方财富 `push2delay` 的涨跌幅排序分页，定位正负边界和有效样本中位数，不再先尝试被上游限制为不完整行数的名义全 A 主快照；容量方向按成交额排序请求 Top-N 股票，`push2` 主域恢复失败或返回无效载荷后降级到同口径 `push2delay`，两个来源统一校验代码、名称、成交额、至少 30 个有效样本和成交额非递增排序。涨跌停生态以扶摇日期化三类池为 membership 主源、东方财富为降级和交叉核对源；扶摇分页必须覆盖 `pagination.total`，请求日期先由交易日历确认并记录 `dateEvidence=request-parameter`，两源按规范证券身份取并集，差异行和整日质量标记 `degraded`。行业板块排名继续使用东方财富主域到延迟域降级，行业领涨股名称取 `f128`，`f140` 仅为代码。当前快照型 provider 仅允许在上海时区的有效市场日采集；已持久化的精确快照可用于对应历史日期，禁止拿其他日期或今日数据回填。未接入的独立亏钱收益和事件输入保持 `null` / `insufficient`，并附 provider quality 和 warning。

研究看板交易日输入按浏览器本地时区生成：本地时间 15:00 前默认选择前一天，达到 15:00 后默认选择当天；首次核心响应若确认候选日为非交易日，前端只将自动日期同步为响应的有效 `asOf`，用户仍可在日期控件中手动选择不晚于当天的日期且手动值不被覆盖。数据采集页不复用研究页的 15:00 截止逻辑，但会在上海开市前（09:30）将省略 `as_of` 的请求解析为上一工作日对应的真实交易日（周末跳过）；若遇节假日或存储中没有可证明的实际日期，返回 `insufficient`/拒绝，不能猜测日期。开市前 provider 只能返回前一交易日数据时，必须以该实际日期保存，禁止将前一日行情写入当日键。开市后才允许按上海当天采集当前快照，用户手工切换后才发送显式日期。API 默认日期、“当前快照”判断和有效市场日解析统一使用 `Asia/Shanghai`，避免浏览器 UTC 转换或服务端部署时区把“今天”错位为前一日。东方财富全 A 快照解析同时接受数组和键值对象形式的 `data.diff`，仅保留有效对象行，并校验实际行数覆盖 `data.total` 后才允许按完整快照计算。

网页使用固定一级导航 `如何判断市场环境`，下设 01 至 09 文档视图；侧边栏另设“数据管理”入口 `/data-collection`，不改变交易知识文档层级。研究视图只解释 API 已返回的证据与质量状态，数据采集页只读取本地任务和快照状态并提供受控写操作；前端不补算缺失指标，不把未验证阈值渲染为确定性评分。所有可见界面文字和图表标签以 `14px` 为最小字号，标题与关键数字在此基础上维持层级。移动端将导航收纳为抽屉，宽表或采集状态行必须在自身容器内适配，页面不得横向溢出。
网页使用固定一级导航 `如何判断市场环境`，下设 01 至 09 文档视图；侧边栏另设“数据管理”入口 `/data-collection`，不改变交易知识文档层级。研究视图只解释 API 已返回的证据与质量状态，数据采集页只读取本地任务和快照状态并提供受控写操作；前端不补算缺失指标，不把未验证阈值渲染为确定性评分。第 01 页指数卡的指数主值和涨跌幅是独立复制交互，涨跌幅展示保留百分号而复制值去掉百分号，Clipboard API 不可用时只允许显式失败或受控降级，不伪造成功。所有可见界面文字和图表标签以 `14px` 为最小字号，标题与关键数字在此基础上维持层级。移动端将导航收纳为抽屉，宽表或采集状态行必须在自身容器内适配，页面不得横向溢出。

规则平台扩展数据包括全市场宽度、涨跌停/炸板池、板块与成交集中度、流动性和事件输入。行情优先 mootdx/腾讯，百度/新浪/东方财富作为明确降级；东方财富请求必须经单进程共享请求门串行执行，锁覆盖限流等待和完整 HTTP 请求，间隔至少 1 秒并加入抖动。连接/读取错误、429 和 5xx 使用有界退避重试，403 不盲目重试。公告、政策和突发事件必须保存来源与有效期；无法观测的主体意图不进入自动评分。

指数代码始终使用 `sh000001`、`sz399001` 等显式前缀。对百度/mootdx 存在沪市代码歧义的指数，必须有腾讯价格交叉校验，否则拒绝该源，避免股票数据静默冒充指数。

## 运行时流

普通读取流为：浏览器 → Vite `/api` 代理 → FastAPI `src/market_environment/api.py` → `MarketEnvironmentService` → PostgreSQL materialized aggregate / snapshot store。`/api/market-environment`、`/core` 和 `/chapter-01` 优先读取精确日期本地结果，缺失、陈旧或活动采集不得在普通 GET 中启动外部 provider。

手工采集流为：`/data-collection` → collection run API → 有界进程内 executor → collection coordinator → 五个独立 dataset task → provider 适配层 → 成功快照 → 聚合响应重建。父批次只汇总 `success` / `partial` / `failed`；`core`、`breadth`、`limits`、`sectors` 和 `activeDirection` 各自持有 `(dataset, as_of)` lease，单项失败不停止后续任务，也不覆盖同日期成功快照。不同 task 可以由 executor 调度，但共享东方财富请求门保证供应商调用不并发；CLI 与 HTTP 复用同一 coordinator，不通过 shell 启动子进程。

盘后定时采集流为：k3s/Helm CronJob → `python -m src.market_environment.cli snapshots scheduled-refresh` → collection coordinator → 同一组五类独立 task → PostgreSQL Service。CLI 在 Python 内按 `Asia/Shanghai` 解析日期，周末无 provider 调用并返回 skipped，结算边界前拒绝执行；CronJob 使用显式 timezone strategy：Kubernetes 1.27+ 的 native strategy 才输出 `spec.timeZone: Asia/Shanghai`，k3s 1.26 的 controller strategy 省略该字段且只允许经验证的 `Etc/UTC` 或 `Asia/Shanghai` 映射。CronJob 默认业务目标为工作日 16:30、`concurrencyPolicy: Forbid` 且不对 `partial` 自动整批重试；controller strategy 在获授权 no-provider canary 证明之前必须保持 suspend。CronJob 与人工触发并发时由 PostgreSQL dataset/date lease 作为最终去重边界。第一版不维护交易所节假日日历，工作日节假日可能留下 failed/partial 记录，但精确日期校验禁止把其他交易日数据写成当天。

生产部署使用单镜像边界：Node 构建阶段生成 `apps/market-environment-dashboard/dist`，Python 运行阶段由 FastAPI 同时托管静态网页与 `/api`。Dashboard-only 的原生 k3s Kustomize base 位于 `deploy/k3s/`；带原生 CronJob timezone 的显式 overlay 位于 `deploy/k3s-native-scheduled/`，只能由 `scripts/render-k3s.py` 在 Kubernetes 1.27+ 边界内渲染；k3s 1.26 使用 `deploy/helm/a-stock/` 的 controller strategy。Helm 默认 `enabled=false`、`suspend=true`；通用 Dashboard install/upgrade/application rollback 只通过 `scripts/deploy-truenas-k3s.sh`，使用完整受版本控制的 baseline values 且不带 scheduling overlay，不得继承 release 历史 values、直接执行 Helm write、执行原始 uninstall 或恢复历史 revision。普通入口从 Helm render 解析 release-derived exact CronJob 名称，按该名称读取 API live state而不依赖可漂移 instance label；它在构建和目标写入前、Helm write 前分别证明 stored Helm manifest 与 live release 均无 application CronJob，active/suspended 状态必须先经单独审核和授权的 `--disable-schedule` 删除。入口在任何网络前冻结 chart、调用方 values 和 overlay，在最终 values 生成后记录 disabled render hash，并在 Helm write 前从同一只读 packet 重渲染和比对；Helm 不再读取可变 repo chart。普通写入成功后再次证明 exact live CronJob absent；失败、信号或写后读取异常会把 validator 绑定的意外 active CronJob 精确补偿为 suspended 并重读验证，无法证明 absent/suspended 时保持 uncertain/NO-GO。默认路径为 Traefik Ingress → ClusterIP Service → 单副本 Deployment，也允许在没有 Ingress Controller 的单节点环境显式使用 NodePort Service。TrueNAS scheduling packet 必须为 baseline 加一个 ordered overlay；离线 render、只读 discovery、精确 suspended-CronJob admission probe、suspended release 与 `--activate-schedule` 是相互独立的操作。read-only discovery 只绑定 clean reviewed HEAD/chart 并发现实际 release/namespace/version；从 admission 起才要求实际版本派生的 frozen chart/baseline/overlay/render hashes。入口在任何网络、构建或写操作前校验最终合并后的 typed Helm values、目标 release/namespace 和 `enabled/suspend`，禁止同次运行更新仓库；admission 仅提交该 namespace 中的 exact suspended CronJob。实际 release 只从本次只读快照读取审阅 packet，拒绝 Helm/live drift，绑定 Deployment→ReplicaSet→ready Dashboard Pod 与 containerd tag 的精确 digest，使用 atomic upgrade 并校验 server-observed postcondition；激活只允许已审阅的 `/spec/suspend` 单字段差异，失败时先补偿暂停 exact CronJob。入口不会自行创建 canary/Job。生产顺序固定为 read-only preflight → frozen exact packet review → exact admission → no-provider canary → 非覆盖备份 → suspended release → 一次性 provider-backed Job → 证据审阅 → 明确 catch-up 的激活决策 → activation；任何步骤缺失或失败都保持 `suspend=true`，不进入 Helm write。TrueNAS 直连候选为明文 HTTP `NodePort:32001` 且手工写入口开启，没有应用身份认证、TLS 或请求级授权；安全边界是所有实际可路由到节点端口的网络，不能声称仅限用户、设备或子网，且不得配置公网映射。1.21 的部署控制面与应用入口分离：Helm/kubectl 默认通过仅绑定 1.21 回环地址的临时 SSH 隧道连接 TrueNAS `127.0.0.1:6443`，不要求将 k3s API 放行给局域网。两条路径均通过 PostgreSQL ClusterIP Service 访问共享状态；只有 PostgreSQL StatefulSet 持久化到独立 Retain RWO PVC，Dashboard 与 CronJob 不挂载任何数据库 PVC。当前 PostgreSQL 事务、lease/fencing 和 provider 限流按单主边界设计，因此默认保持一个 Uvicorn 进程和一个 Dashboard Pod；扩展为多副本前必须先引入高可用 PostgreSQL/协调方案。Dashboard 与 CronJob Pod 都需要访问通达信 TCP 及外部 HTTPS 行情源，健康探针只访问不触发外部 provider 的 `/api/health`。

TrueNAS 的 `market-data-collection` CronJob 与 Dashboard / PostgreSQL 统一归属 Helm release `a-stock`；仓库不再保留 operator override 清单、修正脚本或其独立 `market-environment-data` PVC/PV/StorageClass。k3s 1.26 使用 Helm `controller` strategy：目标 controller 已验证为 `Asia/Shanghai`，因此上海 16:30 使用 `30 16 * * 1-5` 并省略 `spec.timeZone`；CronJob 通过 `market-environment-postgresql` Service 与 `a-stock-postgresql` Secret 访问 PostgreSQL，不挂载数据库 PVC。调度发布只允许 `scripts/deploy-truenas-k3s.sh` 的 `--release-suspended` / `--activate-schedule` / `--disable-schedule` 专用入口，默认 `suspend=true`。Kubernetes 1.27+ 的 native timezone 清单继续只存在于 `deploy/k3s-native-scheduled/`，不得把该 overlay 用于 TrueNAS 1.26。

普通 TrueNAS Helm 组件发布同时按 release 派生的 exact 名称和固定的独立 override 名称 `market-data-collection` 查询调度状态；独立 CronJob 存在时，即使 Helm stored manifest 的调度为 absent，也必须先取得该资源专属的操作/回滚授权并完成更新或安全停止。该检查只读且 fail closed，不把 PostgreSQL StatefulSet/PVC 纳入 override ownership，不以修改普通部署入口替代独立调度变更入口。独立 CronJob 的镜像修复使用单独的 exact-image 入口，只允许在旧镜像、调度、安全上下文和 PostgreSQL Service/Secret 引用均未漂移时替换 collector image。离线 render 可使用任意 release/namespace 检查渲染，目标组件写入必须验证受审 baseline 的 release/namespace，且在引用前先解析调用方默认值。

### TrueNAS k3s 组件化部署边界

`scripts/deploy-truenas-k3s.sh` 是 TrueNAS 的唯一组件入口，`--component` 取值为
`all`、`database`、`service`、`schedule`。四种操作共享同一个 Helm release、release name、
namespace 和受审 values packet；组件选择只改变本次期望资源集合，不创建竞争性的 Helm
release。`all` 的依赖图固定为 `postgresql -> schema migration -> service -> schedule`：

- `database` 负责 PostgreSQL StatefulSet、ClusterIP、existingSecret 合同和独立 Retain RWO
  claim；旧 SQLite claim 只作为显式迁移源验证，不由 Dashboard/CronJob 挂载，且不被隐式删除、
  替换、扩容或重新绑定。
- `service` 依赖已验证的 namespace、绑定 PVC 和不可变镜像，保持单副本 Deployment、
  Dashboard Service/Ingress、健康探针及非 root/read-only-rootfs 安全上下文。镜像变更只
  更新服务工作负载，使用 PostgreSQL Service/Secret，不挂载数据库 PVC。
- `schedule` 依赖 service/PVC 就绪和目标 k3s containerd 中已证明 digest 的 frozen image，
  只渲染或部署 `scheduled-refresh` 的 suspended/disabled 状态。它复用 service 的镜像、
  PVC、时区、环境和安全边界，不因布尔值直接激活生产采集。

每个组件先执行 typed values、资源集合和依赖预检，再写入并读取 server-observed postcondition；
失败输出区分 prerequisite/component，并给出唯一重试组件。组件操作仍由单个 Helm release
管理资源，避免对同一 Deployment、Service、Ingress、CronJob 或 PVC 产生多套 ownership。
`database` 不构建或传输镜像，`service`/`all` 复用不可变镜像构建、烟测、校验和、SCP 与
containerd import，`schedule` 只接受已审核的 frozen image。任何 active schedule 都必须
通过专用调度入口（`--release-suspended` / `--activate-schedule`）或受审 `--disable-schedule` rollback 流程；组件参数本身不是调度授权。

调度发布将调用者提供的原始 Kubernetes 版本传入 packet validator，使用严格 SemVer 并按 prerelease precedence 比较；非法值或低于 stable 1.27.0 的 native prerelease 在 kubectl/target access 前失败。激活前从 active packet 的 schedule、timezone 与 `startingDeadlineSeconds` 计算 previous/next trigger：`next-schedule` 必须越过 missed-run deadline 且距离下一触发至少 300 秒，`immediate-catch-up` 只允许在上一触发的 deadline window。该 activation window 在 preflight 检查一次，并在 live/image/diff/re-render/hash 检查后、Helm write 前重新检查；第二次失败不执行写入或补偿。通过后才建立 release-derived exact CronJob fail-safe guard；Helm 或任何写后读取、比较、最终查询、HUP/INT/TERM 失败都先补偿 `suspend=true`，全部 postcondition 通过后才解除 guard。

`--disable-schedule` 使用 rollback-only 的 `rollback-v1:<approval-id>:<binding-sha256>` 授权引用；digest 对 versioned canonical payload 中的 exact operation、release、namespace、Kubernetes version、reviewed HEAD 与 chart/baseline/overlay/render hashes 做 SHA-256，入口在 SSH、目标 API 访问或 release mutation 前重算比较。布尔开关只表达 intent，不构成授权证据。active-to-off 从 Helm write 前持有 release-derived exact-name fail-safe；应急检查不依赖可漂移 label 或完整业务 shape，任何 existing resource 只有在 `spec.suspend` 为 typed boolean `true` 时才算安全，否则精确 patch 并按同名读回证明 absent/suspended，无法读取、补偿或证明时保持 uncertain/NO-GO。普通 deploy 在首次 Helm render/build/image work/SSH/target API access 前以及冻结 packet 首次 render 前都深合并并校验 typed `enabled=false,suspend=true`。

部署文档的可执行命令属于发布边界。CommonMark/Bash AST 审计对 brace/glob、`eval`、stdin-fed `bash`/`sh`/`dash`/`zsh`、`source`/`.`、`alias`/`hash -p` 命令解析变更、动态 executable/action 与未知 Helm plugin/action 全部 fail closed；解析不确定不能视为只读。

`.github/workflows/trading-rules-after-market.yml` 是独立的交易规则证据流水线：它在 GitHub runner 创建临时 snapshot/evidence Artifact，不挂载部署 PVC，也不向市场环境 PostgreSQL 写入数据。它不能替代部署内 CronJob，两者的产物和运维边界必须保持区分。

服务层默认请求 280 个交易日，先按 `as_of` 截断到最近交易日，再计算 MA5/10/20/60、20/60 日高低价区间位置、成交额比值、趋势状态、量价状态、MA20 斜率 250 日滚动分位和量价推进效率 250 日滚动分位；60–249 个有效观测降置信，少于 60 个输出 `insufficient-history`。五指数同步性按同步上涨、普遍走弱、权重护盘、成长占优、分化未定型五态输出，深证成指只参与同步多数。五态是仅由指数涨跌得出的观察事实，服务层另以市场广度、指数相对 MA20 的多数位置和指数成交额形成 `synchronizationAssessment`，分别输出确认、反驳、中性或不足证据，再映射为市场层确认状态与稳定结论码；确认结果不得反写五态。系统性下降必须同时具备弱广度、至少三个指数位于 MA20 下方和至少三个指数放量下跌，权重护盘和成长占优也必须通过各自的广度与量能门槛。服务层进一步计算五指数均线多头比例、六类组合、四问结论和盘后收束句；缺失指标附 `insufficient-history`、`missing-today`、`provider-failed` 或 `not-computable`。量价状态与六类组合仍不使用通用兜底。返回给前端的 60 日历史点保留真实 OHLC、成交额和均线；前端仅负责渲染、矩阵聚合与选中行交互，不补算阈值。单指数失败保留其他指数并写入 warning；全部失败返回 503。

核心指数、市场广度、涨跌停生态、行业板块和容量方向统一使用 PostgreSQL 的按交易日持久化快照，记录规范化 payload、来源、抓取时间、样本数、质量、warning、schema version 和 SHA-256。成功快照与 collection attempt 分开存储：失败尝试只记录 `failed-retained` 或 `failed-missing`，不得覆盖同日期成功值，也不得跨日期回填。`core` 内部对五个指数分别记录子项状态，单指数失败允许 core 为 `partial`。SQLite 文件只由停写迁移工具作为只读输入和归档。

PostgreSQL 还保存 collection run/task 和 materialized market-environment aggregate。每个成功 task 提交后，从同日期最新成功数据重建完整响应并经 Pydantic 契约验证后原子替换聚合记录；聚合允许明确的 `partial` / `degraded`。当前日盘中结果标记 provisional，结算后成功结果标记 settled。针对开市前误写日期的修正通过 `date_relabel_audits` 记录的 PostgreSQL 事务执行：迁移前校验 checksum/实际日期并检测目标冲突，事务内同步快照、任务、事实和聚合，保留 before/after image 供回滚；普通采集路径不自动跨日期改名。SQLite lease 仅在一次性导入源中审计，运行时 lease 和 provider limiter 由 PostgreSQL 事务协调。

### 第 03 页 limits 事实与聚合边界

涨跌停生态使用 Alembic 管理的 PostgreSQL additive schema，不删除或改写既有快照、采集任务和旧五字段聚合。一次性 SQLite 导入在切换前执行 `quick_check`、表统计和数据集校验和校验；导入失败不得写入生产数据库。运行时 schema 版本记录在 `alembic_version`，表职责如下：

| 表 | 主键/关键字段 | 约束 |
|---|---|---|
| `trading_sessions` | `as_of`；`previous_as_of`、`actual_as_of`、`is_session`、`source`、`checksum`、`fetched_at`、`warnings_json` | 只保存已证明的真实交易日和精确前一交易日；请求/实际日期不一致时不可用于晋级 |
| `limit_security_datasets` | `as_of`；`actual_as_of`、`source_revision`、`rule_version`、`complete`、`membership_complete`、`streak_complete`、`pool_quality_json`、`dataset_checksum` | 分别保存严格 enrichment、集合和连板字段完整度；重复采集同日期/版本必须幂等 |
| `limit_security_facts` | `(as_of, security_id, pool_type)`；身份、ST/新股/上市、价格、连板、事件字段、来源、行级质量、行/数据集 checksum | 规范身份和完整集合可进入基础晋级；高级属性缺失只降低对应分层，不删除基础成员 |

`limit_security_facts` 的事实字段包括 `code`、`exchange`、`name`、`board`、`is_st`、`is_new`、`listing_date`/`listing_days`、`limit_regime`、价格/涨跌幅、涨停时间/原因/封单额、跌停时间、开板次数、换手率、成交额、`closed_limit_up`、`failed_limit_up`、`streak_days`、行级质量和 `actual_as_of`。证券名称不是身份键，provider 也不得推断固定涨跌幅制度。

晋级聚合只读取本地当前日和 `trading_sessions.previous_as_of` 指向的前一真实交易日：昨日 membership-complete 涨停身份集合为分母，与今日 membership-complete 涨停集合的交集为分子。ST、新股、制度和板块不从基础分母删除；两日 manifest 的 `actual_as_of`、`rule_version`、membership 完整度和 checksum 必须匹配聚合绑定，否则 `promotionQuality` 为 `insufficient`/`failed`。普通历史 GET 不调用 provider，不向更早日期回退；分母为 0 时 `promotionRatio` 为 `null`。

显式回填通过交易日历采集最近 6 个真实交易日并形成最近 5 个晋级点；缺失日期不替代。250 日分位、风险扩散和规则证据要求至少 60 个有效观测，覆盖不足返回有效数、缺口和 `insufficient`。`QTS-01-03-01` 至 `QTS-01-03-05` 的 ID、权重和 `needs-backtest` 状态不变。

新 detail/V1 写入由 `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED` 控制，默认值为 `0`。关闭时继续提供旧五字段和本地快照读取；开启前须通过迁移、幂等、事务、generation fencing、lease/CAS、provider-free warm GET 和失败保留验证。刷新失败只写 collection attempt，保留同日期最后成功快照并返回 `failed-retained`；无旧值返回 `failed-missing`。回滚先关闭该开关，再恢复应用版本，保留 PVC、旧聚合、事实表、session 和 checksum，不删除或跨日期替代。

limits provider 将 membership、streak 和 enrichment 分层校验：交易日、完整分页和规范身份足够形成基础集合；连板数字段决定梯队；ST/上市窗口/制度/板块只决定对应高级分层。真实 provider smoke 只在获授权的盘后窗口使用隔离 PostgreSQL 执行，记录六个交易日、逐池来源、集合差异、checksum 和五个晋级点；密钥仅从环境/Secret 注入，字段不足保持 `failed`、`degraded` 或 `insufficient`，不写生产数据库。

同步性广度变化的读取流为：核心指数历史确定 `as_of` 前一个真实交易日 → `SnapshotStore.get("breadth", previous_trading_date)` 精确日期读取 → 计算上涨占比与涨跌幅中位数变化。精确日期记录不存在时比较维度为 `insufficient`，不得继续向更早日期搜索，也不得在普通 GET 中触发 provider。materialized aggregate 重建复用同一只读路径；后补上一日快照不会自动回填所有后续历史聚合，需要通过既有重建路径显式刷新。

规则平台运行流分为两个阶段：provider 获取数据并创建规范化 snapshot；执行器加载指定规则集和 snapshot，输出确定性 trace 与聚合结果。相同 snapshot、规则版本和 Git 版本必须产生相同 canonical result。完整证据通过 manifest 关联输入哈希、规则版本、Git SHA、provider 降级和结果哈希。

## 归属边界

### PostgreSQL 运行时边界（2026-09 migration）

旧版 SQLite/PVC 文字仅代表迁移前历史，不再描述当前运行时。Dashboard Deployment 与 CronJob 通过同一 PostgreSQL ClusterIP Service 和 Secret 连接配置访问共享状态；只有 PostgreSQL StatefulSet 挂载 Retain RWO PVC。应用工作负载不挂载 SQLite 或 PostgreSQL PVC，`MARKET_ENVIRONMENT_SNAPSHOT_PATH` 仅允许一次性导入工具使用。迁移 Job 按 `postgresql -> schema migration -> service -> schedule` 顺序执行；首次 PostgreSQL 写入后不回切过期 SQLite。

前端仅消费固定 JSON 契约，不直接访问行情源。计算逻辑集中在 `calculations.py`，数据源差异封装在 `providers.py`，持久化快照、collection 状态与 lease 由 snapshot store 模块负责，采集编排和聚合重建由 collection coordinator 负责，CLI、CronJob 与 HTTP 共用该边界，HTTP 错误映射在 `api.py`。手工采集通过 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 默认开启，可设置为 `0` 显式关闭。TrueNAS NodePort 是已接受的匿名写入口而非授权机制；CORS、前端按钮、lease 与 provider 串行化均不能阻止可路由客户端依次发起有效请求。出现异常调用、provider 压力、PostgreSQL 锁等待或数据库 PVC 增长时，先关闭手工写入并按现场捕获的 release/network baseline 处置；首次 PostgreSQL 写入后不得回切过期 SQLite。内部 CronJob 直接执行 CLI，不依赖该 HTTP 写开关；其调度回滚优先使用 reviewed suspend/off overlay，且不得修改 Deployment、PVC 或手工写入设置。

## 已知约束（已定，不可绕过）

- 运行时以 Python 优先（数据 / 分析栈）。
- Windows / macOS / Linux 均为一等公民：脚本禁止绑定单一平台路径与命令（禁 `/tmp`、`grep -P`、`source` 等单平台依赖进默认路径）。
- `docs/` 是事实源；本文件描述系统边界、数据流、分层与不变量。

## 关键不变量

- 本地 gate（`.githooks` + `scripts/check-docs-contract.py`）必须始终可运行。
- 架构边界变更时必须先更新本文档再动代码（AGENTS.md 硬规则 5）。

## 分层地图

```text
apps/market-environment-dashboard/  Vue 3 + Vite + TypeScript + ECharts
src/market_environment/             FastAPI、provider、计算、PostgreSQL 快照、迁移 CLI 与响应模型
deploy/k3s/                          k3s Kustomize、Traefik Ingress、持久卷与工作负载配置
deploy/helm/a-stock/                 等价的可参数化 Helm Chart
trading-rules/                       机器规则、schema 与覆盖清单
src/trading_system/                  快照、规则执行、证据、回测与 CLI
evidence/                            可入库验证索引和月度哈希摘要
tests/                              公式、服务层和 API 契约测试
```

市场环境 API 保留原有 `indices` / `summary` 契约，并以可选 `chapter01` 对象追加证据。核心接口返回不访问章节外部 provider 的 `chapter01` 骨架，章节接口返回截至当前请求已加载的数据集与后端计算的覆盖率、组合概览和评估；前端只合并后端响应，不补算证据。任何 provider 缺失均使用 `null`、`partial`、`missing` 或 `insufficient` 表达；只有上游明确返回空池时才可将对应计数记为 0，分母为 0 的比率仍为 `null`。规则平台继续通过独立 snapshot 契约执行确定性评分。

前端日期时间由 `apps/market-environment-dashboard/src/timezone.ts` 统一格式化：个人偏好优先于工作区偏好，再回退浏览器 IANA 时区，解析失败显式回退 `UTC`。所有 ISO8601 时间展示本地日期时间与 UTC 偏移，tooltip 保留规范化原始 UTC ISO；空值、无效值和无时区输入保持 `--`，不改写 API 原始字段。数据采集页的“最近尝试”属于市场运行审计字段，固定按 `Asia/Shanghai` 显示（不受浏览器/个人时区影响），以免 UTC 浏览器环境造成盘后时间误读。偏好接口采用可替换的 `GET/PUT /api/preferences/timezone` 契约；接口尚未接入或离线时个人偏好安全保存在浏览器本机，工作区偏好仍要求服务端权限。

## 架构相关文档映射规则

| 变更类型 | 必须更新 |
|----------|----------|
| 新增 / 变更系统边界、数据流 | 本文档 |
| 新增外部数据源或第三方集成 | 本文档 + `docs/runbooks.md` |
| 变更本地 gate 行为 | `AGENTS.md` + `docs/runbooks.md` |

## 看板图表生命周期

第 01 章的 ECharts 容器位于章节证据加载态的条件渲染区域内。章节加载开始时必须释放旧的 ECharts 实例，避免实例继续引用已卸载的 DOM；章节加载结束并完成下一轮 DOM 更新后，再重新初始化价格和成交额图表。切换指数或窗口尺寸时复用当前 DOM 对应的实例并执行 `setOption` / `resize`。

## 前端路由与状态层（2026-09-16）

市场环境看板前端从单一 `App.vue` 路由壳演进为 `vue-router` history mode + `pinia` 状态层。前端**不**接入 SSR、不**修改**后端端点；后端契约（`/core` / `/chapter-01?section=` / `/next-session` / `/preferences/timezone`）保持不变。

### 路由边界

- `router/routes.ts` 声明 5 条路由：
  - `/` → 重定向到 `/dashboard/01`
  - `/dashboard/:documentId(0[1-9])` → `DashboardPlaceholder.vue`（Phase 1 临时占位；Phase 2 task 2.6 替换为 `DashboardLayout.vue`，Phase 3/4 在 `frontend-component-split` change 内拆为各 `DocumentXXPage.vue` 嵌套 children）
  - `/data-collection` → `data-collection-view.vue`
  - `/settings` → `timezone-settings-view.vue`
  - `/:pathMatch(.*)*` → catch-all 重定向到 `/dashboard/01`
- `router/legacy-redirect.ts` 在 `beforeEach` 内一次性把 `#document-N`（N=01–09）重写为 `/dashboard/N`，旧书签可点；非文档 hash 不动。
- `props: route => ({ documentId: route.params.documentId })` 让占位组件拿到 URL 参数；后续 `DashboardLayout` 复用此机制。

### 状态归属

- `stores/market.ts`：核心数据 (`data` / `loading` / `error` / `loadedSections` / `sectionStates` / `nextSessionComparison`)、3 个 action（`loadCore` / `loadSection` / `loadNextSession`）、2 个 setter（`setDate` / `setSelectedCode`）、`selectedDate` / `selectedCode` 作为受控输入。请求序列（`coreSequence` / `sectionEpoch` / `sectionSequences` / `nextSessionSequence`）与 `initialDatePending` 是 store 闭包变量，不暴露给 UI。
- `stores/preferences.ts`：时区偏好（`personalTimeZone` / `workspaceTimeZone` / `effectiveTimeZone` / `source` / `warning` / `loading` / `saving` / `canManageWorkspaceTimeZone` / `backendAvailable`）、`load()` / `save(scope, value)` action、localStorage 读写。`formatDateTime` / `parseTimestamp` 等纯函数迁入 `composables/useFormatDateTime.ts`，接收显式 `timeZone` 参数，不读 store。
- `stores/navigation.ts`：UI 路由附属状态（`sidebarOpen` + `openSidebar` / `closeSidebar` / `toggleSidebar`）。
- `market` store 不调其他 store；`preferences` / `navigation` 不调其他 store；时间显示由调用方显式读 `usePreferencesStore().effectiveTimeZone` 后传入纯函数。

### `App.vue` 职责

- 路由壳：`<RouterView/>` 接管 dashboard / data-collection / settings 三层；侧栏与顶栏仍是 `App.vue` 模板（`Sidebar.vue` / `Topbar.vue` 在 `frontend-component-split` change 内拆出）。
- `useRoute()` / `useRouter()` 替换原 `currentView` / `window.history.pushState` / `popstate` 手写路由；`documentFromPath(route.path)` 派生 `selectedDocumentId` 让章节内联模板按 URL URL 渲染。
- `onMounted` 调 `market.loadCore()` 取代原 `loadData()`；`watch(selectedIndex)` / `watch(selectedDocumentId)` 等 ECharts 副作用保留到 `frontend-component-split` 内的 `useChartLifecycle` composable 抽出。
- `initializeTimezonePreferences()` 仍由 `App.vue` 触发（保留在路由壳）。

### 测试边界

- `app.test.ts` / `breadth-page.test.ts` / `limits-page.test.ts` 在 `setActivePinia(createPinia())` + `createMemoryHistory` + `router.push('/dashboard/0X')` + `mount(App, { global: { plugins: [router] } })` 模式下跑通；Phase 1 加入 3 条路由断言（`/dashboard/01` 直达、`/dashboard/99` 重定向、`#document-03` 重写）。
- `stores/market.test.ts`（9 tests）覆盖 `loadCore` 数据填充与初始日期归一、503 错误、并发请求序列、`loadSection` 跳过已加载与合并、`setDate` / `setSelectedCode` / `reset`。
- `stores/preferences.test.ts`（10 tests）覆盖 `load` 200/404/503、`save` 200/401/403/404、`isSupportedTimeZone` / `resolveEffectiveTimeZone` 纯函数。

### 部署侧注意点

- vue-router history mode 在生产部署需要 SPA fallback：开发由 Vite 自动处理；生产 Ingress / NodePort 必须在 404 时回退 `index.html`。详见 `docs/runbooks.md`（后续 Phase 4 增补）。

### 当前不在范围内的范围

- `App.vue` 内联的 9 章节模板仍内联（由 `selectedDocumentId` 切换）；`market` store 未挂载到 `App.vue` 的 ref（仍是设计稿）。完整迁移与组件拆分推迟到 `frontend-component-split` change（2026-09-16-frontend-component-split）：Phase A 抽 composable、Phase B 按章节顺序拆 `Document01`..`Document09`、Phase C App.vue 收尾 + 嵌套路由升级、Phase D 文档同步 + archive。
- 后端 `/api/market-environment` 全量端点（不在当前调用链上）保留为兼容接口。
- 历史模式 SPA fallback 的 Ingress / NodePort 具体配置在 Phase 4 增补（不在本次交付范围）。

### Phase A 基础设施（2026-09-16，frontend-component-split）

`frontend-component-split` Phase A 已落地以下 composables 与未挂载组件。它们**尚未接入 `App.vue` 或路由**——Phase B / C 才替换 App.vue 的内联对应部分。

- `composables/useChartLifecycle.ts`：单个 echarts 实例的生命周期管理（`onMounted` init + setOption，`watch` 重画，`window.addEventListener('resize')` resize，`onBeforeUnmount` dispose）。不持有全局闭包变量；调用方按 `<script setup>` 内 `const lc = useChartLifecycle(el, () => optionFactory())` 形式获取 `{ resize, dispose }`。Phase B 的 `IndexPriceChartPanel.vue` / `VolumeChartPanel.vue` / `BreadthHistoryChartPanel.vue` 直接消费此 composable。
- `composables/useFormatDateTime.ts`：纯日期/时区工具（`formatDateTime`、`parseTimestamp`、`isSupportedTimeZone`、`formatDateTimeTitle`、`formatLocalDate`、`getDefaultMarketDate`）。调用方**必须显式传 `timeZone` 选项**——不再隐式从 module-scope reactive 读取。
- `composables/useDocumentContext.ts`：章节公共派生与 label 字典的只读聚合（breadth 5 行规则 + 一致性 + 验证 + warnings；limits history/stratifications/warnings/promotionGap；qualityLabel / reasonLabel / environmentLabel / gapLabel / formatRatioDelta 等）。`useMarketStore()` 仅在 setup 顶层调用一次，暴露的全部是 `ComputedRef` 与纯函数——章节组件不能借它写 `market`。
- `components/Sidebar.vue`：从 `App.vue` 模板 `<aside class="sidebar">` 整块迁出。`useRoute()` 派生激活态，`router.push` 切换路径，`useNavigationStore` 控制抽屉开关。
- `components/Topbar.vue`：从 `App.vue` 模板 `<header class="topbar">` 整块迁出。日期选择器 `@change` 改用 `market.setDate(market.selectedDate)`；面包屑用 `useRoute()` 派生。
- `pages/dashboard/DashboardLayout.vue`：`/dashboard/:documentId` 嵌套路由的共享壳（document header + evidence strip + breadcrumb + `<RouterView/>`）。`onMounted` 调 `market.loadCore()`（若 `market.data` 为 null）。从 `preferences.effectiveTimeZone` 读取时区给 `evidence-strip` 的 generatedAt 显示。Phase C 才接入路由——目前 `/dashboard/:documentId(0[1-9])` 仍指向 `DashboardPlaceholder.vue`。

测试边界：12 文件 / 86 tests / 全绿。其中 18 个新测试（`useChartLifecycle` 4 个 + `useDocumentContext` 10 个 + 其他已被新 composable 间接覆盖的边界）。

### Phase B-01 / B-02 章节组件（2026-09-16，frontend-component-split）

按章节逐个拆分的前两章已落地为独立页面组件。它们**尚未接入路由**（`/dashboard/:documentId` 仍渲染 `DashboardPlaceholder`，App.vue 内联模板未删除）；现有测试已改为直接挂载页面组件。

- `pages/dashboard/Document01IndexPricePage.vue`：第 01 章全部 7 个 section（指数卡 / 价格结构 + 趋势量能 / 同步评估 / 复盘句 / 次日对照 / 组合矩阵 / 五大指数指标表）。只读 `useMarketStore()` + `useDocumentContext()`；写操作（选指数、复制、刷新）通过 emit 上抛。图表区域预留 `<slot name="price-chart" />` / `<slot name="volume-chart" />`，由路由壳在 Phase C 填入 chart panel。
- `pages/dashboard/Document01IndexPricePage.test.ts`：6 tests，独立 `mount` + pinia 预填 market fixture；覆盖指数卡、workspace grid、同步评估、组合矩阵、null 数据兜底、`selectIndex` emit。
- `pages/dashboard/Document02BreadthPage.vue`：第 02 章全部 5 个 section（盘后复盘卡 / 量化证据 / 近 5 日宽度趋势 / 指数×广度一致性 / 次交易日验证 + 质量元数据）。直接内嵌 `BreadthHistoryChartPanel`；`copyVerification` 通过 emit 上抛。
- `components/charts/IndexPriceChartPanel.vue` / `VolumeChartPanel.vue` / `BreadthHistoryChartPanel.vue`：三个 chart panel，全部通过 `useChartLifecycle` 持有各自 ECharts 实例；接收 `history` / `dates` / `points` props，watch 数据变化重画。
- `breadth-page.test.ts` 改造：从 `mount(App)` + hash 跳转改为 `mount(Document02BreadthPage)` + `setActivePinia` + `market.loadCore()` 预填；原 7 条断言保留，390px 溢出断言从 `.content-shell`（App 壳层节点）改为页面根元素。

测试边界：13 文件 / 92 tests / 全绿（86 基线 + 6 个 Document01 新测试；breadth-page 7 条断言随组件化迁移，总数不变）。

### Phase B-03 章节组件（2026-09-16，frontend-component-split）

- `pages/dashboard/Document03LimitsPage.vue`：在既有质量、指标、晋级、梯队/分层、历史和规则区块后增加股票明细折叠区；四组明细使用分段切换、关键词搜索、20 行本地分页和表内横向滚动，行级来源/质量/warning 可见。刷新按钮仍通过 `refreshSection` emit 上抛。
- `limits-page.test.ts` 改造：从 `mount(App)` 改为 `mount(Document03LimitsPage)`；预填走 `market.loadCore()` + `market.loadSection('limits')`（03 章数据来自 `chapter-01?section=limits`，与 01/02 的 core 直出不同）；刷新按钮的写操作在 mount 时通过 `onRefreshSection` prop 接线回 `market.loadSection('limits', true)`，验证了 emit 边界。

测试边界：13 文件 / 92 tests / 全绿（B-03 不新增测试文件；limits-page 4 条断言随组件化迁移，总数不变）。

### Phase B-04 章节组件（2026-09-16，frontend-component-split）

- `pages/dashboard/Document04TierRiskPage.vue`：第 04 章读取已预拉的 `chapter01.limits`，高/中/低位来自 `stratifications[dimension=risk_tier]`，修复率来自 `riskEvidence[code=failure-repair]`；四项分别沿用自身 quality，缺失单项显示 `--`，不依赖不存在的 `chapter01.tierRisk`。
- `Document04TierRiskPage.test.ts`：覆盖真实 limits 映射、单项缺失、质量 warning 和 section 加载状态。

测试边界：14 文件 / 95 tests / 全绿（92 基线 + 3 个 Document04 新测试）。

### Phase B-05 ~ B-09 章节组件（2026-09-16，frontend-component-split）

剩余五个章节全部拆为独立页面组件，形态与 B-04 一致（core 直出、只读 store 与 composable、无 section 预拉）：

- `Document05SectorsPage.vue`：行业轮动表（板块 / 涨跌幅 / 上涨下跌 / 主力净额 / 领涨股）+ 空态 fallback。3 tests。
- `Document06ActiveDirectionPage.vue`：容量资金 Top 表（个股 / 涨跌幅 / 成交额 / 方向 / 收盘位置）+ summary 与空态。2 tests。
- `Document07EventsPage.vue`：事件台账（来源 / 时间 / 已核实徽章）+ 调整边界面板。事件时间用纯 `formatDateTime` 显式传 `preferences.effectiveTimeZone`。2 tests。
- `Document08EnvironmentClassifyPage.vue`：当前环境标签（environmentLabel）+ 证据一致性列表。3 tests。
- `Document09AssessmentPage.vue`：唯一结论（分数 / 置信度 / 覆盖率）+ 证据链 + 风险否决 + 次日确认 + NextSessionPanel(mode="summary")。meta.section 为 null，不触发预拉。3 tests。

测试边界：19 文件 / 108 tests / 全绿（95 基线 + 13 个新测试）。Phase B 全部 9 章节组件就绪，Phase C 进入 App.vue 收尾与嵌套路由接入。

### Phase C — App.vue 收尾与嵌套路由（2026-09-16，frontend-component-split）

- **App.vue**：从 ~1020 行缩至 ~48 行的纯壳（app-shell + `<Sidebar/>` + `<Topbar/>` + `<RouterView/>` + 时区偏好初始化）。不再持有任何 dashboard 状态、fetch 逻辑、ECharts 实例、章节模板或派生 computed。
- **嵌套路由**（`router/routes.ts`）：`/dashboard` 父级挂 `DashboardLayout`；9 个 children `01`..`09` 各自声明 `meta.section`（01→summary、02→breadth、03→limits、04→limits、05→sectors、06→activeDirection、07→null、08→summary、09→null）与 `meta.documentId`。`/dashboard` 空路径重定向到 `/dashboard/01`；catch-all 保持重定向。
- **守卫**（`router/guards.ts`）：单一 `registerRouterGuards(router)` 工厂——(1) legacy `#document-N` hash 一次性重写；(2) 进入 `/dashboard/*` 且 store 无数据时 `await market.loadCore()`（阻塞）；(3) 目标章节 `meta.section` 非空且未加载时 `void market.loadSection(section)`（不阻塞）。生产 `index.ts` 与测试共用同一工厂。
- **DashboardLayout**：document header（按路由派生 documentId 与章节元数据）+ evidence strip（时区经 `preferences.effectiveTimeZone` 显式传入纯 `formatDateTime`）+ section 级 loading/error 面板（由 `meta.section` 与 `market.loadedSections` 联合派生）+ `<RouterView>` + 两条 warning band（本节证据边界 / 数据质量提醒）。章节组件的 `selectIndex` / `refreshSection` emit 在 `<RouterView>` 的 slot props 上统一接线到 `market.setSelectedCode` / `market.loadSection(section, true)`。`onMounted` 有 `!market.data` 兜底 loadCore（直接挂载测试路径）。
- **Document01**：图表从 slot 改为内嵌 `IndexPriceChartPanel` / `VolumeChartPanel`；剪贴板（指数值 / 涨跌幅 / 复盘句）判定为纯 UI 行为收编进组件，不再 emit；唯一保留的 store 写是 `selectIndex` emit。`app.test.ts` 的 chart lifecycle 测试重写为「路由切换 dispose/init」契约（01→02→01，init 2→3→5、dispose 0→2→3），替代旧的"section loading 替换 DOM"时序断言。
- **Document02**：验证项复制同样收编为组件内剪贴板行为。
- **删除**：`components/DashboardPlaceholder.vue`（无引用）。`App.vue` 的手写路由、`currentView`、`popstate`、`pushState`、hash 解析、9 章节内联模板、3 个 ECharts 闭包变量与 5 个图表函数全部移除。

验证：19 文件 / 108 tests / 全绿；`npm run build` 通过（单 chunk 警告为 echarts 全量打包，非回归）；`python scripts/check-docs-contract.py --mode=full` 通过。
- 扶摇市场数据迁移采用独立通用请求层 `src/market_environment/fuyao_market.py`，与已稳定的 limits 专用 `FuyaoClient` 并行存在。`core`、`breadth`、`sectors`、`activeDirection` 通过能力报告、批准 revision 和逐数据集开关控制，默认关闭。
- shadow 对账结果只进入采集任务 `timings` 元数据，不覆盖正式快照、source 或 checksum；能力报告保存在 `provider_capability_reports`，SQLite/ PostgreSQL 均为加法 schema。
