# 架构

> 状态：**已落地第 01 章市场环境看板与交易规则工程平台首期**。产品范围见 `docs/product-specs/market-environment-dashboard.md` 与 `docs/product-specs/trading-rule-engineering.md`；看板视觉与交互约束见 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。

## 系统角色

市场环境看板面向盘后研究，前端用于选择交易日、比较指数和查看解释；后端负责行情获取、指标计算、数据质量标记和降级。

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

市场环境 API 通过可选的 `chapter01` 对象扩展第 01 章证据。市场广度直接使用东方财富 `push2delay` 的涨跌幅排序分页，定位正负边界和有效样本中位数，不再先尝试被上游限制为不完整行数的名义全 A 主快照；容量方向独立请求按成交额排序的 Top-N 股票，只保留形成成交额前 30 聚集和前 10 展示所需字段，不要求下载全部 A 股。东方财富日期化涨停、跌停和炸板池用于打板生态；行业板块排名用于当日方向线索。当前快照型 provider 只允许为上海时区当前市场日期采集，但已在盘后按交易日持久化的精确快照可以用于对应历史日期，禁止拿其他日期或今日数据回填。暂未接入的高/中/低位亏钱效应和事件输入保持 `null` / `insufficient`，并附 provider quality 和 warning。

看板交易日输入按浏览器本地时区生成，API 默认日期和“当前快照”判断统一使用 `Asia/Shanghai`，避免浏览器 UTC 转换或服务端部署时区把“今天”错位为前一日。东方财富全 A 快照解析同时接受数组和键值对象形式的 `data.diff`，仅保留有效对象行，并校验实际行数覆盖 `data.total` 后才允许按完整快照计算。

网页使用固定一级导航 `如何判断市场环境`，下设 01 至 09 文档视图。每个视图只解释 API 已返回的证据与质量状态；前端不补算缺失指标，不把未验证阈值渲染为确定性评分。所有可见界面文字和图表标签以 `14px` 为最小字号，标题与关键数字在此基础上维持层级。移动端将同一导航收纳为抽屉，宽表保留横向滚动，并通过增加行高与容器空间承载放大后的文字。

规则平台扩展数据包括全市场宽度、涨跌停/炸板池、板块与成交集中度、流动性和事件输入。行情优先 mootdx/腾讯，百度/新浪/东方财富作为明确降级；东方财富请求必须经共享串行 limiter，间隔至少 1 秒并加入抖动，403 不盲目重试。公告、政策和突发事件必须保存来源与有效期；无法观测的主体意图不进入自动评分。

指数代码始终使用 `sh000001`、`sz399001` 等显式前缀。对百度/mootdx 存在沪市代码歧义的指数，必须有腾讯价格交叉校验，否则拒绝该源，避免股票数据静默冒充指数。

## 运行时流

浏览器 → Vite `/api` 代理 → FastAPI `src/market_environment/api.py` → `MarketEnvironmentService` → SQLite snapshot store → 必要时 provider 适配层 → 行情源。网页首屏调用 `/api/market-environment/core`，只等待五大指数和基于指数即可生成的基础章节骨架；进入需要扩展证据的二级文档时，再调用 `/api/market-environment/chapter-01` 并按 `section` 加载市场广度、涨跌停生态、行业或容量方向。第 08、09 页请求综合章节数据。原 `/api/market-environment` 继续返回完整聚合响应，作为兼容接口而非网页首屏依赖。正常盘后路径先通过显式 refresh CLI 采集并预计算章节快照，API 请求优先读取本地结果。

生产部署使用单镜像边界：Node 构建阶段生成 `apps/market-environment-dashboard/dist`，Python 运行阶段由 FastAPI 同时托管静态网页与 `/api`。原生 k3s Kustomize 资源位于 `deploy/k3s/`，等价 Helm Chart 位于 `deploy/helm/a-stock/`；两条路径均为 Traefik Ingress → ClusterIP Service → 单副本 Deployment，并使用持久卷保存 SQLite 快照。当前缓存、SQLite lease 和 provider 限流均按单机边界设计，因此默认保持一个 Uvicorn 进程和一个 Pod；扩展为多副本前必须先引入支持多节点共享与协调的存储方案。Pod 需要访问通达信 TCP 及外部 HTTPS 行情源，健康探针只访问不触发外部 provider 的 `/api/health`。

服务层至少请求 120 个交易日，先按 `as_of` 截断到最近交易日，再计算 MA5/10/20/60、20/60 日高低价区间位置、成交额比值、趋势状态和量价状态。量价状态只在明确命中价格变化与 5 日成交额比值规则时返回；“量价平稳”限定为日涨跌幅绝对值小于 `0.5%` 且比值位于 `[1.0, 1.2)`，其他阈值空档返回 `null`，禁止通用兜底分类。服务层进一步按量化版 `0.2` 的风险优先映射计算每个指数的六类位置量价组合、触发证据和交易模式，并结合五大指数同步性与可用市场广度生成市场强弱、阶段、资金认可和交易模式四项汇总；前端只消费这些结果，不重复计算阈值。返回给前端的 60 日历史点保留真实 `open`、`high`、`low`、`close`、成交额和均线；前端仅负责将 OHLC 渲染为 K 线，不合成或补算行情。单指数失败保留其他指数并写入 warning；全部失败返回 503。

指数核心结果继续使用独立进程内短缓存。市场广度和容量方向使用 `.artifacts/market-environment/snapshots.sqlite3` 的按交易日持久化快照，路径可由环境变量配置；记录规范化 payload、来源、抓取时间、样本数、质量、warning、schema version 和 SHA-256。当前日未结算数据使用数据集级 soft TTL；结算时间后由 refresh CLI 确认的成功快照标记为 settled 并持续复用。fresh 命中不访问 provider；stale 命中立即返回上次成功值并通过 `(dataset, as_of)` SQLite lease 合并刷新；冷 miss 保留一次同步 single-flight 兼容路径。刷新失败不得覆盖上次成功 payload，API 通过可选 `cacheState`、`snapshotFetchedAt`、`refreshing`、`refreshWarning` 暴露缓存状态。SQLite 仅作为单机本地文件系统方案，多主机共享缓存不在当前边界内。

规则平台运行流分为两个阶段：provider 获取数据并创建规范化 snapshot；执行器加载指定规则集和 snapshot，输出确定性 trace 与聚合结果。相同 snapshot、规则版本和 Git 版本必须产生相同 canonical result。完整证据通过 manifest 关联输入哈希、规则版本、Git SHA、provider 降级和结果哈希。

## 归属边界

前端仅消费固定 JSON 契约，不直接访问行情源。计算逻辑集中在 `calculations.py`，数据源差异封装在 `providers.py`，持久化快照与 lease 由 snapshot store 模块负责，盘后预计算由 refresh coordinator 与 CLI 负责，HTTP 错误映射在 `api.py`。持久化缓存可通过环境配置关闭并回退到直接 provider 路径。

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
