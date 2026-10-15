# 第 01 章市场环境看板

## Status

`active` · 版本 `0.17`

后端分层重构的实现状态：普通查询、状态和 next-session 读取已切换到 provider-free application query boundary；正式运行时存储为 PostgreSQL，SQLite 仅用于停写迁移/测试输入；旧 `service.py`、`providers.py`、`snapshot_store.py` 仅保留稳定导入 shim，实际 legacy 实现位于 `infrastructure/legacy/`。项目内 Kubernetes 定时采集正在退役，仓库不得再创建或激活 application-owned CronJob；盘后时钟与结果投递由 `192.168.1.21` 上的 Hermes Agent 持有，后端自动化写入口保持独立且默认关闭。

采集适配器统一已完成；本版本将公共采集集合由五项迁移为 `core`、`breadth`、`limits`、`industry-ranking`、`sector-turnover`、`sector-breadth`、`activeDirection` 七项。各数据集统一消费 typed `CollectionOutcome`，provider 差异由 dataset acquisition plan 与 source adapter 隔离，task/lease/同日留存/提交/聚合由 coordinator 和 typed committer 统一处理。`requests` 保持默认 HTTP engine；可选 Scrapling static engine 默认不安装、不启用且 host/source allowlist 为空，不构成生产数据源批准。

## 目标

把 `搭建交易系统/01-如何判断市场环境/` 与量化版对应文档中的盘后判断拆成可重复读取、带数据质量说明且可追溯到规则范围的网页证据，避免把主观描述或缺失数据包装成确定结论。

页面布局、组件、字体、颜色、图表、状态和响应式实现统一遵循 [`market-environment-dashboard-design-guidelines.md`](market-environment-dashboard-design-guidelines.md)。

## 用户与流程

- 盘后研究者选择交易日，从一级导航 `如何判断市场环境` 进入 01 至 09 的二级文档视图。
- 页面依次查看指数结构、市场广度、涨跌停生态、分层亏钱效应、行业主线、容量方向、事件、环境归类和综合判断。
- 首屏先展示指数结构；扩展章节证据按当前二级文档需要加载，切换页面不应被未访问数据集阻塞。
- 每个数据集同时展示来源、状态和 warning；缺失或未核实证据保持 `null` / `insufficient` / `unverified`。
- 日期时间统一按生效时区显示本地日期、时间和 UTC 偏移，悬停可查看原始 UTC ISO8601；解析优先级为个人偏好、工作区偏好、浏览器 IANA 时区，均不可用时显式显示 UTC。数据采集页“最近尝试”是市场运行审计字段，固定使用 `Asia/Shanghai`，不随浏览器或个人时区切换。偏好设置页支持 IANA 时区选择、持久化以及无效值、权限不足、离线和接口失败状态。
- 开发阶段通过独立的 `/data-collection` 数据管理页查看精确日期的七类数据状态，可单项重新采集或一键采集全部数据；`industry-ranking`、`sector-turnover`、`sector-breadth` 使用三个独立任务卡，历史回填和成员事实导入另列 operation 进度，不伪装成普通每日重试。普通研究页面不承担自动采集职责；第 05 页仅可通过明确操作发起板块历史回填。
- 数据采集页首次打开时由后端按上海时区解析有效市场日：开市前（09:30 前）选择上一工作日对应的真实交易日并跳过周末；节假日或实际日期无证据时返回 `insufficient`/拒绝，provider 返回的实际日期必须与目标日期一致；开市后才选择上海当天。这样不会把尚未开始的当日误标为已完成，也不会把上一交易日行情伪装成当天；用户手工选择历史日期后仍严格展示 provider 日期限制。
- 已确认的盘前误标必须显式选择后端：生产运行时只允许在受控停写窗口对目标 PostgreSQL 使用 `snapshots relabel-date --database-url ...`，先 dry-run 再显式 `--apply`；隔离 SQLite 副本仅用于迁移/回归演练。流程同步快照、任务、涨跌停事实与聚合，校验 checksum/目标冲突并留下可回滚审计，不允许普通采集路径自动跨日期改名、静默回退 SQLite 或覆盖目标日期已有成功值。
- Hermes 在明确配置的 `Asia/Shanghai` 时区于工作日 16:30 调用 `POST /api/market-environment/collection-runs/full`；后端不接受客户端指定日期或数据集，固定执行七项 canonical collection。自动化与手工采集共享同一 task、lease、快照和失败隔离模型，结果继续在 `/data-collection` 查看和补采；17:00 后不为遗漏时隙补跑。

## 范围

- 五大指数的趋势、均线、区间位置、成交额和量价结构；指数卡同时展示 5 日成交额比值与明确命中的量价状态，收盘指数值与右侧涨跌幅可分别复制且不触发指数切换，60 日历史使用真实开盘、最高、最低、收盘数据展示 K 线，并叠加 MA5/10/20/60。
- 五态 `syncPattern` 只描述五指数当日涨跌关系；独立的 `synchronizationAssessment` 使用市场广度、至少三个指数相对 MA20 的位置和指数成交额确认该模式，输出 `confirmed`、`unconfirmed`、`contradicted` 或 `insufficient`，不得用确认结果反写原始模式。
- 同步上涨只有在上涨占比不低于 55% 且涨跌幅中位数大于 0 时才形成普遍性确认；权重护盘只有在上涨占比不高于 45% 且中位数小于 0 时才可描述为“指数偏强、个股偏弱”；成长占优还要求创业板指和中证500的 5 日成交额比值中位数不低于 1.0；系统性下降必须同时满足弱广度、至少三个指数位于 MA20 下方和至少三个指数放量下跌。
- “上涨家数和中位数改善”只使用指数历史识别出的精确上一交易日广度快照计算；精确快照缺失时不得用更早日期替代，普通 GET 不得因此访问 provider，当前日判断可以保留但置信度最高为中。
- 第 01 页实现“指数、位置和成交额结合判断”：展示所选指数命中的六类典型组合、触发证据和交易模式，并汇总市场强弱、阶段、资金认可和交易模式四项输出。
- 当前交易日的全 A 上涨/下跌/平盘数量、上涨占比和涨跌幅中位数。
- 日期化涨停、跌停、炸板与最高连板生态。
- THS 行业、概念、区域和特色指数的完整目录、当日排名、板块量价与当日内部宽度；这些内容仅属于 provider observation，不以名称相似性映射为申万一级身份，也不进入 `QTS-01-05-*` 输入。
- 历史 Eastmoney-first/Fuyao-fallback `sectors` 契约从公共 API、调度、前端和新采集任务中退役。既有快照、任务、warning、checksum 和 capability report 原样保留为审计证据，不删除、不改名，也不投影成任一新数据集。
- `core` 的 Fuyao v2 主源只在 `fuyao-market-v2` capability report 获批并显式启用后生效，使用指数历史接口逐一获取五个指数；失败时依次回退 mootdx、百度、Sina、腾讯历史，最后才到东方财富。当前日期需要独立腾讯报价交叉校验，历史日期不请求实时价格；缺少指数、OHLC、成交额、280 根历史或精确 `date_ms` 时保持 `partial`/`insufficient`。
- `breadth` 的 Fuyao v2 主源只允许当前上海交易日的 `/api/a-share/prices/snapshot` 完整分页；所有页的 `total`、`timestamp` 和规范证券身份必须稳定，涨跌家数、平盘和中位数由 `price_change_ratio_pct` 派生。Fuyao 失败后才按显式开关使用 TDX 精确日期包，最终回退东方财富；历史日期只能读取本地精确快照，不能用 latest-only 响应回填。
- `activeDirection` 本阶段不由 Fuyao 替换，继续使用现有东方财富/TDX 语义；Fuyao capability 仅记录为 `unverified`，不得把旧 `fuyao-market-v1` 报告当成切换批准。limits 继续使用扶摇主源与东方财富交叉核对/降级。
- 01 至 09 文档导航、桌面与移动布局、数据加载和错误状态。
- `chapter01` 作为原 `indices` / `summary` 契约的可选向后兼容扩展。
- 完整聚合接口继续兼容既有调用；网页使用核心接口和章节按需接口渐进展示数据。
- 市场广度和容量方向按交易日持久化并可在盘后预计算；服务重启或同机 worker 切换后仍可复用精确日期快照。
- 数据质量允许附加缓存状态、快照抓取时间、后台刷新状态和刷新 warning；陈旧快照必须显式标记，不能伪装为刚获取的数据。
- 数据采集页覆盖核心指数、市场广度、涨跌停生态、行业排名、板块量价、板块宽度和容量方向，并分别展示当前可用状态与最近采集结果；核心指数可展开查看五个指数子项。
- 数据采集页从本地状态读取并显示容量方向的 `tdx-daily-package-derived` 来源、本地排序和行业映射覆盖率；`fallback-derived` 标记为本地派生降级，不能被显示为普通成功。
- 每个数据集独立保存成功结果，一键采集中的单项失败不得停止或回滚其他数据集；失败时保留同日期最后一次成功快照并标记刷新错误。
- 七个数据集对 application 暴露同一个 `collect(DatasetDate) -> CollectionOutcome` 产品契约；业务流程只消费 normalized candidate/failure/evidence，不根据 Eastmoney、Fuyao、TDX、requests 或 Scrapling 类型分支。数据源优先级、日期能力、fallback、shadow 和 enrichment 由可审计 acquisition plan 决定，不能由 UI、coordinator 或 transport engine 临时改序。
- source attempt 必须展示真实来源、revision、requested/actual date、fetch time、field availability、timings、分类失败和脱敏 provenance。shadow 不改变正式结果；同供应商 enrichment 不得显示为独立确认；成功缺少 candidate 或身份时必须 fail closed。
- 手工采集写操作在本地开发默认开启，可通过 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` 显式关闭；无应用认证且 NodePort 可路由的生产部署必须保持该开关关闭。新的全量自动化端点由默认关闭的 `MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED` 独立控制；生产可以只开启 automation 而保持 manual=0。负责人已接受固定 `NodePort:32001` 上该 automation 端点的内网匿名边界：所有能路由到 `192.168.1.20:32001` 的客户端均可触发七数据集 provider 调用和 PostgreSQL 写入；NodePort、CORS、幂等 key、前端按钮和 lease 都不提供身份认证或客户端授权，且不得对公网转发。
- 东方财富采集在单进程内全局串行执行；瞬态连接/读取错误、429 和 5xx 有界重试，403 不盲目重试。行业、涨跌停池与容量方向主域失败或返回无效载荷后允许降级到兼容延迟域，并保留实际来源、每个子请求的错误和降级 warning；容量方向的两个来源必须执行相同的必需字段、最小样本和成交额排序校验。两条 Eastmoney 路径均失败后，只有 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED=1` 才允许使用精确日期 TDX 包本地派生容量方向，质量显示为 `fallback-derived`，记录本地成交额排序、TDX revision、行业映射覆盖率和前序 warning；该开关独立于 breadth 的 `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED`，默认关闭。涨跌停池的日期证据优先使用响应中的实际日期；`push2ex` 省略顶层日期但请求包含明确 `date` 时，可记录 `dateEvidence=request-parameter` 绑定该请求日期，并继续校验所有显式行日期，出现冲突仍拒绝 V1 完整事实。
- 所有 HTTP source adapter 共用一个进程内 transport policy gateway；gateway 统一 host 限速、预算、重试、single-flight、缓存和熔断，engine 只执行一个已授权 attempt。请求身份必须隔离 engine、精确日期、完整参数和认证/tenant scope，且诊断不得泄露 credential、Cookie、proxy 或 challenge body。
- 可选 Scrapling 仅提供静态 HTTP engine：默认关闭、空 allowlist、独立依赖/镜像，不启用 Spider、浏览器、Chromium、代理轮换、内部重试、blocked-request escalation 或 challenge solving；401/403/CAPTCHA 不得触发 requests 到 Scrapling 的自动升级。是否为某个真实 host 启用必须由后续证据和独立 rollout 批准。
- Fuyao THS 的 catalog/snapshot、单编号历史和 dump/复权分别使用独立 capability policy；任一操作只有在 exact revision `eligible`、对应开关开启、权限和请求预算有效且上海盘后日期门禁通过后才能构造 provider client。旧 `fuyao/sectors/fuyao-market-v2` 报告不能授权新的历史或 dump 操作。
- capability report 从隔离 probe 进入正式运行时只能通过通用 `capabilities promote` 边界：显式选择 provider/dataset/revision，校验原始 checksum、`eligible`、脱敏一致性和数据集证据策略，默认 dry-run；只有显式 `--apply` 才在运行时 PostgreSQL 的单个事务中写入一条报告。同 checksum 重复操作幂等，同 revision 不同 checksum 冲突拒绝；该命令不得调用 provider、触发采集、写快照/聚合、修改 Secret、调度或任何 provider 开关。
- 新能力的隔离 probe、capability promotion、生产迁移、首次目录同步、历史回填、dump 导入和部署均不属于默认实现写操作，必须在上海盘后取得再次明确授权。回滚只关闭新 provider 开关和写入口，保留新旧 evidence、additive 表、任务、Secret 与 PVC，不恢复旧 `sectors` 公共采集器。
- 涨跌停生态以扶摇三类日期化股票池为主源、东方财富为降级与交叉核对源；交易日历确认请求日期后允许记录 `dateEvidence=request-parameter`，分页总数、规范身份或显式日期冲突任一不完整时不得写成成功集合。两源集合不一致时按规范身份取并集，扶摇字段优先，东方财富独有行和整日质量标记 `degraded` 并保留 warning。
- 盘后自动采集由 Hermes 经内网 HTTP 调用 Dashboard service，使用与 Dashboard 相同的后端进程、PostgreSQL Service/Secret、task、lease 和 snapshot；Hermes 不获得数据库凭据、PVC、provider 凭据、CLI 或部署权限，也不复用只生成交易规则 Artifact 的 GitHub Actions workflow。
- full endpoint 要求 `Idempotency-Key`。同 key 与同语义（服务端日期、operation version、固定七数据集 fingerprint）跨超时、断线、202 和进程重启复用同一 persisted run；wait timeout 不属于语义，相同 key 的语义冲突返回 409。900 秒内 terminal 返回 HTTP 200；仍运行返回 202、`Location`、`Retry-After` 与 provider-free `statusUrl`，断开客户端不取消任务。
- 每项结果持久化 nullable `failure {category,message,retryable,retained}`。`failed-retained` 只能表示本次失败且保留同日旧成功数据，不得计入本次成功；`failed-missing`、`blocked/dependency`、`busy/concurrency` 和 worker interruption 保持独立分类。单项失败不停止无关数据集，terminal 全失败仍以 HTTP 200 返回完整业务结果。
- Helm/Kustomize/TrueNAS render 不再包含 application CronJob，也不暴露 schedule component、suspend/activate/disable 模式或 `scheduledCollection` values。普通部署在首个目标写入前后都以 `a-stock-data-collection` 和 `market-data-collection` 两个旧 identity 检查 stored/live 状态；任一 active 或 suspended 遗留资源存在即 fail closed，处置需要独立审核，不能通过普通部署恢复或修改。
- 周末 full endpoint 应无 run/provider 写并返回 `skipped`；第一版不维护交易所节假日日历，工作日节假日仍可触发，但不得把上一交易日数据写成当天快照。

### Fuyao THS 三数据集产品边界

- `industry-ranking` 维护 `industry`、`cn_concept`、`region`、`tszs` 四类版本化目录。固定 `capabilityRevision` 只表示已批准的接口/schema/权限/预算，不是目录主键；`catalogRevisionId` 必须由 provider、capability revision、上海交易日和完整四类 `(tag, thscode, name)` canonical checksum 确定，且在每日行情对账前计算。每个 observation revision 保存完整分类数量、checksum 与 provider/fetch 时间；时间戳不参与身份，同一 `thscode` 跨分类时共享行情事实，但各分类关系必须独立可查。
- 当日排名必须以完整四类目录和身份集合完全匹配的批量指数快照为输入，证明上海交易日、唯一代码和 100% 身份覆盖后，按可用 `changePct desc, thscode asc` 稳定排序；`changePct=null` 行保留在分类关系末尾并标为不可排名，不得进入 breadth Top-N。重复/额外/缺失身份、名称冲突或混合日期仍 fail closed；身份与日期有效但市场字段为空时保留 relation，以 `partial`、`null`、行级质量、`missingLiveCodes` 和 `missingRankingCodes` 表达，不得裁剪目录或补零。
- `sector-turnover` 按 `thscode` 和真实交易日保存已证明的 `open`、`high`、`low`、`close`、`volume`、`turnover`、来源、质量和 `catalogRevisionId`；成交量与成交额必须分列，缺失保持 `null`，禁止相互代替或使用 0 补齐。每日任务只为至少一个 bar 字段可用的代码创建事实；六项全空的代码进入 `missingLiveCodes`。页面展示 expected/bar/missing coverage，同一编号跨分类只存一份行情。
- 单编号历史最多查询近五年本地日线。覆盖不足时，只显示已有首尾日期和缺口；用户可显式发起回填。每个回填 run 默认最多 60 个唯一编号，按代码与时间窗口保存 checkpoint 和请求预算；单编号失败只影响对应 checkpoint，续跑只处理未完成窗口，已验证同 checksum 数据幂等保留，不同 checksum/revision 形成可审计冲突而不静默覆盖。
- `sector-breadth` 只计算当前已完成上海交易日，从与 ranking/turnover 相同的单一 catalog revision 中排除 `changePct=null` 或质量不可排名行，再为每类选择稳定 Top 10 并合并有效用户点选编号；任一分类有效候选不足 10 时显示该分类 valid/required 计数和 `insufficient`，不得把短列表包装为完整 Top 10。重复选择只计算一次且保留全部选择来源。每个板块输出成员总数/有效数、涨跌平家数、上涨占比、涨跌家数差率、中位涨幅、`close > MA20` 宽度、涨跌停数量、Top 成交、Top 涨幅、单股最大成交贡献和扩散率，并保留每项分子、分母、缺失原因与字段 lineage。
- 板块成员事实以 Fuyao 全市场日 K、最近 10 日增量和复权因子 dump 为主源；TDX 只可对精确日期的盘后原始事实做字段级降级补充。复权只作用于价格，原始成交量和成交额不复权；Fuyao dump、复权因子、成员或字段覆盖不足时输出 `partial` / `insufficient`，混合来源标记 `degraded` 并逐字段记录 lineage。MA20 不足的成员从对应分母排除，limits 缺失只降低涨跌停指标，不得污染独立有效的宽度指标。
- 历史板块宽度不属于本版本。没有精确日期 point-in-time membership 时，系统必须拒绝历史 `sector-breadth`，不得用当前成员回算过去日期。
- 三个每日任务按 `industry-ranking -> sector-turnover -> sector-breadth` 执行。同日期、同 `catalogRevisionId` 且仅含已声明值缺口的 compatible partial 可继续驱动下游；身份/日期错误、revision 不匹配或有效 Top-N 候选不足时才显示精确 `blocked` / `insufficient`。独立数据集和已成功兄弟任务继续提交；任一新任务成功或 accepted partial 后都必须重建并原子替换 Chapter 01 聚合，避免只保存快照而章节缺失。
- Chapter 01 新公共字段为 `industryRanking`、`sectorTurnover`、`sectorBreadth` 和独立的 `sectorAnalysis`，新响应不再包含 `sectors`。显式请求旧 dataset ID `sectors` 返回稳定的不支持错误，并列出三个迁移目标；请求不得调用旧 collector 或改写历史 evidence。
- provider-free GET 只读本地 PostgreSQL：目录查询支持分类、名称/编号搜索、revision 和分页；单编号 K 线支持日期范围、分页、本地覆盖与缺口；operation 进度查询展示目录同步、回填和成员导入的 run/checkpoint 状态。上述 GET 在本地缺失时仍不得构造 provider client、自动回填或下载 dump。
- 目录同步、当日采集、历史回填和成员事实导入只允许通过显式 POST/CLI 触发，并继续受 manual-write、上海盘后、权限、请求预算、enabled switch 和 exact capability revision 门禁控制。预签名 URL、API key、敏感 header 和原始 provider 响应不得持久化或输出。
- 数据管理页对 THS 任务显示 expected/usable/bar/rankable coverage、有界 missing code 样本、稳定 `reasonCode`、`blockedBy` 上游状态和 opaque `catalogRevisionId`；旧纯文本 warning 仍可显示。第 05 页保留 all-null 或 `changePct` 缺失的目录行，数字继续为 `null` 并标注“当日行情缺失”或“部分排名”，但不可排名行不进入任何 Top-N。新增可见文字不小于 14px，桌面和 390px 宽度不得产生页面级横向溢出。

### 第 03 页涨跌停生态完整矩阵

第 01 章第 03 页“涨停、跌停、炸板和连板晋级”采用证据优先顺序。以下内容是页面必须对齐的产品矩阵；每一行都要带实际交易日、来源、抓取时间、观察数、`quality.status`、缓存状态和 warning。前端只格式化后端字段，不从分子/分母补算业务指标。

| 证据层 | 页面内容 | 数据口径与不足语义 |
|---|---|---|
| 证据条 | `asOf`、实际/样本日期、来源、抓取时间、observations、cache state、quality、warning | 只接受精确交易日；缺失显示 `missing` / `insufficient`，不得用其他日期或零值回填 |
| 当日事实 | 涨停家数、跌停家数、炸板数、炸板率、最高连板 | 继续兼容旧五字段 `limitUpCount`、`limitDownCount`、`failedLimitUpCount`、`failedLimitUpRatio`、`maxStreak`；只有 provider 明确返回空池时计数才可为 0 |
| 晋级证据 | 今日晋级数、昨日涨停样本数、晋级率、当前/前一相邻交易日、样本规则与固定版本 | 分母为前一真实交易日完整涨停成员集合，分子为与当日完整涨停集合的规范身份交集；ST、上市窗口、制度和板块不从基础分母删除；20/8 返回 `0.4`，分母为 0 时比例必须为 `null` 且质量为 `insufficient` |
| 证券事实、梯队与明细 | 首板、二板、三板、四板以上；涨停/跌停/炸板/晋级四组明细；交易所、ST、新股窗口、制度和板块分层 | 集合、连板字段和高级属性分别表达完整度；高级属性缺失只降低对应分层，不能阻断已证明的基础集合、晋级、梯队和明细 |
| 历史与风险 | 最近 6 个真实交易日形成最近 5 个带晋级率的历史点；连续跌停、断板/修复、板块集中、昨日强势股次日反馈 | 缺失交易日不替代；少于 60 个有效观测时 250 日分位及其周期结论为 `insufficient`，展示有效数和缺口 |
| 规则证据 | `QTS-01-03-01` 至 `QTS-01-03-05` 的输入、经验分位、分项/总状态、置信度、风险否决、触发/缺失/确认/失效条件 | 规则 ID、权重和 `needs-backtest` 不变；即使输入完整也只能标注“经验阈值 · 待回测”，不输出 `validated` 或自动交易建议 |

本页必须覆盖 `ready`、`partial`、`refreshing`、`missing`、`failed-retained`、`failed-missing`、`degraded` 和 `insufficient` 状态。刷新失败时保留同日期最后一次成功证据并标记刷新 warning；没有保留值才显示 `failed-missing`。普通 GET 只读取本地快照/materialized aggregate，provider 调用数必须为 0。

### 第 03 页数据与发布边界

- limits detail/V1 写入开关 `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED` 默认关闭；关闭时旧五字段路径和本地快照继续可读，开启前须通过 Alembic 迁移、幂等、lease/CAS、provider-free GET、失败保留和前端状态验证。
- 基础集合必须证明交易日、完整分页和规范证券身份；高级 ST、上市窗口、制度与板块字段按分层独立校验。日期冲突、非交易日、无效身份或池无法完整解析时拒绝 membership 完整事实，但高级字段缺失不得阻断基础晋级。
- 当前日与前一日由精确交易日历确定，不使用自然日减一、跨日期回填或浏览器端重新抓取。显式 `--history-sessions 6` 按升序采集六个真实交易日并生成五个晋级点；失败采集只记录审计 warning，不覆盖成功快照。
- 真实 provider smoke 仅在显式授权的隔离 PostgreSQL 和盘后命令执行，密钥通过 Secret/环境注入，记录来源、六日日期、集合差异、checksum 和质量；证明不足时保持 `failed` / `degraded` / `insufficient`，不改变规则校准状态。
- 回滚顺序为先关闭 limits detail/V1 写入，再恢复应用版本；保留 PVC、旧聚合、`trading_sessions`、`limit_security_facts` 和校验和，不删除数据库或用其他日期替代。

不包含自动下单、主体意图推断、未经来源核实的事件评分，也不宣称经验阈值已经通过 500 至 750 个交易日回测。第 04 页可以展示 limits 中可追溯的高/中/低位样本数量和炸板修复率；未形成独立亏钱收益样本的规则仍保持 `unverified` / `insufficient`。

## 第 05 页：THS 板块观察与申万一级持续性（规划范围）

第 05 页使用紧凑 tab 呈现“排名、板块宽度、量价 K 线、申万持续性”四个独立视图，并保持两种互不替代的证据层：

- **provider observation**：排名视图按四类目录筛选并支持名称/编号搜索，保留 THS provider 身份、revision、精确观察日期、来源、抓取时间、质量和 warning；板块宽度视图展示当日公式证据、成员覆盖、Top 成交和 Top 涨幅；量价 K 线视图按单一 `thscode` 展示蜡烛图、成交量和成交额。provider 代码或名称不得直接当作申万行业身份；只有经过请求日期有效的、版本化且唯一的 mapping 才能建立关联。
- **Shenwan canonical analysis**：只使用申万一级 taxonomy、请求日期生效的 membership、普通 A 股 universe、原始成交额、前复权价格和等权基准。概念、题材、重叠行业和当前成分股不得进入分析。分析结果通过 `SectorEvidence.analysis` 作为可选扩展返回，旧的 `rows/state/quality` observation payload 继续有效。

量价 K 线只展示本地 PostgreSQL 已覆盖日期，蜡烛、成交量和成交额共享稳定时间轴但保持独立数值轴与 tooltip。请求区间存在缺口时页面显示实际首尾日期、缺失窗口和质量，不自动访问 provider；用户可通过明确操作发起受门禁的历史回填，并在独立 operation 区域查看 checkpoint 进度、失败编号和可重试窗口。

分析固定生成五项规则证据，并保留原始值、分位、规则输入、样本日期、公式、版本和质量：

1. 5/20 日行业相对强度：行业同期收益减去 `ordinary-a-share-equal-weight-v1` 基准；两窗均有效后取较低 midrank 分位。
2. 近 5 个有效交易日成交额位于完整申万一级横截面前 20% 的天数；并列按稳定行业 ID 裁决，输出 0–5 天。
3. 有效成员中前复权 `close > MA20` 的比例及滚动分位；零分母保持 `null`。
4. 负收益分歧事件及两日内成熟承接：后续任一完整交易日收复下跌幅度至少 50% 才算修复；未成熟事件不进入分母。
5. 申万一级行业前五成交额集中度：按原始成交额和稳定行业 ID 取 `min(5,N)`，除以同一 universe 的全市场原始成交额；不得重复计入成员。

每项滚动分位独立报告有效数、缺口、实际日期范围、60/250 门槛和 confidence；少于 60 个有效观测为 `insufficient`，60–249 为 `reduced-confidence`，不以横截面当天排名替代历史分位。所有经验 bands、权重和规则 ID 继续保持 `needs-backtest`。

分析最多输出三个按总分、核心分项和稳定行业 ID 排序的 canonical 候选。候选必须来自精确日期申万身份；未关联的 provider observation 只能留在观察层。阶段只允许一个：`insufficient`、`high-level-crowding`、`mainline-confirmed`、`mainline-candidate`、`one-day-pulse` 或 `rotation-or-ebb`。高集中度且候选宽度低于 P40 时先触发抱团否决；不得自动赋予“龙头/中军/补涨”等角色，只展示成交排名、涨幅排名、涨跌停、单股贡献和扩散比例等可证明事实。

每个日期恰好生成一条下一交易日验证项，固定格式为：

```text
候选板块：____；阶段：____。
持续性证据：____；宽度证据：____；成交证据：____；内部结构：____。
下一交易日只验证：分歧后____能否承接。
确认条件：____；失效条件：____。
```

验证优先级为：恢复关键缺口 → 抱团否决后的宽度恢复至 P40 → 成熟分歧后两日内收复至少 50% → 下一次分歧后核心三项仍各至少 60 → 首个 canonical 行业补齐三项核心门槛。没有 canonical 候选时必须返回 `candidateIndustry=null`、阶段 `insufficient`，验证项只描述关键身份/历史/事实恢复，不得输出方向性市场判断；确认和失效条件必须含明确数值、分位或分数阈值。

第 05 页的申万持续性视图单独展示 analysis 的五项 trace、历史覆盖、候选阶段、抱团风险、内部结构和唯一验证项。分析不足、THS 观察成功、分析 `failed-retained`/`failed-missing`、`observation-only`、`partial` 与 `insufficient` 必须分层显示；不能从 THS 排名或当前成员观察补算申万分析指标。所有可见文字、图表标签、tooltip 和控件不小于 14px，390px 视口不得出现页面级横向溢出、重叠或截断，宽表仅允许自身滚动。

第 05 页的申万数据管理区域只读展示 analysis readiness、required/available history、missing sessions、版本、最新 attempt、warning 和 retry eligibility；THS K 线回填操作与申万分析管理保持独立，也不得混入七数据集“全部采集”。普通 GET、启动和默认调度必须保持 provider-free；latest-only THS observation 不可用于历史日期分析。

## 验收

### 01–09 多页市场研判重构（2026-09-14）

- 01–09 继续为九个独立页面和导航入口，不收拢为“每日复盘”单页；旧 URL/hash 继续定位对应页面或锚点。
- 第 01 页固定保留五项指数卡、指数切换、60 日真实 OHLC/MA5/10/20/60 图和成交额图。页面新增市场级七项证据、结构化句式槽位/完整句复制和下一真实交易日只读对照；组合矩阵与详细证据置于“再学”折叠区。
- 句式槽位只由市场级证据生成，每个槽位返回值、质量状态和缺失原因；缺失统一显示“数据不足”，不保存用户编辑或复盘记录。
- 第 09 页保留独立综合结论，仅展示跨页证据摘要、风险否决/缺口和下一交易日后验变化，不重复第 01 页七项原始数据。
- 不新增 20 日训练进度、复盘记录表或 SQLite 写接口。下一交易日通过 `/api/market-environment/next-session` 严格读取本地 `trading_sessions` 和精确日期 materialized aggregate；无下一日或聚合缺失时返回 `pending`/`insufficient`，不联网、不使用自然日或旧日期替代。

- 一级导航和 9 个二级入口均可访问，URL hash 可恢复当前文档。
- 第 01 页无需等待全 A、涨跌停池、行业和容量方向；第 02、03、05、06 页只触发各自依赖，第 08、09 页加载综合证据。
- 章节加载失败时保留已成功的指数和其他章节数据，并提供当前章节重试动作。
- Provider 优先遵循 a-stock-data 的稳定源与限流约束，历史日期不复用今日快照。
- 市场广度刷新直接使用精确统计路径，不先请求已知不完整的名义全 A 主快照；容量方向只请求并校验成交额 Top-N 样本。
- 成功盘后快照可按交易日复用；fresh 命中不访问 provider，stale 命中返回旧值并合并刷新，失败不覆盖上次成功结果。
- 同一 dataset/date 的并发冷请求最多产生一次 provider 采集，过期 refresh lease 可以恢复。
- `/data-collection` 状态查询只读 PostgreSQL，不调用外部 provider；所有行情 provider 失败时页面仍可打开并提供可用的重试状态。
- 单项重新采集只运行目标数据集或其尚未满足的最小依赖；一键重新采集创建七个独立任务，并按 `industry-ranking -> sector-turnover -> sector-breadth` 执行三项板块依赖。一个任务失败时父批次返回 `partial`，不相关任务和已成功结果立即可用。
- 核心指数单个子项失败时其他指数继续保存；存在同日期旧值时显示 `failed-retained`，不存在时显示缺失。
- 普通市场环境 GET 只读取本地聚合快照或数据集快照，不因缺失、陈旧或活动采集自动调用 provider。
- warm Chapter 01 本地性能验证在核心和章节快照均命中时小于 500ms，provider 调用数为 0。
- Provider 失败、明确空池和数据缺失三种情况可区分，不用合成零值填补缺口。
- 量价分类不得使用通用兜底：“量价平稳”仅在日涨跌幅绝对值小于 `0.5%` 且 5 日成交额比值位于 `[1.0, 1.2)` 时成立；其余未命中组合保持 `null`。
- 六类组合判断必须由后端按量化版 `0.2` 映射计算并返回证据；未命中保持 `null`，市场广度缺失时“市场是否真强”必须显示待确认或数据不足。
- 第 01 页在六组合矩阵前独立展示指数同步性联合研判，包含原始五态、总确认状态、稳定结论码、中文结论、置信度、广度/趋势/成交额三项状态及实际数值；相互矛盾或缺失的维度必须可见。
- 第 01 页五张指数卡的收盘指数值和涨跌幅必须分别提供可键盘操作的复制入口；涨跌幅可见值保留百分号，复制值去掉百分号但保留正负号和两位小数，成功/失败状态可访问且不误报，复制不改变当前选中指数。
- 指数同步上涨与弱广度并存时保留 `synchronized_rally` 但结论为反驳；权重指数领涨但广度不弱时不得声称个股偏弱；成长占优缺少量能时不得声称题材机会得到资金支持；普遍走弱缺少任一风险确认维度时不得称为系统性下降。
- 系统不得仅凭指数方向推断银行、保险、石油等具体护盘行业；只有同日期行业证据明确支持时才允许显示行业归因。
- 上一交易日比较必须命中精确日期快照，旧日期快照不得替代；缺失比较时普通 GET 的 provider 调用数保持 0。
- 60 日走势显示真实 OHLC K 线与 MA5/10/20/60，红涨绿跌，tooltip 可读取开高低收和均线。
- 桌面和 390px 移动视口无页面级横向溢出，图表非空，移动抽屉可开关。
- 研究页首次自动加载沿用 15:00 截止规则；若候选日期不是交易日，顶部日期同步为核心响应确认的实际交易日，用户手动选择日期后不被自动覆盖。
- 同步性研判在桌面和 390px 移动视口均完整显示模式、三项确认、结论和风险；移动端确认项纵向排列，不出现文字重叠或小于 14px 的可见文字。
- 数据采集页在桌面和 390px 移动视口中保持日期、状态、进度和操作可读，不出现控件重叠；采集期间保留旧数据而不是全屏阻塞。
- TrueNAS 固定 `NodePort:32001` 的生产部署保持 manual refresh 关闭；若负责人显式开启独立 automation gate，文档与验收必须说明所有可路由客户端都能调用 full endpoint，不得将该网络误述为经过认证、授权或仅限 Hermes。
- 开市前（09:30 前）首次打开数据采集页时，默认日期为后端解析的上一工作日对应的真实交易日（周末跳过）；节假日或 provider 日期证据不足时保持 `insufficient`/`failed` 并拒绝写入，不得将前一日数据写入当日键。`industry-ranking`、`sector-turnover`、`sector-breadth` 仅接受当前已完成上海交易日，结算前拒绝 provider I/O；研究页仍保持 15:00 前默认上一日期的规则。
- 四类目录或完整快照的瞬态失败按共享 transport policy 在请求预算内有界恢复；覆盖、日期或身份仍不完整时只允许保留同日期成功快照，并区分 `failed-retained`、`failed-missing` 与依赖 `blocked`。
- 新板块契约不提供或推断单一 `leader` 角色；Top 成交和 Top 涨幅名单只展示经过验证的证券身份、原始值、排序与 lineage。
- 容量方向主域有效时不请求延迟域；主域恢复失败而延迟域有效时保存 `eastmoney-clist-delay` / `fallback` 结果并保留主域 warning。
- 容量方向延迟域不足 30 个有效样本、缺少代码/名称/成交额或未按成交额非递增排列时必须拒绝保存；两个端点均失败时只保留同日期成功快照，不得跨日期替代。
- Hermes 在 `Asia/Shanghai` 工作日 16:30 使用一个稳定 schedule-slot key 调用 full endpoint，并覆盖 `core`、`breadth`、`limits`、`industry-ranking`、`sector-turnover`、`sector-breadth` 和 `activeDirection`；三项板块任务保持依赖顺序。漏跑只允许在 17:00 前以同一 slot key 补偿，之后必须跳过并通知。
- full endpoint 在结算时间前以 422 且零 run/task/provider I/O 拒绝，周末返回 skipped；单项失败时其他成功数据仍落盘，父批次状态、结构化 failure 和兼容 warning 可在 `/data-collection` 与 status GET 查看。
- Hermes 重放依靠持久 idempotency 复用同一 run；不同 key 的手工触发与自动化触发同日期同数据集时由 lease 返回 busy 且不重复调用 provider；异常退出后的同 key replay 恢复原 run。
- 暂停 Hermes 或关闭 automation gate 不影响 Dashboard、本地快照读取、显式维护 CLI 或开发期开关控制的手工 HTTP 采集，也不删除 run/task/idempotency/snapshot 历史。
- 所有 Helm/Kustomize render 均不包含 CronJob；所有文档化通用生产写操作调用受审部署入口并对两个旧 CronJob identity 做只读 fail-closed 检测，不得恢复、创建或激活 application-owned schedule。
- 后端测试、前端生产构建和 docs-contract 完整门禁通过。
- 第 03 页完整矩阵在完整、空池、部分池、相邻日期缺失和刷新失败 fixture 下均保留上述状态与元数据；缺失证据不得渲染为伪造的 0、百分比或规则结论。
- 扶摇替换边界：limits 继续使用扶摇主源与东方财富降级/交叉核对；core/breadth 只有在 `fuyao-market-v2` capability 状态 `eligible`、批准 revision、离线契约、shadow 和隔离盘后验证均通过后才能 opt-in；三个 THS 板块数据集分别使用 catalog/snapshot、history 和 dump exact capability revision，默认 `unverified`/关闭；activeDirection 继续既有 Eastmoney/TDX。旧 `sectors` 不再参与 fallback 或新响应投影。
- shadow 仅作为可审计比较，不改变正式来源；差异显示为 `mismatch`、`degraded` 或 `insufficient`，缺失字段保持 `null`/`missing`，不使用零值或其他日期补齐。
- collector/committer/coordinator 边界验收：coordinator 不反射 collector 方法、不解释 vendor payload；每个 dataset/date 只有一个 lease 和 task sequence；core/limits 的 typed commit 在 PostgreSQL fence/UoW 内保持子结果和 detail/fact/manifest 原子；status/detail 查询 provider 调用数为 0。
- transport engine 验收：requests 与 Scrapling 对同一离线 fixture 产生除 engine/timing 外等价的 normalized payload 或 failure category；401/403/challenge 快速失败，engine 无内部 retry，默认配置不会启动 enhanced runtime，base 镜像不变且所有 Helm profile 仍不含 CronJob。

### Fuyao THS 行业与板块三数据集（2026-10-12）

- 四类合成目录 fixture 能证明独立 count/checksum/revision、重复编号拒绝、名称冲突拒绝和跨分类代码复用；共享 `thscode` 只产生一份同日期行情，同时保留所有分类关系。
- `industry-ranking` 只有在四类目录与快照身份 100% 对齐、上海日期和批次时间一致时才可发布；完整目录 checksum 在行情值分类前生成，固定 capability revision 不得作为目录 observation 主键。稳定排序为可排名行 `changePct desc, thscode asc` 后接不可排名行 `thscode asc`；缺失/重复身份和日期漂移失败关闭，而在场的字段缺失以独立 gap set、`null` 和行级不足状态保留。
- `sector-turnover` 的本地事实与 API 同时保留 OHLC、`volume` 和 `turnover`；测试证明成交量不会被丢弃、成交额不会被当作成交量、缺失字段不会被填 0，跨分类同编号写入保持幂等。
- 历史回填拒绝超过五年、默认超过 60 个编号或请求预算不足的输入，并在 provider I/O 前返回结构化错误。中断续跑只处理未完成的代码/时间窗口，单编号失败不回滚其他编号，已验证行不被新响应静默覆盖。
- Fuyao full-market daily、recent-10-day 和 adjustment dump 的 schema、checksum、日期和重复键验证通过后才允许写入；TDX 只填补同日原始事实，复权只作用于价格。混合来源逐字段显示 lineage，并使质量保持 `degraded` / `partial`。
- `sector-breadth` 的 Top 10 和用户点选合并顺序稳定、重复选择去重；涨跌平、上涨占比、涨跌家数差率、中位涨幅、MA20 宽度、涨跌停交集、Top 成交/涨幅、单股成交贡献和扩散率均使用带分子/分母的后端结果。零分母、成员缺失、MA20 不足和 limits 缺失保持 `null` / `insufficient`，不得在前端补算。
- 对非当前已完成上海交易日请求 `sector-breadth` 时，系统明确返回不支持并保持 provider 调用数为 0；任何 fixture 都不得使用当前 membership 回算历史宽度。
- 目录、单编号 K 线和 operation progress GET 覆盖分类、名称/编号搜索、revision、日期范围、分页、本地覆盖与缺口；在 provider 不可用或本地数据不足时仍能返回本地状态，provider 调用数始终为 0。
- collection 公共枚举、OpenAPI 和 TypeScript 类型只包含七个新 dataset ID。显式请求 `sectors` 返回包含三个迁移目标的稳定错误，调用旧 collector 的次数为 0，已有数据库快照、任务和 capability evidence 的内容与 checksum 保持不变。
- Chapter 01 新物化结果只暴露 `industryRanking`、`sectorTurnover`、`sectorBreadth`、`sectorAnalysis`，不把旧 `sectors` payload 伪装成新字段；任一新板块任务单独成功后都能创建或重建聚合，失败任务不移除同日成功兄弟 evidence。
- 数据管理页显示三个独立任务卡、coverage、有界 missing code、稳定 reason code、依赖 `blockedBy`、最近 attempt、保留结果和 operation progress；第 05 页四个 tab 分别承载排名、板块宽度、量价 K 线和申万持续性，并保留不可排名行但不把它们用于 Top-N。THS 视图与申万视图在名称、身份、质量和 lineage 上明确隔离，THS 数据不进入 `QTS-01-05-*` 输入。
- 量价 K 线视图同时渲染非空蜡烛、成交量和成交额；本地历史不足时仅展示实际覆盖并提供显式回填操作，不因打开或切换视图自动访问 provider。桌面和 390px 视口无页面级横向溢出、重叠或截断，所有可见文字、图例、坐标和 tooltip 不小于 14px。
- 后端 focused/full pytest、前端 Vitest/Vite build、桌面与 390px 浏览器检查、rules validate/coverage/docs sync-check、OpenSpec strict 和 docs-contract full 均通过或在 active plan 中记录精确既有阻塞；真实 probe、生产数据库迁移、部署和首次回填在再次明确授权前保持未执行。仓库所有部署 profile 均不含 Kubernetes CronJob 或调度启用值，自动化默认只由关闭的 backend gate 与尚未授权创建的 Hermes job 控制。

## Provider 请求可靠性边界（2026-10-08）

- composition root 为全部 HTTP source adapter 提供同一个进程内 policy gateway 和 engine registry。gateway 统一请求门、最小间隔、抖动、预算、网络/408/429/5xx 重试、`Retry-After`、single-flight、缓存和 cooldown/half-open，engine 只执行一个 attempt；不能在 adapter/engine 内形成第二套 transport 重试或限流。Fuyao 的 HTTP 200 业务 envelope 重试仍由 adapter 有界处理，不与 transport retry 叠加。
- 连接/读取错误、408、429、5xx 才允许 gateway 在预算内有界重试；401/403、其他权限拒绝、CAPTCHA/interstitial challenge、日期或响应契约错误快速失败。请求身份隔离 engine、完整参数、目标日期和 authentication/tenant digest；诊断不保存 credential、Cookie、proxy、secret query 或 challenge body。
- 该共享状态只保证单进程一致性，不宣称 Dashboard/自动化 HTTP/维护 CLI/多 Pod 全局限流。传输层不得改变 Eastmoney/Fuyao 的既有降级顺序、错误类型或 feature flag 默认值；失败仍保留 `failed`、`degraded`、`insufficient` 或同日期失败留存质量，不得用零值、其他日期或自动切换 enhanced engine 补齐。
- Scrapling 仅用于经授权 host 的静态 HTTP/TLS 客户端兼容验证，不定义为“绕过反爬”。它默认未安装/未启用且 allowlist 为空；Spider、JavaScript/browser、代理轮换、stealth/challenge solving 和 permission bypass 不属于本产品范围。
