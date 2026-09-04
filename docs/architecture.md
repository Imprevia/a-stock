# 架构

> 状态：**已落地第 01 章市场环境看板与交易规则工程平台首期**。产品范围见 `docs/product-specs/market-environment-dashboard.md` 与 `docs/product-specs/trading-rule-engineering.md`；看板视觉与交互约束见 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。

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

市场环境 API 通过可选的 `chapter01` 对象扩展第 01 章证据。市场广度直接使用东方财富 `push2delay` 的涨跌幅排序分页，定位正负边界和有效样本中位数，不再先尝试被上游限制为不完整行数的名义全 A 主快照；容量方向按成交额排序请求 Top-N 股票，`push2` 主域恢复失败后降级到同口径 `push2delay`，两个来源统一校验代码、名称、成交额、至少 30 个有效样本和成交额非递增排序，只保留形成前 30 聚集和前 10 展示所需字段。延迟域成功时质量来源为 `eastmoney-clist-delay`、状态为 `fallback`，并保留主域错误。东方财富日期化涨停、跌停和炸板池用于打板生态；行业板块排名同样先请求 `push2` 主域，主域恢复失败后降级到同口径 `push2delay`，并在质量元数据中保留 fallback 来源和主域错误。行业领涨股名称取 provider 的 `f128`，`f140` 仅为证券代码且不得显示为名称。当前快照型 provider 只允许为上海时区当前市场日期采集，但已在盘后按交易日持久化的精确快照可以用于对应历史日期，禁止拿其他日期或今日数据回填。暂未接入的高/中/低位亏钱效应和事件输入保持 `null` / `insufficient`，并附 provider quality 和 warning。

研究看板交易日输入按浏览器本地时区生成：本地时间 15:00 前默认选择前一天，达到 15:00 后默认选择当天；用户仍可在日期控件中手动选择不晚于当天的日期。数据采集页不复用该截止逻辑，首次状态请求省略 `as_of` 并使用后端返回的上海市场当天，用户手工切换后才发送显式日期。API 默认日期和“当前快照”判断统一使用 `Asia/Shanghai`，避免浏览器 UTC 转换或服务端部署时区把“今天”错位为前一日。东方财富全 A 快照解析同时接受数组和键值对象形式的 `data.diff`，仅保留有效对象行，并校验实际行数覆盖 `data.total` 后才允许按完整快照计算。

网页使用固定一级导航 `如何判断市场环境`，下设 01 至 09 文档视图；侧边栏另设“数据管理”入口 `/data-collection`，不改变交易知识文档层级。研究视图只解释 API 已返回的证据与质量状态，数据采集页只读取本地任务和快照状态并提供受控写操作；前端不补算缺失指标，不把未验证阈值渲染为确定性评分。所有可见界面文字和图表标签以 `14px` 为最小字号，标题与关键数字在此基础上维持层级。移动端将导航收纳为抽屉，宽表或采集状态行必须在自身容器内适配，页面不得横向溢出。

规则平台扩展数据包括全市场宽度、涨跌停/炸板池、板块与成交集中度、流动性和事件输入。行情优先 mootdx/腾讯，百度/新浪/东方财富作为明确降级；东方财富请求必须经单进程共享请求门串行执行，锁覆盖限流等待和完整 HTTP 请求，间隔至少 1 秒并加入抖动。连接/读取错误、429 和 5xx 使用有界退避重试，403 不盲目重试。公告、政策和突发事件必须保存来源与有效期；无法观测的主体意图不进入自动评分。

指数代码始终使用 `sh000001`、`sz399001` 等显式前缀。对百度/mootdx 存在沪市代码歧义的指数，必须有腾讯价格交叉校验，否则拒绝该源，避免股票数据静默冒充指数。

## 运行时流

普通读取流为：浏览器 → Vite `/api` 代理 → FastAPI `src/market_environment/api.py` → `MarketEnvironmentService` → SQLite materialized aggregate / snapshot store。`/api/market-environment`、`/core` 和 `/chapter-01` 优先读取精确日期本地结果，缺失、陈旧或活动采集不得在普通 GET 中启动外部 provider。

手工采集流为：`/data-collection` → collection run API → 有界进程内 executor → collection coordinator → 五个独立 dataset task → provider 适配层 → 成功快照 → 聚合响应重建。父批次只汇总 `success` / `partial` / `failed`；`core`、`breadth`、`limits`、`sectors` 和 `activeDirection` 各自持有 `(dataset, as_of)` lease，单项失败不停止后续任务，也不覆盖同日期成功快照。不同 task 可以由 executor 调度，但共享东方财富请求门保证供应商调用不并发；CLI 与 HTTP 复用同一 coordinator，不通过 shell 启动子进程。

盘后定时采集流为：k3s/Helm CronJob → `python -m src.market_environment.cli snapshots scheduled-refresh` → collection coordinator → 同一组五类独立 task → 同一 SQLite/PVC。CLI 在 Python 内按 `Asia/Shanghai` 解析日期，周末无 provider 调用并返回 skipped，结算边界前拒绝执行；CronJob 默认工作日 16:30、`concurrencyPolicy: Forbid` 且不对 `partial` 自动整批重试。CronJob 与人工触发并发时仍由 SQLite dataset/date lease 作为最终去重边界。第一版不维护交易所节假日日历，工作日节假日可能留下 failed/partial 记录，但精确日期校验禁止把其他交易日数据写成当天。

生产部署使用单镜像边界：Node 构建阶段生成 `apps/market-environment-dashboard/dist`，Python 运行阶段由 FastAPI 同时托管静态网页与 `/api`。原生 k3s Kustomize 资源位于 `deploy/k3s/`，等价 Helm Chart 位于 `deploy/helm/a-stock/`；两条路径均为 Traefik Ingress → ClusterIP Service → 单副本 Deployment，并使用持久卷保存 SQLite 快照，盘后 CronJob 使用同一不可变镜像和 PVC 执行短生命周期 CLI。当前缓存、SQLite lease 和 provider 限流均按单机边界设计，因此默认保持一个 Uvicorn 进程和一个 Dashboard Pod；扩展为多副本前必须先引入支持多节点共享与协调的存储方案。Dashboard 与 CronJob Pod 都需要访问通达信 TCP 及外部 HTTPS 行情源，健康探针只访问不触发外部 provider 的 `/api/health`。

`.github/workflows/trading-rules-after-market.yml` 是独立的交易规则证据流水线：它在 GitHub runner 创建临时 snapshot/evidence Artifact，不挂载部署 PVC，也不向市场环境 SQLite 写入数据。它不能替代部署内 CronJob，两者的产物和运维边界必须保持区分。

服务层默认请求 280 个交易日，先按 `as_of` 截断到最近交易日，再计算 MA5/10/20/60、20/60 日高低价区间位置、成交额比值、趋势状态、量价状态、MA20 斜率 250 日滚动分位和量价推进效率 250 日滚动分位；60–249 个有效观测降置信，少于 60 个输出 `insufficient-history`。五指数同步性按同步上涨、普遍走弱、权重护盘、成长占优、分化未定型五态输出，深证成指只参与同步多数。五态是仅由指数涨跌得出的观察事实，服务层另以市场广度、指数相对 MA20 的多数位置和指数成交额形成 `synchronizationAssessment`，分别输出确认、反驳、中性或不足证据，再映射为市场层确认状态与稳定结论码；确认结果不得反写五态。系统性下降必须同时具备弱广度、至少三个指数位于 MA20 下方和至少三个指数放量下跌，权重护盘和成长占优也必须通过各自的广度与量能门槛。服务层进一步计算五指数均线多头比例、六类组合、四问结论和盘后收束句；缺失指标附 `insufficient-history`、`missing-today`、`provider-failed` 或 `not-computable`。量价状态与六类组合仍不使用通用兜底。返回给前端的 60 日历史点保留真实 OHLC、成交额和均线；前端仅负责渲染、矩阵聚合与选中行交互，不补算阈值。单指数失败保留其他指数并写入 warning；全部失败返回 503。

核心指数、市场广度、涨跌停生态、行业板块和容量方向统一使用 `.artifacts/market-environment/snapshots.sqlite3` 的按交易日持久化快照，路径可由环境变量配置；记录规范化 payload、来源、抓取时间、样本数、质量、warning、schema version 和 SHA-256。成功快照与 collection attempt 分开存储：失败尝试只记录 `failed-retained` 或 `failed-missing`，不得覆盖同日期成功值，也不得跨日期回填。`core` 内部对五个指数分别记录子项状态，单指数失败允许 core 为 `partial`。

SQLite 还保存 collection run/task 和 materialized market-environment aggregate。每个成功 task 提交后，从同日期最新成功数据重建完整响应并经 Pydantic 契约验证后原子替换聚合记录；聚合允许明确的 `partial` / `degraded`。当前日盘中结果标记 provisional，结算后成功结果标记 settled。SQLite lease 和 provider limiter 仍是单机边界，多主机共享不在当前范围。

同步性广度变化的读取流为：核心指数历史确定 `as_of` 前一个真实交易日 → `SnapshotStore.get("breadth", previous_trading_date)` 精确日期读取 → 计算上涨占比与涨跌幅中位数变化。精确日期记录不存在时比较维度为 `insufficient`，不得继续向更早日期搜索，也不得在普通 GET 中触发 provider。materialized aggregate 重建复用同一只读路径；后补上一日快照不会自动回填所有后续历史聚合，需要通过既有重建路径显式刷新。

规则平台运行流分为两个阶段：provider 获取数据并创建规范化 snapshot；执行器加载指定规则集和 snapshot，输出确定性 trace 与聚合结果。相同 snapshot、规则版本和 Git 版本必须产生相同 canonical result。完整证据通过 manifest 关联输入哈希、规则版本、Git SHA、provider 降级和结果哈希。

## 归属边界

前端仅消费固定 JSON 契约，不直接访问行情源。计算逻辑集中在 `calculations.py`，数据源差异封装在 `providers.py`，持久化快照、collection 状态与 lease 由 snapshot store 模块负责，采集编排和聚合重建由 collection coordinator 负责，CLI、CronJob 与 HTTP 共用该边界，HTTP 错误映射在 `api.py`。手工采集通过 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 默认开启，可设置为 `0` 显式关闭；无认证的外部部署在接入权限边界前必须显式关闭。内部 CronJob 直接执行 CLI，不依赖该 HTTP 写开关。

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
src/market_environment/             FastAPI、provider、计算、SQLite 快照、刷新 CLI 与响应模型
deploy/k3s/                          k3s Kustomize、Traefik Ingress、持久卷与工作负载配置
deploy/helm/a-stock/                 等价的可参数化 Helm Chart
trading-rules/                       机器规则、schema 与覆盖清单
src/trading_system/                  快照、规则执行、证据、回测与 CLI
evidence/                            可入库验证索引和月度哈希摘要
tests/                              公式、服务层和 API 契约测试
```

市场环境 API 保留原有 `indices` / `summary` 契约，并以可选 `chapter01` 对象追加证据。核心接口返回不访问章节外部 provider 的 `chapter01` 骨架，章节接口返回截至当前请求已加载的数据集与后端计算的覆盖率、组合概览和评估；前端只合并后端响应，不补算证据。任何 provider 缺失均使用 `null`、`partial`、`missing` 或 `insufficient` 表达；只有上游明确返回空池时才可将对应计数记为 0，分母为 0 的比率仍为 `null`。规则平台继续通过独立 snapshot 契约执行确定性评分。

## 架构相关文档映射规则

| 变更类型 | 必须更新 |
|----------|----------|
| 新增 / 变更系统边界、数据流 | 本文档 |
| 新增外部数据源或第三方集成 | 本文档 + `docs/runbooks.md` |
| 变更本地 gate 行为 | `AGENTS.md` + `docs/runbooks.md` |
