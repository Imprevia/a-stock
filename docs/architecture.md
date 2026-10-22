# 架构

## 多页市场研判重构边界（2026-09-14）

市场环境 Dashboard 保持 01–09 独立路由和按需章节加载。第 01 页的七项复盘证据与 `ReviewSentence` 在计算层由五项指数和精确市场广度聚合生成；第 09 页仅消费综合摘要。`GET /api/market-environment/next-session` 是 provider-free 只读路径：服务从 `trading_sessions` 解析严格大于 `as_of` 的最小真实交易日，并读取该日核心/广度 materialized aggregate，缺失返回 `pending` 或 `insufficient`，不触发采集、不跨日期回退。新增 schema 为 additive，旧 `summarySentence`、`syncPattern` 和组合矩阵字段继续兼容。看板不保存用户复盘记录、输入或训练进度。

### PostgreSQL 运行时存储边界（2026-09-16）

生产运行时状态统一保存到 Helm/k3s 管理的单主 PostgreSQL StatefulSet。Dashboard Deployment 通过内部 ClusterIP Service 和 `MARKET_ENVIRONMENT_DATABASE_URL` Secret 连接，不挂载数据库 PVC，也不创建或读取共享 SQLite 文件；Hermes 只经内网 HTTP 调用后端，不接触数据库。PostgreSQL 独占自己的 Retain RWO PVC；单主、无复制和自动故障切换是当前明确边界。SQLite 只作为停写迁移的只读输入和归档，不是运行时回退路径。

> 状态：**已落地第 01 章市场环境看板与交易规则工程平台首期**。产品范围见 `docs/product-specs/market-environment-dashboard.md` 与 `docs/product-specs/trading-rule-engineering.md`；看板视觉与交互约束见 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。

### 第 02 页市场广度派生边界（2026-09-16）

第 02 页 "上涨家数、下跌家数和涨跌幅中位数" 在 provider 抓取的全 A 快照基础上，由 `MarketEnvironmentService._enrich_breadth` 在每次章节请求时串接派生指标：涨跌家数差、涨跌差率、4 条 250 日滚动分位（上涨占比 / 涨跌差率 / 中位数 / 5 日动量）、5 日动量、5 个指数与广度同向判定、6 档宽度标签（含自然语言依据）。历史来源固定为 PostgreSQL exact-date breadth snapshot/read repository，与第 01 章 `syncPattern` / `next-session` 共用同一 provider-free 读取路径；不引入新的 provider、PostgreSQL schema 或日常采集任务。所有新字段为可空，分位计算最低需要 60 个有效交易日，分析窗口固定为最近 250 个有效交易日；页面只展示最近 5 个已验证点位，coverage 使用真实唯一观察数除以 250 并限制在 `[0, 1]`，不得把返回条数同时伪装成所需观察数、窗口或满覆盖率。缺失样本数 < 60 时历史分位标注 `insufficient` 且保持 `null`，不补 0，但完整的当日计数、中位数、宽度标签和摘要质量仍可独立展示。

V2 breadth summary 与 breadth history 构成同一 revision-pinned resource group，但具有独立提交点：summary 校验成功后立即进入前端状态；history 的 loading/error/insufficient 单独维护，网络或 5xx 失败不得清空 summary、不得关闭全局 V2，也不得覆盖其他已成功资源。history 返回 409 时必须刷新 overview 并重新读取 summary 与 history 后再提交新 revision，禁止把旧 summary 与新 history 合并。summary 自身的 `snapshot_integrity_error` 继续 fail closed，不得以 legacy 或其他日期证据替代。

历史缺口只能由显式、有界、默认 dry-run 的 `snapshots breadth-history` maintenance command 处理。命令接受明确日期集合或闭区间交易日，单次最多 20 个已确认交易日；`--apply` 还必须同时携带 `--allow-real-provider` 与 `--allow-snapshot-writes`，任一缺失都在 provider 构造和 I/O 前拒绝。获批执行逐日复用 breadth acquisition plan、TDX exact-date/package 与普通 A 股 universe 校验、coordinator、lease/fencing、typed committer、task/run audit 和 materialized aggregate rebuild；不得直接 SQL 写 snapshot。每个日期独立结算，已有同日成功证据不得被不可用、错日或不足包覆盖。真实 provider probe、生产写入、生产回填与部署是互相独立的授权动作，本 change 的代码和离线测试不构成授权。

## 系统角色

市场环境看板面向盘后研究，前端用于选择交易日、比较指数、查看解释和在开发阶段管理数据采集；后端负责行情获取、指标计算、数据质量标记、独立任务协调、快照持久化和降级。

交易规则平台面向盘后研究、规则维护和审计。YAML 注册表是机器执行事实源，量化版 Markdown 是人读解释层；执行器只读取规范化快照，不直接依赖网络 provider。

## AI 市场数据读取边界（2026-10-16）

新增 HTTP namespace `/api/v2/market-environment`，但不新增事实源：HTTP 专用 DTO/mapper → resource query facade → typed local read ports → PostgreSQL repositories/materialized evidence 是唯一读取方向。query facade 不依赖 FastAPI、provider 或具体 persistence；HTTP 层不直接构造 repository；生产列表 adapter 在 SQL 中完成 filter、稳定 order、cursor seek 与 `limit + 1` 后才物化。breadth/limits 等历史查询只从封闭 predicate 集合追加实际存在的 `start_date`、`end_date` 和 cursor 条件，并以显式 date 类型绑定非空值；首页不得包含 cursor predicate，也不得用 `(:value IS NULL OR ...)` 绑定未类型化 `NULL`。后续页绑定完整非空排序键并执行严格大于 seek，保持精确日期升序与 `limit + 1` 分页。仅兼容/测试 adapter 可从有界 fixture 投影，生产不得加载完整 JSON/行集后切片。

精确日期资源包括 overview；indices summary/detail/history；breadth summary/history；limits summary/pool/history/evidence；sector rankings/turnover/breadth/analysis；active-direction、events、assessment；以及按 run id 分离的 operation summary/checkpoints。每项有独立 DTO，共享 envelope 只含 `asOf`、`generatedAt`、opaque `snapshotRevision`、`quality`、`data`、`links` 和集合专用 `pagination`。不得用 `response_model_exclude` 包装完整 `MarketEnvironmentResponse` / `Chapter01Response`，否则 OpenAPI 仍会公开错误结构并可能泄漏兄弟字段。

revision authority 是 exact-date materialization component revision vector；公开值是该 vector 的稳定 opaque digest，不暴露私有 component metadata。overview 返回当前 revision 与同值 ETag；后续资源用 HTTP revision precondition 固定同一版本，冲突返回 409 与当前 revision，`If-None-Match` 命中返回 304。cursor 同样 opaque，签入资源、日期/run id、filters、最后稳定排序键和 revision；解析与一致性校验发生在 repository access 之前，malformed、跨资源、改筛选或 stale revision 均 fail closed。历史按日期，pool 按域顺序再证券 identity，ranking 按 rank/change 再 `thscode`，checkpoint 按 code/window 稳定排序。

普通 v2 GET 与 `/llms.txt`、`/llms-full.txt` 必须 provider-free/read-only：只读本地精确日期证据，不构造 provider client，不 start/join collection，不创建 background task，不写 PostgreSQL，不下载 dump，也不搜索替代日期。未知日期 404；无效/未来日期、closed selector 或 limit 422；已知日期的单数据集缺失仍返回显式 missing/insufficient envelope。discovery renderer 在内存中组合 tagged OpenAPI operations 与受控产品/runbook 语义，以 `/openapi.json` 为结构事实源，不读写生成文件、不查询数据库或行情。

core 的精确日期身份从单指数 history 的最后有效 observation 开始证明：只有 history 尾日等于请求日的结果才是本次成功；更早日期必须成为带 requested/actual date 的 date-mismatch failure，不能通过 candidate `actual_as_of`、quality `asOf` 或 payload 重标。四个同日指数与一个错日指数可形成同日 partial；五项均错日时只有请求日既有合法快照可成为 `failed-retained`，否则为 `failed-missing`。snapshot 与 materialized aggregate 的兼容 facade、typed PostgreSQL repository/CAS 都在 fenced/atomic 写入前复核 key、payload/quality 日期、effective date 与已包含指数 history 尾日；失败不推进 checksum/revision、不覆盖同日合法证据。

普通读取发现本地行存在但 checksum 或 key/payload/effective date 不一致时，v2 与 legacy 统一返回脱敏 HTTP 503、code=`snapshot_integrity_error`；它不同于无本地事实的 404 或单数据集 missing/insufficient。完整性失败仍为 provider-free、零 collection/background task、零 PostgreSQL 写入；dashboard 不把该错误替换成 legacy 或其他日期成功结果。存量坏行只能由显式只读审计识别，任何备份、停写、前向重采/重建或数据处置都需要独立计划和授权，GET 与正常采集不得自动重标、复制、删除或修复。

core 前向修复仍走正常 collector → typed candidate → fenced committer → aggregate rebuild 链，只允许维护 CLI 同时明示 `--force --repair-integrity --dataset core` 后启用一次性 replacement intent。replacement intent 不进入 HTTP、Hermes 或普通采集，只接受五个指数全部 success 且所有 payload/history/quality 日期均与目标日一致的 candidate；它只跳过对已确认坏 existing 的留存读取，随后由 snapshot repository 重新计算 checksum 并原子 upsert。partial、retained、failed 或错日 candidate 继续 fail closed。worker 在完整性异常中断时必须把 task/run 固化为真实失败状态，不能遗留无 lease 的 `collecting`。

现有未版本化 aggregate、core、累计 Chapter 01、next-session、collection 与 THS route 继续并行注册；THS catalog/bars 从 sector links 复用而不复制 contract。dashboard 逐页迁移且保留非完整性错误的 legacy fallback。该 change 不新增数据库 schema、provider、采集/调度、authentication、MCP 或部署路径。回滚只需撤下 v2/discovery router 注册并让 dashboard 恢复 legacy caller；PostgreSQL facts、snapshot、aggregate、collection state 和旧 API 均不变。

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

### 本地交易知识 MCP 边界（2026-09-27）

`src/trading_knowledge/` 是独立于市场环境 API 和交易规则执行器的本地知识服务。离线构建命令发现 `搭建交易系统/`、`搭建交易系统-量化版/`、`trading-rules/rule-sets/`、`trading-rules/coverage.yaml` 和 Git 中的 `evidence/` YAML，在 `.artifacts/knowledge-base/knowledge.sqlite3` 中生成 SQLite FTS5 索引。索引记录来源层级、标题路径、行号、规则 ID、状态和源文件 hash；CJK 二元字段用于中文检索，规则 ID、路径和状态使用精确字段。

Codex 通过 MCP stdio 调用五个只读工具：`search_trading_knowledge`、`get_source_excerpt`、`get_rule`、`get_evidence_status` 和 `get_index_status`。服务进程只打开本地索引和受控仓库文件，不导入 provider，不连接 PostgreSQL，不执行 shell，不访问网络，也没有写入工具。源文件 hash 发生漂移时查询返回 `stale`，必须重新运行索引构建；构建失败不会替换上一次索引。

机器规则、覆盖清单、证据摘要、量化说明和原始观点保持独立引用。YAML 是执行字段事实源，`latestEvidence: null`、`needs-backtest`、`documented-only`、`unverified` 和 `insufficient` 不得升级为 `validated`。

## 主要数据源

| 优先级 | 数据源 | 用途 |
|---|---|---|
| 1 | 扶摇指数历史 K 线（capability-gated） | `core` 显式切换后的主源；逐指数请求并严格校验日期、OHLC、成交额和 280 根最小历史 |
| 2 | mootdx（通达信 TCP） | 扶摇失败后的首个非东方财富历史降级 |
| 3 | 百度股市通 K 线 | mootdx 失败时的历史降级 |
| 4 | 新浪指数 K 线 | 指数历史成交量；按腾讯实时成交额校准历史成交额 |
| 5 | 腾讯历史 K 线 | 最后的非东方财富历史降级；历史成交额可能不可用 |
| 6 | 东方财富历史 K 线 | 最终历史降级；显式市场 `secid` 并提供指数历史成交额 |
| 7 | 腾讯财经实时行情 | 当前报价、涨跌幅、成交额和当前日期 Fuyao 价格交叉校验；历史日期不调用 |
| 8（末层, opt-in） | 静态 HTML 末层 — `sectors-sina-html` (`finance.sina.com.cn`) | sina 行业卡片：name、changePct、amount、leader 名（HTML 文本,经 `strip_leader_label` 处理后写入）；其余字段强制 `null + dom-source-unsupported:<field>` warning,绝不从成分股数 / 计数 / inflow 数值合成 mainNet / upCount 等不可见字段;revision `crawl-html-sina-v1`,capability-gated,默认禁用,只在前 6 步全部失败后启用 |
| 9（末层, opt-in） | 静态 HTML 末层 — `sectors-xueqiu-html` (`xueqiu.com`) | xueqiu 行业卡片,与 sina 同口径;revision `crawl-html-xueqiu-v1`,capability-gated,默认禁用,在 sina 失败或未启用后尝试;登录墙频率高于 sina,通常降级为 `degraded` |


市场环境 API 通过可选的 `chapter01` 对象扩展第 01 章证据。市场广度在批准 v2 revision 并显式启用时先完整分页拉取扶摇最新快照，再按开关进入 TDX 精确日期盘后包，最后才用东方财富 `push2delay` 涨跌幅排序分页；未启用 Fuyao 时仍从既有 TDX/Eastmoney 链开始。容量方向按成交额排序请求 Top-N 股票，`push2` 主域恢复失败或返回无效载荷后降级到同口径 `push2delay`，两个来源统一校验代码、名称、成交额、至少 30 个有效样本和成交额非递增排序，必要时才进入独立开关控制的 TDX derived，绝不调用 Fuyao。涨跌停生态以扶摇日期化三类池为 membership 主源、东方财富为降级和交叉核对源；扶摇分页必须覆盖 `pagination.total`，请求日期先由交易日历确认并记录 `dateEvidence=request-parameter`，两源按规范证券身份取并集，差异行和整日质量标记 `degraded`。扶摇 limits 与通用行情客户端共享进程级请求门和最小间隔；HTTP 429、`code=4001` 和 `code=5003` 使用较慢的有界指数退避，并在最终 warning 中保留脱敏业务码、message 和 request_id。该节流与退避只降低重复请求压力，不改变 exact-date、source revision、membership 完整性或失败保留门禁。行业板块排名继续使用东方财富主域到延迟域降级，行业领涨股名称取 `f128`，`f140` 仅为代码。当前快照型 provider 仅允许在上海时区的有效市场日采集；已持久化的精确快照可用于对应历史日期，禁止拿其他日期或今日数据回填。未接入的独立亏钱收益和事件输入保持 `null` / `insufficient`，并附 provider quality 和 warning。

### `breadth` / `activeDirection` 通达信盘后包备用边界（2026-09-29）

`breadth` 在批准 `fuyao-market-v2` 并显式启用后按 `Fuyao -> TDX daily package -> Eastmoney push2delay` 降级；TDX 必须由 `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED=1` 显式开启，关闭时扶摇失败直接进入东方财富最后降级。Fuyao `/api/a-share/prices/snapshot` 是 latest-only：必须用 `limit/offset` 拉完 `total`、证明每页 `timestamp` 均可解析且映射到请求的同一上海当前交易日；原始值可按页漂移，但必须保留 exact/date stability 与跨度证据，历史日期只读本地精确快照，不调用该接口。`activeDirection` 不参加本次 Fuyao 切换，仍按 `Eastmoney push2 -> push2delay -> 可选 TDX derived`；`sectors`、`limits` 和 `core` 不进入 breadth 的 TDX 链。盘后包客户端只请求 `https://www.tdx.com.cn/products/data/data/g4day/{YYYYMMDD}.zip`，保存请求日期、包内文件推导的源日期、抓取时间、文件完整性和市场行数；运行时不访问 GitHub。解析逻辑是对 `simonlin1212/a-stock-data` Apache-2.0 实现的最小兼容重写，固定 revision `2e0ae6383c649b2bc5f68d3bc430d357f1c59ae7`，具体边界和进度见 [`add-tdx-daily-package-fallback`](exec-plans/active/add-tdx-daily-package-fallback.md)。

盘后包的日期、证券代码、名称、收盘价、前收、成交额和市场完整性均需通过校验；缺失事实保持 `null` 或拒绝候选，不能用零值、代码字符串、当前行情或其他日期回填。解析器保留有价格的原始包行作为传输事实，但 `breadth` 和 TDX 派生 `activeDirection` 在消费前必须共享 `tdx-stock-universe-v1` 分类策略：按请求日期检查市场和代码号段，只保留可证明的上海主板/科创板、深圳主板/创业板和北京普通股票，基金、债券、指数、权证、B 股、存托凭证及未知身份全部排除。北京 `920` 号段按 2025-10-09 切换边界解释；过滤前、保留、排除、未分类数量、按市场保留统计和排除原因随 quality metadata 保存。分类后的普通股票样本还要单独通过市场覆盖和最小样本门槛，不能把原始全证券行数当作 `observations` 或广度分母。`breadth` 优先使用包内涨跌幅/前收，缺失时只允许通过精确交易日历取得相邻上一交易日包并对同一过滤后 universe 校验身份覆盖率。`activeDirection` 的原有 TDX breadth 开关不再控制派生方向：新开关 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED` 默认关闭，只有 Eastmoney 主域和延迟域都失败时才允许启用 TDX 派生路径；过滤后的普通股票按成交额降序、规范证券身份升序执行本地稳定排序，来源为 `tdx-daily-package-derived`、质量为 `fallback-derived`，并记录 `derived=true`、排序方法、TDX revision、行业映射 revision/覆盖率和前序 warning。它不伪装成 provider-ranked 结果。名称优先使用包内名称，缺失时仅对派生 Top-N 批量请求腾讯名称，腾讯不得提供价格、成交额或日期事实。`MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED` 仍只控制 breadth fallback。包未发布、日期冲突、格式损坏、证券宇宙不足或字段不足仍为 `failed`/`insufficient`，由 collection 层继续执行 `failed-missing`/`failed-retained`；派生成功可写入精确日期快照，但任务和父运行保持 `partial`。普通 GET、状态查询和聚合读取只读本地精确日期证据，不自动重采集、直接改 payload 或跨日期回填。解析逻辑是对 `simonlin1212/a-stock-data` Apache-2.0 实现的最小兼容重写，固定 revision `2e0ae6383c649b2bc5f68d3bc430d357f1c59ae7`，运行时不依赖 GitHub，也不提交真实全市场行业映射或数据快照。

研究看板交易日输入按浏览器本地时区生成：本地时间 15:00 前默认选择前一天，达到 15:00 后默认选择当天；首次核心响应若确认候选日为非交易日，前端只将自动日期同步为响应的有效 `asOf`，用户仍可在日期控件中手动选择不晚于当天的日期且手动值不被覆盖。数据采集页不复用研究页的 15:00 截止逻辑，但会在上海开市前（09:30）将省略 `as_of` 的请求解析为上一工作日对应的真实交易日（周末跳过）；若遇节假日或存储中没有可证明的实际日期，返回 `insufficient`/拒绝，不能猜测日期。开市前 provider 只能返回前一交易日数据时，必须以该实际日期保存，禁止将前一日行情写入当日键。开市后才允许按上海当天采集当前快照，用户手工切换后才发送显式日期。API 默认日期、“当前快照”判断和有效市场日解析统一使用 `Asia/Shanghai`，避免浏览器 UTC 转换或服务端部署时区把“今天”错位为前一日。东方财富全 A 快照解析同时接受数组和键值对象形式的 `data.diff`，仅保留有效对象行，并校验实际行数覆盖 `data.total` 后才允许按完整快照计算。

网页使用固定一级导航 `如何判断市场环境`，下设 01 至 09 文档视图；侧边栏另设“数据管理”入口 `/data-collection`，不改变交易知识文档层级。研究视图只解释 API 已返回的证据与质量状态，数据采集页只读取本地任务和快照状态并提供受控写操作；前端不补算缺失指标，不把未验证阈值渲染为确定性评分。所有可见界面文字和图表标签以 `14px` 为最小字号，标题与关键数字在此基础上维持层级。移动端将导航收纳为抽屉，宽表或采集状态行必须在自身容器内适配，页面不得横向溢出。
网页使用固定一级导航 `如何判断市场环境`，下设 01 至 09 文档视图；侧边栏另设“数据管理”入口 `/data-collection`，不改变交易知识文档层级。研究视图只解释 API 已返回的证据与质量状态，数据采集页只读取本地任务和快照状态并提供受控写操作；前端不补算缺失指标，不把未验证阈值渲染为确定性评分。第 01 页指数卡的指数主值和涨跌幅是独立复制交互，涨跌幅展示保留百分号而复制值去掉百分号，Clipboard API 不可用时只允许显式失败或受控降级，不伪造成功。所有可见界面文字和图表标签以 `14px` 为最小字号，标题与关键数字在此基础上维持层级。移动端将导航收纳为抽屉，宽表或采集状态行必须在自身容器内适配，页面不得横向溢出。

规则平台扩展数据包括全市场宽度、涨跌停/炸板池、板块与成交集中度、流动性和事件输入。行情优先 mootdx/腾讯，百度/新浪/东方财富作为明确降级；东方财富请求必须经单进程共享请求门串行执行，锁覆盖限流等待和完整 HTTP 请求，间隔至少 1 秒并加入抖动。连接/读取错误、429 和 5xx 使用有界退避重试，403 不盲目重试。公告、政策和突发事件必须保存来源与有效期；无法观测的主体意图不进入自动评分。

指数代码始终使用 `sh000001`、`sz399001` 等显式前缀。对百度/mootdx 存在沪市代码歧义的指数，必须有腾讯价格交叉校验，否则拒绝该源，避免股票数据静默冒充指数。

## 市场环境后端分层边界（2026-10-07）


## 末层 HTML 静态源（2026-10-09）

为 `sectors` 数据集新增两条互不相关的 **末层** 静态 HTML source adapter，与现有 4 步同名链解耦：

- `infrastructure/providers/html_common/` 拥有跨 host 共享的 DriftDetector、文本归一、HTML 选择器、fixture loader 和 SourceAdapter 基类；不依赖 `lxml`/`parsel`/`selectolax`，运行时仅要求标准库。
- `infrastructure/providers/sina_html/` 与 `infrastructure/providers/xueqiu_html/` 各自拥有一份 `SourceCapability`（revision 分别为 `crawl-html-sina-v1` 与 `crawl-html-xueqiu-v1`，`latest_only=True`，`available=True`），通过 `sectors_acquisition.SectorsAcquisitionPlan` 的 `_attempt_html_tier` 在 Eastmoney（主 + 延迟 + enrichment）+ Tushare + Fuyao 之后接入。
- 字段权威：`code` / `name` / `changePct` / `amount` / `leader` 五项可选；SUPPLEMENTAL_FIELDS（`mainNet` / `mainNetPct` / `upCount` / `downCount`）永远 `null` 并附带 `dom-source-unsupported:<field>` warning；原始页面把 leader 暴露成代码或数字徽标时 adapter 立即把 `leader` 改成 `null` 并追加 `leader-identifier-not-name` warning，绝不写入代码或数字。
- 失败路径与现有 `failed-retained` / `failed-missing` 一致：sina 失败 → xueqiu；都失败 → 既有 `FAILED_MISSING` 与前序 warning。
- 显式 host allowlist + 401/403/challenge 立即 fail-closed，禁止 engine 升级、retry、`requests` 后退或浏览器/SPA 渲染。
- 与 `bootstrap/settings.CrawlFallbackConfig`（`MARKET_ENVIRONMENT_CRAWL_FALLBACK_ENABLED` / `MARKET_ENVIRONMENT_CRAWL_FALLBACK_HOSTS`）以及 `bootstrap/registries.build_runtime_acquisition_registries(..., crawl_fallback_is_enabled=...)` 联动；`enabled=False` 时 container 完全跳过 adapter 注册，plan 步骤不出现，`openspec validate add-static-html-sector-fallback` 通过。
- capability promotion 与真实 probe 均不在本次代码路径内：`python -m src.market_environment.cli sectors-html real-probe --source <sina|xueqiu>-html --as-of ... --output ...` 默认 dry-run，只有 `--allow-real` + `MARKET_ENVIRONMENT_PROBE_ALLOW_REAL=1` 才发单次 bodyless GET，且输出 envelope 永不包含 token / cookie / body。

`src/market_environment/` 保持单体进程和单镜像部署，但内部依赖改为可执行的单向分层，不再由扁平模块互相构造具体实现：

```text
interfaces/http ----> application ----> domain
       |                   ^               ^
       |                   |               |
       +---- bootstrap ----+               |
                    |                      |
                    +---- infrastructure --+
```

- `bootstrap/` 是唯一 composition root：读取不可变配置、装配 PostgreSQL repository、provider collector、查询/命令 use case 和有界 executor，并由 FastAPI lifespan 负责资源关闭。稳定入口 `src.market_environment.api:app` 只创建应用对象，不在模块导入时连接数据库、建表、请求 provider 或提交后台任务。
- `interfaces/http/` 只处理 FastAPI router、身份/时区上下文、输入输出 DTO 和错误映射；router 通过 typed dependency 获取 use case，不直接构造 store、provider、coordinator 或 executor。CLI 使用独立 composition builder，复用 application/infrastructure，但不创建 FastAPI。
- `application/` 按 query、command、collection 和 port 分组。query 仅依赖只读 repository 与纯分析服务，不能获得 collector/provider；command 才可持有 collector registry、写 repository 和 task executor。因此普通 GET、collection status 与 next-session 的 provider-free 边界由构造关系保证。
- `domain/` 保存精确日期、质量/缓存、collection outcome、run/task 状态等领域值，以及指数、广度、同步性和涨跌停生态纯计算；不得导入 FastAPI、SQLAlchemy、requests 或 infrastructure。
- `infrastructure/` 实现 PostgreSQL persistence、SQLite 停写迁移/测试适配器、外部 provider、collector 和进程内 executor。共享 HTTP transport、Fuyao request gate、TDX 包客户端等保持基础设施复用，不向 application 暴露具体 vendor client。

采集侧固定由 stable dataset id 映射到五个 collector：`core`、`breadth`、`limits`、`sectors`、`activeDirection`。目标边界中，每个 collector 只接收 typed `DatasetDate`、执行已注册的 dataset acquisition plan 并返回 `CollectionOutcome`；provider 优先级、fallback、shadow、enrichment、日期能力与字段权威由 plan 和 source adapter 表达，不进入 coordinator。collection coordinator 只负责请求验证、run/task 生命周期、lease/fencing、collector 调用、typed committer、同日期失败留存、最多一次聚合重建和父状态归并。迁移期间允许无副作用的 compatibility adapter 包装尚未迁移的 provider 方法，但不得嵌套 coordinator、二次 lease、直接提交快照或重复重建聚合；移动代码时不得同时改变算法或降级顺序。

持久化按 snapshot、collection run/task、lease、trading session、materialized aggregate、provider capability、limits fact/detail 和 timezone preference 拆分 repository；需要原子性的操作继续共享 PostgreSQL unit of work，不能因为接口拆分而拆散 fenced write、limits manifest/fact 或 aggregate CAS 事务。PostgreSQL 是 Dashboard service 和所有采集 command 的唯一正式运行时；运行时只校验连接和 Alembic schema 兼容性，不调用 `create_schema`。Alembic `0003_provider_capability_reports` 以非破坏方式创建 runtime 已要求的 capability table/index 并登记 schema version 6，不改写既有市场表、payload 或 checksum。SQLite 仅允许作为测试适配器或停写的一次性导入源，配置 PostgreSQL 的运行时不得静默回退。

迁移期间允许旧 `api.py`、CLI 路径和经清单登记的根级导入 shim 保持兼容；shim 只转发到 `domain`、`interfaces` 或 `infrastructure` 的目标实现，不新增业务逻辑。纯计算位于 `domain/analysis` / `domain/policies`，HTTP DTO 位于 `interfaces/http/schemas`，迁移辅助位于 `infrastructure/persistence`，Fuyao/TDX 实现分别位于 `infrastructure/providers/fuyao` 与 `infrastructure/providers/tdx`。普通 runtime 使用 `infrastructure/providers/runtime.py::CollectorProviderRuntime`、明确命名的 PostgreSQL store、application query/command 和 `MaterializationSupport`，不继承或构造 legacy `MarketDataProvider`、旧 service 或 `Legacy*` coordinator facade；`infrastructure/legacy/providers.py` 只保留稳定重导出和同类身份 alias。兼容 snapshot store 仍被 PostgreSQL runtime adapter 传递使用，不能与 provider facade 一并删除。逐文件的运行时/兼容/维护状态和 shim 退役矩阵见 `src/market_environment/AGENTS.md`。仓库使用 `scripts/check_market_environment_architecture.py` AST/import 门禁阻止 domain/application 反向依赖、query 导入 provider、router 直接装配基础设施、normal runtime 重新依赖 legacy provider、compatibility shim 嵌套 coordinator、shim 内新增业务逻辑、未登记根模块及 production 子包重新依赖已迁移根实现。

### 统一采集适配器目标边界（2026-10-08）

统一的是采集结果、失败分类、数据集计划和注册表，不是强制所有来源使用 HTTP 或同一第三方库。目标依赖只能沿下列方向流动：

```text
application command
  -> DatasetCollectorRegistry
  -> DatasetCollector.collect(DatasetDate) -> CollectionOutcome
  -> DatasetAcquisitionPlanRegistry
  -> DatasetAcquisitionPlan
  -> SourceAdapterRegistry
  -> SourceAdapter.acquire(SourceRequest)
  -> governed HTTP transport 或非 HTTP client
  -> normalized candidate / classified failure + ordered evidence
  -> DatasetCommitterRegistry + LocalProjectorRegistry
  -> coordinator retention / commit / aggregate rebuild
```

- `application/ports` 与 `domain` 只定义 typed dataset/date、candidate/outcome、failure、attempt evidence、source capability、committer/projector 等稳定契约，不导入 FastAPI、persistence、vendor client、`requests.Response` 或 Scrapling 原生类型。
- dataset acquisition plan 是确定性基础设施策略：描述 formal、fallback、shadow、enrichment 的有序步骤。source adapter 负责认证、请求构造、供应商载荷解析、实际日期证明、字段能力与归一化；shadow 不改变正式 payload/source/checksum/task state，enrichment 只填允许字段。
- bootstrap 是唯一 composition root，必须在任何外部 I/O 前验证七个 stable dataset、所有 plan/adapter/capability revision、committer、local projector 和 transport engine 注册完整。缺失、重复、未知或不可用配置一律 fail closed。
- coordinator 不解释供应商异常或 payload，不通过 `inspect.signature` 发现 collector 能力。它为每个 dataset/date 管理唯一 lease 和 task transition，并从同日期本地存储推导 `failed-retained`/`failed-missing`。
- 普通数据集使用标准 snapshot committer；`core` 和 `limits` 使用 typed committer，在同一 PostgreSQL unit of work 和 fence 内分别保持指数子结果/交易日证据，以及 membership/detail/fact/manifest 的原子性。status detail 通过完整 local projector registry 读取，provider/transport 调用数必须为 0。
- 共享 HTTP 层由进程内唯一 policy gateway 和 engine registry 组成。gateway 独占 host pacing、请求预算、网络/408/429/5xx 重试、`Retry-After`、single-flight、缓存、cooldown/half-open、请求身份与脱敏诊断；engine 每次只执行一个已授权请求。Fuyao limits 与 market 客户端注入同一 gateway，缺 API key 时在 I/O 前失败，401/403 不重试；只有 HTTP 200 内的 `4001`/`5003` 等业务 envelope 仍由 adapter 做有界慢退避并保留脱敏 request ID。请求身份至少包含 engine、精确请求日期、完整规范化参数和不可逆 authentication/tenant-scope digest，不能跨日期、engine 或认证范围复用。
- `requests` 是默认 engine。Scrapling 仅通过精确版本的 `requirements-scrapling.txt` 可选 profile 提供静态 HTTP engine，host/source allowlist 默认空且不在 requests 失败后自动升级；基础 `requirements.txt` 与默认镜像不安装它。禁止 Spider、浏览器/Chromium、代理轮换、内部重试、blocked-request escalation、challenge solving 和 401/403 绕过。
- host policy 仍是单进程边界；PostgreSQL lease 只去重 dataset/date 工作，不宣称 Dashboard、自动化 HTTP 调用方或维护 CLI 之间共享分布式 HTTP 限流。跨进程限流需要独立设计。
- `ProviderResult` 与 Fuyao/TDX 原生结果只可停留在 source adapter 下方。七数据集正常 runtime 已不再继承或构造 legacy all-dataset facade；成熟 provider mechanics 由正式 `CollectorProviderRuntime` 持有，`MarketDataProvider` 仅为同一类的稳定 alias。根导入、CLI real probe、旧 collector/coordinator fallback、legacy service/`SnapshotRefresher` 和兼容测试的退役前置条件按 `src/market_environment/AGENTS.md` 清单管理。

## 运行时流

### 第 05 页申万一级行业持续性数据流（规划边界）

第 05 页的 canonical analysis 与现有 provider observation 是两条独立但可关联的证据链：

```text
taxonomy revision + point-in-time membership
        + security daily facts (adjusted price, original amount)
        + ordinary-a-share benchmark + trading calendar
                         │
                         ▼
               industry aggregate (exact as-of)
                         │
                         ▼
                 continuity analysis (5 metrics)
                         │
                         ├── up to 3 canonical candidates
                         └── exactly 1 unique validation item

provider sector observation ──(optional exact-date mapping)──► association only
```

只允许申万一级行业。`taxonomy`、`membership`、`security_daily_fact`、`benchmark_fact`、`industry_aggregate`、`continuity_result`、`backfill_run` 和 `backfill_date_attempt` 是独立的、带版本/checksum/精确日期或有效区间的领域事实；概念/题材、当前成分股、跨日期排名和按名称猜测均不能进入 canonical analysis。五项指标分别是 5/20 日相对强度较低分位、近 5 日成交额横截面前 20% 天数、前复权站上 MA20 比例分位、负收益分歧两日 50% 修复承接率和申万一级前五成交集中度。分析最多三个候选，且只渲染一个下一交易日验证项；不自动赋予龙头/中军/补涨角色。

实现时保持单向依赖：`domain/models` 与 `domain/analysis` 只保存不可变值对象和纯计算；`application/ports` 定义 repository、unit-of-work、backfill、capability 和 provider-free query 契约；`application/commands` 才能编排显式 backfill/写入；`application/queries` 只能读本地结果；`infrastructure/persistence/postgres` 提供 additive migration、repository、UoW、lease/fencing；`infrastructure/providers` 只负责 capability-gated source adapter 和导入，不写快照或分析。普通 GET、状态读取和启动不获得 backfill 或 provider 能力；七数据集日常采集与默认调度也不得隐式触发历史回填或 dump 导入。

`SectorEvidence.analysis` 是可选扩展，原有 provider observation 的 `rows/state/quality` 必须原样保留。observation quality、canonical analysis quality 和 backfill attempt 状态分别记录；分析成功而 observation 缺失、observation 成功而分析 `insufficient`、同日兼容结果 `failed-retained` 与无兼容结果 `failed-missing` 不得相互覆盖。provider observation 只有在精确日期、版本化、唯一 mapping 通过时才保留双身份关联，模糊/冲突时保持未关联。

历史回填是独立、显式、有界、可恢复的 application workflow，默认预热 272 个交易日，也可请求小范围修复或更长研究区间。它按权威交易日历逐日运行输入、聚合、分析阶段，持久化 parent run 与 per-date attempt；成功日期幂等复用，失败日期可恢复重试，不加入 `SUPPORTED_COLLECTION_DATASETS`，不改变现有七类日常采集任务语义。

交易规则桥接采用 snapshot v2：新增 closed `metricProvenance`，从同日 materialized continuity result 复制五个 canonical 指标（前四项取第一候选，集中度取市场级值），不重算、不发 provider 请求；冻结 v1 snapshot 继续可 replay。taxonomy/data/membership/universe/adjustment/benchmark/calculation 及上游 immutable evidence revision 进入规范化 hash，但当前输出 evidence bundle ID 不得自引用。

普通读取流为：浏览器 → Vite `/api` 代理 → FastAPI `src/market_environment/api.py` 稳定入口 → HTTP router → provider-free query use case → PostgreSQL materialized aggregate / read repository。`/api/market-environment`、`/core`、`/chapter-01`、`/next-session` 和 collection status 只读取精确日期本地结果；缺失、陈旧或活动采集不得在普通 GET 中启动外部 provider。

手工采集流为：`/data-collection` → collection command use case → `TaskExecutor` 端口的有界进程内实现 → collection coordinator → 七个独立 dataset task → collector registry → dataset acquisition plan / THS 专用 collector → normalized outcome → typed committer → 成功提交后聚合响应重建。父批次只汇总 `success` / `partial` / `failed`；`core`、`breadth`、`limits`、`industry-ranking`、`sector-turnover`、`sector-breadth` 和 `activeDirection` 各自持有 `(dataset, as_of)` lease，三项 THS 任务按 `industry-ranking -> sector-turnover -> sector-breadth` 执行，单项失败不停止无关任务，也不覆盖同日期成功快照。旧 `sectors` 不再进入公共 coordinator，只能通过审计路径读取历史证据。不同 task 可以由 executor 调度，但同一进程的所有 HTTP adapter 共用唯一 policy gateway；CLI 与 HTTP 复用同一 application command，不通过 shell 启动子进程。TDX 包/TCP 等非 HTTP 来源仍通过 source adapter 返回同一 outcome，普通 GET、状态查询和 provider-free 读取绝不触发任何外部来源。

盘后自动采集流为：`192.168.1.21` 上的 Hermes Agent（工作日 15:30，`Asia/Shanghai`，投递到已批准的飞书当前会话）→ 确定性 pre-run caller → `POST /api/market-environment/collection-runs/full` → 持久化幂等 claim → 有界进程内 executor → collection coordinator → 七个独立 task → PostgreSQL。Hermes 只拥有触发时钟、16:00 前的有限补偿与轮询和中文结果投递，不选择日期、数据集或 provider；后端按上海时间解析有效日期，结算边界前以 422 且零写入拒绝，周末返回无 run、无 provider I/O 的 `skipped`。端点固定使用七数据集 canonical tuple，不对 `partial` 自动整批重试；不同 key 或维护触发并发时仍由 PostgreSQL dataset/date lease 作为最终边界。第一版不维护交易所节假日日历，工作日节假日可能留下真实 failed/partial 记录，但精确日期校验禁止把其他交易日数据写成当天。

全量自动化端点要求 `Idempotency-Key`，并在 PostgreSQL 中原子绑定 operation scope、版本化语义指纹、服务端解析日期、canonical dataset fingerprint、run 和 submission state。同 key、同语义在断线、202、进程重启或 executor 拒绝后只恢复原 run；wait timeout 不进入语义指纹；同 key、不同日期/operation version/dataset fingerprint 返回 409。terminal `success`、`partial`、`failed` 均是 HTTP 200 业务结果；900 秒内未终结则返回 HTTP 202、`Location`、`Retry-After` 与 provider-free `statusUrl`，客户端断开不取消后台任务。任务持久化 nullable `failure {category,message,retryable,retained}`；success 的 failure 为 null，failed-retained、failed-missing、blocked、busy 和 worker-interrupted 必须保存稳定分类而不是要求调用方解析 warning。

生产部署使用单镜像边界：Node 构建阶段生成 `apps/market-environment-dashboard/dist`，Python 运行阶段由 FastAPI 同时托管静态网页与 `/api`。`deploy/k3s/` 与 `deploy/helm/a-stock/` 只部署 PostgreSQL、migration 和 Dashboard service，不再渲染、安装、暂停或激活 application-owned market-data CronJob；原 `deploy/k3s-native-scheduled/`、Helm `scheduledCollection`、TrueNAS scheduling overlays 与正向调度 packet 属于本 change 的退役面。普通部署仍在任何写入前后，以 release-derived `a-stock-data-collection` 和 legacy `market-data-collection` 两个精确名称检查 stored manifest 与 live state；任一 active 或 suspended legacy CronJob 存在都 fail closed，清理必须另行审核，普通部署不得静默忽略、接管或激活它。

默认路径为 Traefik Ingress → ClusterIP Service → 单副本 Deployment，也允许单节点环境显式使用明文 HTTP `NodePort:32001`。`MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED` 默认关闭且只控制新的 full-collection endpoint；`MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 独立控制现有手工 POST，生产可保持 manual=0 而单独启用 automation。automation 的 `0→1` 与 `1→0` 都只能使用同镜像、完整 reviewed packet、无 hook 的受控部署入口；停写时还必须先暂停 Hermes 并证明活动 run/task/lease 为零。当前没有应用身份认证、TLS 或请求级授权；一旦 automation gate 开启，任何能路由到 `192.168.1.20:32001` 的客户端均可调用，idempotency、CORS、UI 隐藏和 dataset lease 都不是鉴权。Hermes 不获得 PostgreSQL Secret、PVC、provider 凭据或部署权限。部署控制面继续通过审核过的 Helm/kubectl 通道，和应用 NodePort 分离。

Dashboard 与所有采集任务通过 PostgreSQL ClusterIP Service 访问共享状态；只有 PostgreSQL StatefulSet 持久化到独立 Retain RWO PVC，应用工作负载不挂载数据库 PVC。当前 PostgreSQL 事务、lease/fencing、持久幂等和 provider 限流按单主边界设计，因此默认保持一个 Uvicorn 进程和一个 Dashboard Pod；扩展为多副本前必须先引入高可用 PostgreSQL、共享 provider 限流与提交恢复协调方案。健康探针只访问不触发外部 provider 的 `/api/health`。

需要构建镜像的 `all/service` 部署在 `podman save` 前读取本地镜像实际大小，加 25%（最低 256 MiB）安全余量后选择归档临时文件系统。显式 `DEPLOY_TMP_ROOT` 不满足条件时 fail closed；未显式配置时依次检查 `TMPDIR`、`/dev/shm` 和 `/tmp`。归档传输完成即清理本次唯一临时目录，失败和信号路径由退出 trap 兜底；`database` 不生成镜像归档，也不受该容量门禁影响。该边界只保护本地归档写入，Podman graphRoot 与 TrueNAS 远端归档数据集仍需独立容量治理。

`a-stock-data-collection`（历史 Helm-owned）和 `market-data-collection`（历史 legacy override）只作为负向检测 identity 保留。仓库不再提供它们的 template、overlay、release/activation/disable 模式或 `scheduled-refresh` CLI；发现任一资源时必须停止普通部署并进入另行审核的遗留资源处置，不得为验证退役而重新创建。

普通 TrueNAS Helm 发布同时按 release 派生名称和固定 legacy 名称做只读查询；stored manifest 或 live state 中任一 legacy CronJob 存在时，即使它为 suspended，也必须在 build、Helm write 或 application rollback 前 fail closed。该 guard 不把 PostgreSQL StatefulSet/PVC 纳入旧调度 ownership，也不提供修改 CronJob 的正向能力。离线 render 必须证明所有支持的 profile 都不含 application CronJob，目标组件写入仍验证受审 baseline 的 release/namespace。

### TrueNAS k3s 组件化部署边界

`scripts/deploy-truenas-k3s.sh` 是 TrueNAS 的唯一组件入口，`--component` 只保留
`all`、`database`、`service`。三种操作共享同一个 Helm release、release name、namespace 和受审 values
packet；组件选择只改变本次期望资源集合，不创建竞争性的 Helm release。`all` 的依赖图固定为
`postgresql -> schema migration -> service`：

- `database` 负责 PostgreSQL StatefulSet、ClusterIP、existingSecret 合同和独立 Retain RWO
  claim；旧 SQLite claim 只作为显式迁移源验证，不由 Dashboard 应用挂载，且不被隐式删除、
  替换、扩容或重新绑定。
- `service` 依赖已验证的 namespace、绑定 PVC 和不可变镜像，保持单副本 Deployment、
  Dashboard Service/Ingress、健康探针及非 root/read-only-rootfs 安全上下文。镜像变更只
  更新服务工作负载，使用 PostgreSQL Service/Secret，不挂载数据库 PVC。
- 这里的“应用 Job 保持 absent”只指调度或 provider-backed collection Job。经单独授权的 backend/schema
  rollout 可以短暂创建唯一例外：精确的 provider-free `a-stock-schema-migration` Helm hook；冻结 manifest
  中的命令只能是 `alembic upgrade head`，render 必须只有这一项 Job，legacy SQLite migration 保持关闭。
  `all` 流程只允许 database 阶段的一次 Helm upgrade 执行该 hook；service 阶段和最终完整 release 收敛都
  使用 `--no-hooks`。成功后必须在 provider-free 验收前证明该 hook 与全部 namespace Job 已 absent；hook
  失败时立即停止 service rollout 和完整 release 收敛，保留 failed Job 与脱敏诊断证据，不得通过删除 Job
  制造 absent 结果。
- 历史 `schedule` component 和 `--release-suspended` / `--activate-schedule` /
  `--disable-schedule` 模式全部退役；普通组件只执行两项只读负向检查：stored manifest 不含旧
  CronJob，live cluster 中两个旧 identity 都 absent。

每个组件先执行 typed values、资源集合和依赖预检，再写入并读取 server-observed postcondition；
失败输出区分 prerequisite/component，并给出唯一重试组件。组件操作仍由单个 Helm release
管理资源，避免对同一 Deployment、Service、Ingress 或 PVC 产生多套 ownership。
`database` 不构建或传输镜像，`service`/`all` 复用不可变镜像构建、烟测、校验和、SCP 与
containerd import。组件参数本身不构成自动采集授权；自动采集只由独立的后端 automation gate 与
Hermes job 共同控制。普通部署对旧 CronJob 的检查只能读取和拒绝，不能 patch、删除或接管；发现遗留资源后的
处置需要单独审批并使用冻结证据包，且不得恢复正向 Kubernetes 调度能力。

部署文档的可执行命令属于发布边界。CommonMark/Bash AST 审计对 brace/glob、`eval`、stdin-fed `bash`/`sh`/`dash`/`zsh`、`source`/`.`、`alias`/`hash -p` 命令解析变更、动态 executable/action 与未知 Helm plugin/action 全部 fail closed；解析不确定不能视为只读。

`.github/workflows/trading-rules-after-market.yml` 是独立的交易规则证据流水线：它在 GitHub runner 创建临时 snapshot/evidence Artifact，不挂载部署 PVC，也不向市场环境 PostgreSQL 写入数据。它不能替代 Hermes 触发的市场环境采集，两者的产物和运维边界必须保持区分。

服务层默认请求 280 个交易日，先按 `as_of` 截断到最近交易日，再计算 MA5/10/20/60、20/60 日高低价区间位置、成交额比值、趋势状态、量价状态、MA20 斜率 250 日滚动分位和量价推进效率 250 日滚动分位；60–249 个有效观测降置信，少于 60 个输出 `insufficient-history`。五指数同步性按同步上涨、普遍走弱、权重护盘、成长占优、分化未定型五态输出，深证成指只参与同步多数。五态是仅由指数涨跌得出的观察事实，服务层另以市场广度、指数相对 MA20 的多数位置和指数成交额形成 `synchronizationAssessment`，分别输出确认、反驳、中性或不足证据，再映射为市场层确认状态与稳定结论码；确认结果不得反写五态。系统性下降必须同时具备弱广度、至少三个指数位于 MA20 下方和至少三个指数放量下跌，权重护盘和成长占优也必须通过各自的广度与量能门槛。服务层进一步计算五指数均线多头比例、六类组合、四问结论和盘后收束句；缺失指标附 `insufficient-history`、`missing-today`、`provider-failed` 或 `not-computable`。量价状态与六类组合仍不使用通用兜底。返回给前端的 60 日历史点保留真实 OHLC、成交额和均线；前端仅负责渲染、矩阵聚合与选中行交互，不补算阈值。单指数失败保留其他指数并写入 warning；全部失败返回 503。

核心指数、市场广度、涨跌停生态、行业板块和容量方向统一使用 PostgreSQL 的按交易日持久化快照，记录规范化 payload、来源、抓取时间、样本数、质量、warning、schema version 和 SHA-256。成功快照与 collection attempt 分开存储：失败尝试只记录 `failed-retained` 或 `failed-missing`，不得覆盖同日期成功值，也不得跨日期回填。`breadth` / `activeDirection` 的历史 latest-only 修复只能由显式本地 CLI `snapshots refresh --force` 触发；普通 API、定时刷新和 provider-free GET 不获得该许可。`core` 内部对五个指数分别记录子项状态，单指数失败允许 core 为 `partial`。SQLite 文件只由停写迁移工具作为只读输入和归档。

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

旧版 SQLite/PVC 文字仅代表迁移前历史，不再描述当前运行时。Dashboard Deployment 内的 HTTP/maintenance collection application 通过同一 PostgreSQL ClusterIP Service 和 Secret 连接配置访问共享状态；只有 PostgreSQL StatefulSet 挂载 Retain RWO PVC。应用工作负载不挂载 SQLite 或 PostgreSQL PVC，`MARKET_ENVIRONMENT_SNAPSHOT_PATH` 仅允许一次性导入工具使用。迁移 Job 按 `postgresql -> schema migration -> service` 顺序执行；首次 PostgreSQL 写入后不回切过期 SQLite。

前端仅消费固定 JSON 契约，不直接访问行情源。纯计算归属 `domain/analysis` 与 `domain/policies`，application query/command 只通过 ports 读取或写入；数据源差异和七数据集 collector 位于 `infrastructure/providers`，PostgreSQL repositories/unit of work 位于 `infrastructure/persistence/postgres`，HTTP 错误映射位于 `interfaces/http`，具体装配只在 `bootstrap`。CLI 与 HTTP 共用 application command/query 边界。手工采集通过 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 控制，自动化 full endpoint 通过默认关闭的 `MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED` 独立控制；任一开关都不是身份认证。出现异常调用、provider 压力、PostgreSQL 锁等待或数据库 PVC 增长时，先关闭对应写入口并按现场捕获的 release/network baseline 处置；首次 PostgreSQL 写入后不得回切过期 SQLite。Hermes 停止路径只暂停外部 job 并关闭 automation gate，不恢复 Kubernetes 调度、不删除 Deployment、PVC、幂等绑定、task 或快照。

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
src/market_environment/bootstrap/   FastAPI/CLI composition root、配置与资源生命周期
src/market_environment/interfaces/  HTTP router、DTO、错误映射与 CLI 入口适配
src/market_environment/application/ query/command、collection 编排与抽象 ports
src/market_environment/domain/      领域值、精确日期/质量策略与纯市场分析
src/market_environment/infrastructure/ PostgreSQL、迁移 SQLite、provider collector 与 executor
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
- 扶摇市场数据迁移采用 `src/market_environment/infrastructure/providers/fuyao/market.py`，与同包下 `limits_client.py` 的 limits 专用 `FuyaoClient` 并行存在。正常 composition 为两个客户端注入同一个进程级 policy gateway，由 gateway 统一执行串行节流、请求预算和 transport retry；HTTP 200 的 `4001`/`5003` 等业务码有界重试仍由客户端负责，兼容 fixture 才保留可注入的 `request_gate`。根级 `fuyao*.py` 只保留稳定兼容导出。最终错误只保留脱敏的 `code`、`message`、`request_id`。`core` 与 `breadth` 的当前契约 revision 为 `fuyao-market-v2`：前者只使用 `/api/a-share-index/prices/historical` 的逐指数 `thscode/start/end/date_ms` 契约，后者只使用 `/api/a-share/prices/snapshot` 的完整 `limit/offset` 分页。旧 `fuyao-market-v1` 不得批准这两个数据集。`sectors` 仍是东方财富主链后的 Fuyao fallback；`activeDirection` 强制保留 Eastmoney/TDX 链且 capability 保持 `unverified`。所有开关默认关闭。TDX 配置与盘后包实现对应位于 `infrastructure/providers/tdx/config.py` 和 `daily_package.py`，不改变其显式 probe/collector-only 边界。
- 除下述 core 正式启用例外外，shadow 对账结果只进入采集任务 `timings` 元数据，不覆盖正式快照、source 或 checksum；能力报告保存在 `provider_capability_reports`，SQLite/PostgreSQL 均为加法 schema。

### Fuyao core 正式首选与无 shadow 边界（2026-10-19，离线实现完成）

`core` 的唯一生产组合继续是 typed `CoreAcquisitionPlan`。当
`MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED=1`、批准 revision 精确为 `fuyao-market-v2`，且运行时存在
同 identity 的 `eligible` capability report 时，五个指数分别按
`Fuyao -> mootdx -> 百度 -> 新浪 -> 腾讯 -> 东方财富` 尝试。Fuyao candidate 只有同时证明规范指数身份、
请求日精确尾日、至少 280 根完整 OHLC 与直接成交额时才能成为正式证据；正式 payload、provenance、
fingerprint 和 typed quality 均保留 `amountEvidence=direct-turnover` 与 source revision。任一指数失败只推进
该指数的 fallback，其他 Fuyao 成功不丢失；fallback 保留实际来源和 Fuyao 分类 warning，全部来源失败时
只允许留存请求日已有合法证据，禁止跨日期 candidate 进入 snapshot 或 aggregate。

core 正式启用是 shadow 的明确例外：off/enabled 配置都强制
`MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED=0`，正式采集不发起独立 comparison request，不持久化
容差、其他 provider 数值或多日对账结果。当前日期腾讯报价仍用于指数身份/价格 sanity check，但它不是
历史 provider 对账；历史日期不请求实时价格。用户已接受因此无法发现“字段完整但成交额语义不同”的风险，
系统不得缩放、替换或重标 Fuyao 直接成交额。

`fuyao/core/fuyao-market-v2` capability policy 只审查 Fuyao 自身：固定历史 endpoint、五个规范身份、
OHLC/直接成交额覆盖、每指数请求日与尾日一致、每指数至少 280 根、显式真实 probe 权限以及
`0 < requestsUsed <= requestBudget`。报告禁止包含 shadow/comparison/tolerance/provider-values；generic promotion
继续校验脱敏结构和 canonical checksum，并只写一条 capability row。两份完整 TrueNAS profile 固定相同镜像、
Secret/PVC/Service/数据库/调度/其他数据集和 revision v2，唯一启用差异是
`MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED: 0 -> 1`，部署使用 hook-free same-image 路径。普通 GET、status 和
materialized aggregate 仍只读本地精确日期 PostgreSQL 证据，绝不因 core 缺失而调用 Fuyao 或 fallback。

### 行业板块扶摇降级边界（2026-09-29）

`sectors` 的正式来源仍是东方财富 `push2`，失败后才尝试
`push2delay`；只有两条东方财富路径均失败、
`MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED=1`、扶摇 capability report 为
`eligible` 且 `MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION` 完全匹配时，
采集 coordinator 才允许使用扶摇行业 fallback。扶摇基址为
`https://fuyao.aicubes.cn`，行业契约由三个只读 endpoint 组成：

- `GET /api/a-share/calendar/trading-days`：证明请求日期是上海交易日；
- `GET /api/a-share-index/catalog/ths-index-list?tag=industry`：读取同花顺行业指数目录；
- `GET /api/a-share-index/prices/snapshot?thscodes=...`：按目录代码分批读取指数快照。

目录和快照必须绑定同一上海日期、覆盖完整目录（当前探针为 320/320）并按涨跌幅降序、
代码升序稳定排序。结果只映射行业代码、名称、涨跌幅和成交额；扶摇不提供主力净流入、
主力净流入比例、上涨/下跌家数或领涨股，这些字段保持 `null`，质量为 fallback/partial
并附字段 warning。行业快照的 `data.timestamp` 是响应时间戳，分批请求的原始毫秒值可以不同，
但必须全部映射到同一上海交易日；日期、身份、跨交易日批次时间或覆盖校验失败时 fail closed，不能用最新快照包装
历史日期，也不能用零值或其他日期补齐。

行业 fallback 继续复用 `SectorRow` 和现有 `fallback`/`partial` 质量语义，并合并两条东方财富
失败 warning、扶摇 source/revision、字段缺失 warning 和 exact-date 证据。`GET`、status、
materialized aggregate 与快照读取均 provider-free，只读本地 `(dataset, as_of)` 结果；失败时
仍按同日期 `failed-retained` / `failed-missing` 处理，不跨日期回填。扶摇 capability 报告只
保留 endpoint、日期、目录/快照数量、字段覆盖、权限/限流结果等脱敏证据，API key 只由独立
Secret 注入，绝不进入 values、日志、报告或 API 响应。

隔离 probe 与正式运行时之间增加独立的 capability promotion application boundary。CLI
`python -m src.market_environment.cli capabilities promote --input <report.json|-> --provider <provider> --dataset <dataset> --revision <revision> [--apply]`
只负责解析脱敏报告 envelope、选择唯一匹配报告、验证原始 canonical checksum、identity、`eligible`
状态和注册的数据集证据策略，并通过正常运行时配置解析目标 PostgreSQL；数据库连接信息不得作为命令行参数或输出。
默认 dry-run 只做冲突检查并输出脱敏计划，显式 `--apply` 才通过 provider-capability repository/UoW
在一个事务中写入一条报告。同 identity/checksum 重复晋升幂等，同 revision 不同 checksum 冲突拒绝，未知策略和
`fuyao-market-v1` fail closed。标准 redaction 应用于输入后必须与原结构完全一致，检查失败时不得回显敏感值。
`--input -` 只接受一个 stdin JSON envelope；空输入、畸形输入和多文档输入均在 repository write 前拒绝。

`fuyao/sectors/fuyao-market-v2` 的 evidence policy 固定要求三个允许 endpoint、envelope/requested/calendar/snapshot
日期完全一致、320 个唯一目录与 320 个唯一快照及 1.0 覆盖率、同一上海交易日的批次时间、代码/名称/涨跌幅/成交额
四字段完整、五个不支持字段明确缺失、权限已配置，且 `0 < requestsUsed <= requestBudget`。promotion 不装配 provider
client、collection coordinator、snapshot committer、scheduler、deployment/Secret client，也不修改 enabled 或 approved
revision；因此它可以在 provider 不可达时独立完成，但不能被当作启用或采集证据。

生产恢复先冻结绑定 clean reviewed HEAD、chart、off/enabled values、两份 render、release、namespace、Kubernetes
version 和 image repository/tag 的 source packet，再把包含 promotion CLI 的新镜像构建、传输并 import 恰好一次。
入口从目标 containerd 的 exact tag 读取唯一 manifest digest，在任何 Helm write 前完成不可变 image identity 和 production
packet；预填 digest 若存在必须与读取值一致。发布前因 dirty source、source packet hash/identity drift、可选 engine 开启、
CronJob 存在或候选 sectors 已启用而失败时，必须在网络或集群写入前停止；import 后无法证明 exact digest 时必须在 Helm
write 前停止。随后才以 sectors-off 完整 release 发布。调度关闭时，database/service 分段写入后的 `component=all` 完整
release 收敛是 stage 的终点；即使此时已经解析出 `FROZEN_IMAGE_*`，也不得再执行 schedule component 写入并把 stored
manifest 缩窄。

若历史中断恰好留下预期 deployed revision 的受审 empty non-hook disabled schedule-component stored manifest 与 computed values，但 live Deployment→ReplicaSet→Ready Pod 仍证明 exact
frozen image、sectors-off，且两个 application CronJob 与 namespace Job 均 absent，可通过独立
`repair-sectors-off-release` 恢复。该入口从新的 clean reviewed control-plane HEAD 运行，但复用原 stage 已记录的 image
source HEAD、tag 和 manifest digest；写前通过 `helm get metadata`、`helm get values --all`、`helm get hooks`
证明 revision/status/chart/hooks/computed values 与 stored manifest 精确等于受审 failure shape、tracked live Deployment/Service 精确
等于受审完整 off release 的持续资源子集、Secret/PVC identity 未漂移。唯一写操作是带 reviewed off values、exact image 和
`component=all` 的 `helm upgrade --no-hooks`；禁止 build/save/copy/transfer/import、provider、probe、promotion、collection
和 Job。写后必须证明紧邻的下一 revision 为 deployed、stored manifest/computed values 为完整 off release、tracked live Deployment/Service 精确一致、exact Ready Pod/image、sectors-off、CronJob/Job absent 及 Secret/PVC
identity 不变。任何其他 partial/drift 形态都在 Helm write 前拒绝。
exact Pod 环境比较只规范化 Kubernetes 1.26 API read-back 对 desired 显式空字符串的省略：仅当同名 live 项同时缺少
`value` 与 `valueFrom` 时补为 `value: ""` 再比较；非空值、Secret reference、变量集合和其他字段仍必须精确一致。

off-first 发布成功后，受审 real-probe envelope 另以文件 SHA-256 和 canonical capability checksum 冻结。生产 promotion
解析 exact Ready application Pod，证明它属于该 Deployment、运行冻结镜像、sectors 为关闭状态且两个 application
CronJob absent，再通过 `kubectl exec -i` 把报告流式送入 `capabilities promote --input -`。CLI 只使用 Pod 已注入的
`MARKET_ENVIRONMENT_DATABASE_URL` Secret 环境；控制端不得读取或导出数据库 URL，不得 `kubectl cp` 报告、在 Pod
落临时报告文件、使用 TTY 或通过 `sh -c` 二次解释。dry-run 与 apply 必须消费同一受审 envelope/checksum；promotion
本身不改变快照、任务、聚合、开关或调度。

匹配报告晋升后，enable 与 off rollback 统一走 same-frozen-image、hook-free config-only full-release rollout。该路径
不构建、保存、复制、传输或 import 镜像，不运行 migration/Helm hook/provider-backed Job；写入前比较 live/desired
packet，只允许 `MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED` 在 `"0"` 与 `"1"` 之间翻转，image、approved revision、
Secret、PVC、Service、topology、调度及其他环境值必须完全一致，写入前后都证明两个 CronJob absent。real probe 还必须
在构造任何 provider/client 和创建 JSON/SQLite 输出前校验上海当前有效日期、工作日和配置的 settlement time，没有
force 绕过；2026-10-09 的首次生产采集使用了当时存在、现已退役的
`snapshots scheduled-refresh --dataset sectors`，该命令只保留为历史审计事实，不得复制为当前操作。首次采集只在两条
Eastmoney 尝试失败后进入 Fuyao，并保留前序 warning。任一步失败都停止后续操作；需要回退时仅关闭 sectors 开关，
保留 capability report、同日快照、任务历史、Job、Secret 和 PVC，后续失败仍只允许同日
`failed-retained`/`failed-missing`。

扶摇行业结果通过上述门禁后，才允许在显式开关
`MARKET_ENVIRONMENT_EASTMONEY_SECTOR_ENRICHMENT_ENABLED=1` 下调用同供应商
`https://data.eastmoney.com/dataapi/bkzj/getbkzj`。请求固定使用
`key=f3,f6,f62,f104,f105,f128,f184` 和 `code=m:90+s:4`，经共享 `data.eastmoney.com`
host policy、单飞、短缓存、有限重试和按上海市场日隔离的缓存键。该接口没有可靠业务日期且使用
东方财富 `BK` 分类；只允许版本化映射或唯一严格规范化名称匹配，不能把 `BK` 代码当作 THS 代码，
也不能按排名或模糊名称连接。`f3`/`f184` 的整数化百分比必须先通过基准涨跌幅证据归一化，
口径不明、数值无效、重复名称或变动/成交额冲突时保持 `null`。

补充只填扶摇结果中原本为空的 `mainNet`、`mainNetPct`、`upCount`、`downCount` 和 `leader`，
不覆盖扶摇的代码、名称、涨跌幅或成交额；成功、部分匹配、跳过和失败都在 `quality.sectorEnrichment`
保留同供应商来源、请求字段、映射 revision、匹配/字段覆盖、百分比 scale、日期证据和 warning。
历史日期、上海结算前或缺少当前日期证据时零次 dataapi 调用。补充失败只降低质量并保留有效扶摇基础快照，
不改变正式 Eastmoney → Fuyao 回退顺序，不构成独立 provider 交叉确认；Tushare 当前 token 无相关
行业资金流/指数接口权限，因此不进入运行时路径。

### Fuyao THS 目录、量价历史与内部结构边界（2026-10-12，离线实现完成）

`add-fuyao-ths-sector-datasets` 的目标公共契约把兼容 `sectors` 拆为
`industry-ranking`、`sector-turnover` 和 `sector-breadth` 三个顶层数据集。旧 `sectors`
快照、任务和聚合行继续作为不可改写的审计证据保留，但新 API、TypeScript 契约、调度和 Chapter 01
不再投影或接受该标识，也不得把历史行重命名为任一新数据集。

目录层保存 Fuyao `industry`、`cn_concept`、`region`、`tszs` 四类 THS 编号，记录 `tag`、
`thscode`、名称、provider/fetch 时间、数量、checksum 和 revision。单个 tag 内编号必须唯一；同一编号跨
tag 出现时保留分类关系和共享代码身份，不按名称、排名或模糊匹配擅自合并。跨 revision 的新增、删除、
改名和跨 tag 冲突必须形成可审计差异，身份无法唯一证明时 fail closed，不能用旧目录或其他分类补齐。

#### THS 目录观察版本完整性边界（2026-10-14）

`capabilityRevision` 只标识已批准的 provider endpoint/schema/permission/request-budget 契约，不能再兼任
目录主键。四类目录必须先完成身份、重复项、跨 tag 名称和非空计数校验，再以完整、排序后的
`(tag, thscode, name)` 关系计算 canonical SHA-256 `catalogChecksum`；每日行情为空不得裁剪关系或改变
checksum。目录观察身份 `catalogRevisionId` 由 `provider + capabilityRevision + 上海交易日 + 完整
catalogChecksum` 确定，provider/fetch timestamp 不参与身份，因此同日同内容重试幂等、同日内容变化可
并存、跨日同内容仍保持独立血缘。该值对 HTTP 客户端是 opaque string。

快照身份集合必须与目录唯一代码集合精确一致，重复、额外、缺失或无法证明精确日期继续 fail closed；
身份和日期有效后，值可用性独立分类。OHLC/volume/turnover 六项全空的代码进入 `missingLiveCodes`，不创建
`ThsSectorBar`；`changePct` 为空的代码进入 `missingRankingCodes`，仍保留完整 ranking relation，并以
`quality=insufficient` 和行级 warning 排在可排名行之后。两类缺口可重叠，也可分别出现；任何缺失值保持
`null`，不得补零。原子提交必须证明 ranking keys 等于完整目录关系，且唯一代码满足
`barCodes ∪ missingLiveCodes = catalogCodes`、两集合不相交。

同一日期存在多个目录观察时，隐式精确日期读取只按 `provider_timestamp DESC, fetched_at DESC,
revision_id DESC` 选择一个最新兼容 revision；显式 revision 读取只返回指定版本，禁止跨 revision 合并。
排名、量价、宽度、Chapter 01 和依赖 DAG 必须传播同一 `catalogRevisionId`。本修复在 PostgreSQL schema
version 10 / Alembic `0007_ths_catalog_identity` 中仅删除不含交易日的
`UNIQUE (provider, capability_revision, checksum, fetched_at)`；保留 `(revision_id, provider)` 不可变身份，
不更新或删除旧 fixed revision、旧成功事实及失败/blocked 审计。任务 warning 使用有界 `THS_DIAGNOSTIC_V1` 兼容封装；旧
纯文本或格式错误内容原样回退，诊断不得包含凭据、签名 URL、敏感 header 或 raw provider payload。

三个数据集的职责和依赖固定如下：

- `industry-ranking` 从四类完整目录和同一上海交易日的完整快照身份集合生成稳定分类排名；目录、编号
  身份、日期或 100% 身份覆盖任一不足时不发布正式结果。身份有效但值为空属于可审计 partial，不删除目录
  关系。当 provider 快照行确实缺少 `changePct`（如真实
  `883401.TI` 在 `/api/a-share-index/prices/snapshot` 不返回任何日涨跌幅 alias）时，adapter
  把缺失按行级 warning 透传，`ThsRankingRow.change_pct` 允许 `null`，排序键在该 tag 内把
  `None` 行排到末尾而非拒绝整份快照。capability policy 接受 partial 的两条独立证据门：
  `changePctCoverage >= 0.99` 且 `changePctMissingTags` 为空（即四个 tag 都至少有非空
  `change_pct`），任何 tag 整列缺失仍记 `ineligible`；committer/collector 接受 `changePct=null`
  行落库，质量仍按现有规则标记为 `partial`，前端 `ThsIndustryRankingRow.changePct` 类型同步为
  `number | null`。PostgreSQL migration `0006_ths_ranking_nullable_change_pct` 将
  `ths_industry_rankings.change_pct` 明确设为 nullable，禁止用 0 替代缺失值。重复 collection
  复用同一 catalog revision 时只比较 checksum、provider、capability revision 和 tag counts；provider
  每次抓取变化的 `provider_timestamp`/`fetched_at` 属于观察元数据，不得被误报为 revision 冲突。
  `missingRankingCodes` 与行级质量；OHLC/volume/turnover 六项全空的行进入 `missingLiveCodes` 且不生成
  全空 bar。catalog identity 门禁不变，缺失值保持 `null`。
- `sector-turnover` 保存逐 `thscode` 日线的 `open`、`high`、`low`、`close`、`volume` 和
  `turnover`。每日快照只追加已证明至少一个 bar 字段的编号，并报告 expected/bar/missing coverage；
  声明的 live-value 缺口使结果为 partial 而非 dependency-blocked。历史接口按单编号请求；产品回填窗口最多近五年，每批最多
  60 个编号，以 checkpoint 记录编号、日期区间、revision、预算消耗和完成状态。重试必须幂等且可恢复，
  不得用空值、零值、其他日期或较低质量响应覆盖已验证事实。
- `sector-breadth` 只计算当日四类 Top 10 与用户点选编号的内部结构。成员和个股事实以 Fuyao 全市场日 K、
  最近 10 日增量和复权因子 dump 为主，TDX 精确日期盘后事实为降级；不足或混合来源必须保留质量与
  lineage，禁止用当前成员回算历史宽度。

current membership 由显式 `catalog-sync` 在 provider I/O 前同时解析 `industry-ranking` 与
`sector-membership` 两个 exact capability revisions，并按 capability 中的目录规模/四类计数为 snapshot
分片、每类 Top 10 和显式点选编号预留总预算。目录和当日日线先事务提交；去重后的成员编号随后逐编号独立
提交，单编号失败只令 operation 为 `partial`，不得回滚目录或已成功兄弟 membership。membership 开关与
revision 独立于 catalog，默认关闭/空值。

执行依赖为 `industry-ranking -> sector-turnover -> sector-breadth`。同日期、同 revision 的 compatible partial
可继续执行：turnover 只消费 proven bars，breadth 先排除 `changePct=null` 或不可排名质量行；任一 tag 的有效
候选少于配置 Top N 时返回该 tag 的 `insufficient` 计数，不把短列表包装为完整结果。真正的身份/日期失败、
revision 不匹配或无兼容前置结果继续 blocked/insufficient；已经成功的兄弟任务和同日期结果不得被抹除。
每个新数据集首次成功或 accepted partial 提交后均可触发 Chapter 01 原子重建；
聚合删除旧 `sectors` 字段，新增 `industryRanking`、`sectorTurnover`、`sectorBreadth`，并把申万一级结果
保留在独立 `sectorAnalysis`。THS 行业、概念、区域和特色指数 observation 不得进入申万一级
`QTS-01-05-*` 规则输入，也不得改变 `core` 五指数、申万 taxonomy/membership 或 continuity backfill。

普通目录、K 线、回填进度、任务状态和 Chapter 01 GET 只读本地 PostgreSQL，必须保持 provider-free。
目录同步、单编号历史回填、dump 导入和任何 provider 请求只能从显式 CLI 或受保护的 POST 入口触发，并在
发起网络或正式写入前通过盘后时间、调用授权、capability revision 和请求预算门禁。默认 dry-run 为零网络、
零正式写入；真实 provider probe、生产 migration、首次生产同步/回填、部署和调度激活仍需分别授权。
real-probe 的 dump 证据按官方 schema 检验；daily/incremental 使用 `thscode`、`date_ms` 与 `*_price` 字段，
adjustment 仅提供公司行动事件项。后者在复权公式和前收盘证据未冻结前保持 `ineligible`，不能把 synthetic
`adjustment_factor` fixture 晋升为生产能力。

### 统一 provider 请求层边界（2026-10-08，已完成）

腾讯、百度、新浪、Eastmoney、TDX HTTP 包/名称查询、行业 enrichment 和两个 Fuyao 客户端已统一进入 composition root 创建的 engine-neutral policy gateway；兼容 provider 只保留 transport 层创建的可注入 session fixture seam，架构门禁不再允许这些模块直接构造或调用 `requests`。非 HTTP mootdx/TCP 行为不变。Fuyao API-key 零 I/O 门禁与 HTTP 200 business-code 语义保留在 adapter，raw HTTP attempt、408/429/5xx retry 和进程级预算归 gateway；401/403 不重试，HTTP 错误只向 adapter 暴露有界且脱敏的 `code`、`message`、`request_id` 证据，因此不会同时受两套 transport retry/limiter 控制。

gateway 只负责传输可靠性和请求压力控制，不改变 provider 字段契约、日期证据、降级顺序或 feature flag。它按 host 执行最小间隔、抖动、并发门、请求预算、single-flight、成功短缓存、`Retry-After`、cooldown 与 half-open 探测；连接/读取异常、408、429、5xx 才允许在同一预算内有界重试。engine 接收 engine-neutral request 并只执行一次，返回 normalized status/headers/body/final URL/timing 或 classified failure；provider validator 不导入 `requests.Response` 或 Scrapling 原生类型。

缓存与 single-flight identity 包含 engine、规范 URL、完整参数、精确请求日期和不可逆 authentication/tenant-scope digest。401/403、其他 permission failure、CAPTCHA/interstitial challenge 与响应日期/契约错误快速失败，不重试、不自动换 engine。日志和持久证据不保存 credential、Authorization、Cookie、proxy material、secret query、原始 challenge page 或敏感 body。

该 gateway 的 host policy 是单进程共享，不是 Dashboard/自动化 HTTP/维护 CLI/多 Pod 的分布式限流；跨触发器只由 PostgreSQL dataset/date lease 防止重复采集。失败仍由 acquisition/coordinator 输出真实 `failed`、`degraded`、`insufficient`、`failed-retained` 或 `failed-missing`，不得用零值、其他日期或更宽松 engine 替代。
# 大成交额主动进攻方向工作台边界（2026-10-21）

active-direction 采集在通过既有字段、样本数和成交额非递增校验后，保留前 30 行 `researchRows`，并将前 10 行投影到兼容的 `topStocks`。研究行可携带证券 identity、原始方向 observation、排序/来源 revision、行业映射 revision/coverage 和行级质量；新增字段为可选，旧 JSON 无需迁移即可读取。

工作台由同一精确日期 materialized aggregate 的可选 `activeDirectionWorkbench` 组件提供。组件在本地事实 revision 上组合方向观察/规范映射、Top-30、已存历史、涨跌停与事件事实，并通过 `/api/v2/market-environment/{as_of}/active-direction/workbench` provider-free 读取。普通 GET 不调用 provider、不启动 collection/background task、不回填或写 PostgreSQL，也不以其他日期补齐；revision 冲突必须在读取混合数据前失败。工作台失败按模块隔离为 `partial`/`missing`/`insufficient`，不得擦除有效 active-direction 或阻断其他 aggregate component。

工作台现在还投影两类已有本地事实：active-direction 行中的 PE/PB、市值、换手率和阶段涨跌幅作为 `fundamentals.items[].metrics` 原始估值观察；limits `securityDetails` 中的首封/末封时间、开板次数、封单和换手作为 `candidatePools.firstToSecond.intraday`。这些字段保留来源和日期，不产生 QTS 分数。集合竞价字段（竞价涨跌幅、竞价金额、未匹配量、同题材竞价宽度）以及利润/成长/现金流/杠杆/可比行业财务事实仍按字段级 `pending`/`missing` 返回，禁止用行情快照冒充财务报表或分钟序列。

跨数据集关联只允许规范证券 identity 与请求日期有效的版本化 sector mapping；原始 provider 标签保留为 observation，无法映射时不得晋级 canonical candidate。QTS-04 规则证据从 trading-rules 注册表接入，当前只输出原始 trace、缺口、否决、确认/失效提示，状态保持 `documented-only` / `needs-backtest`，不在 market-environment 内复制阈值或生成角色/交易信号。

回滚顺序为先回滚前端五视图，再停用工作台 endpoint/materializer；保留 `topStocks`、`researchRows`、旧聚合、PostgreSQL 历史和 task 记录，不删除数据、不执行自动回填。该变更不新增 CronJob、调度或生产写路径。
