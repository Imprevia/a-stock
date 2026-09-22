# 第 01 章市场环境看板

## Status

`active` · 版本 `0.12`

## 目标

把 `搭建交易系统/01-如何判断市场环境/` 与量化版对应文档中的盘后判断拆成可重复读取、带数据质量说明且可追溯到规则范围的网页证据，避免把主观描述或缺失数据包装成确定结论。

页面布局、组件、字体、颜色、图表、状态和响应式实现统一遵循 [`market-environment-dashboard-design-guidelines.md`](market-environment-dashboard-design-guidelines.md)。

## 用户与流程

- 盘后研究者选择交易日，从一级导航 `如何判断市场环境` 进入 01 至 09 的二级文档视图。
- 页面依次查看指数结构、市场广度、涨跌停生态、分层亏钱效应、行业主线、容量方向、事件、环境归类和综合判断。
- 首屏先展示指数结构；扩展章节证据按当前二级文档需要加载，切换页面不应被未访问数据集阻塞。
- 每个数据集同时展示来源、状态和 warning；缺失或未核实证据保持 `null` / `insufficient` / `unverified`。
- 日期时间统一按生效时区显示本地日期、时间和 UTC 偏移，悬停可查看原始 UTC ISO8601；解析优先级为个人偏好、工作区偏好、浏览器 IANA 时区，均不可用时显式显示 UTC。数据采集页“最近尝试”是市场运行审计字段，固定使用 `Asia/Shanghai`，不随浏览器或个人时区切换。偏好设置页支持 IANA 时区选择、持久化以及无效值、权限不足、离线和接口失败状态。
- 开发阶段通过独立的 `/data-collection` 数据管理页查看精确日期的五类数据状态，可单项重新采集或一键采集全部数据；普通研究页面不承担数据采集职责。
- 数据采集页首次打开时由后端按上海时区解析有效市场日：开市前（09:30 前）选择上一工作日对应的真实交易日并跳过周末；节假日或实际日期无证据时返回 `insufficient`/拒绝，provider 返回的实际日期必须与目标日期一致；开市后才选择上海当天。这样不会把尚未开始的当日误标为已完成，也不会把上一交易日行情伪装成当天；用户手工选择历史日期后仍严格展示 provider 日期限制。
- 已确认的盘前误标可在隔离 SQLite 副本通过 `snapshots relabel-date` dry-run 后显式 `--apply` 重标；流程同步快照、任务、涨跌停事实与聚合，校验 checksum/目标冲突并留下可回滚审计，不允许普通采集路径自动跨日期改名或覆盖目标日期已有成功值。
- k3s/Helm 部署的业务触发目标为上海时区工作日 16:30；Kubernetes 1.27+ 的 `native` 策略使用 `spec.timeZone: Asia/Shanghai`，k3s 1.26 的 `controller` 策略省略该字段并只接受经证据验证的 UTC/上海 controller 映射。定时任务与手工采集共享同一任务、lease、快照和失败隔离模型，结果继续在 `/data-collection` 查看和补采。

## 范围

- 五大指数的趋势、均线、区间位置、成交额和量价结构；指数卡同时展示 5 日成交额比值与明确命中的量价状态，收盘指数值与右侧涨跌幅可分别复制且不触发指数切换，60 日历史使用真实开盘、最高、最低、收盘数据展示 K 线，并叠加 MA5/10/20/60。
- 五态 `syncPattern` 只描述五指数当日涨跌关系；独立的 `synchronizationAssessment` 使用市场广度、至少三个指数相对 MA20 的位置和指数成交额确认该模式，输出 `confirmed`、`unconfirmed`、`contradicted` 或 `insufficient`，不得用确认结果反写原始模式。
- 同步上涨只有在上涨占比不低于 55% 且涨跌幅中位数大于 0 时才形成普遍性确认；权重护盘只有在上涨占比不高于 45% 且中位数小于 0 时才可描述为“指数偏强、个股偏弱”；成长占优还要求创业板指和中证500的 5 日成交额比值中位数不低于 1.0；系统性下降必须同时满足弱广度、至少三个指数位于 MA20 下方和至少三个指数放量下跌。
- “上涨家数和中位数改善”只使用指数历史识别出的精确上一交易日广度快照计算；精确快照缺失时不得用更早日期替代，普通 GET 不得因此访问 provider，当前日判断可以保留但置信度最高为中。
- 第 01 页实现“指数、位置和成交额结合判断”：展示所选指数命中的六类典型组合、触发证据和交易模式，并汇总市场强弱、阶段、资金认可和交易模式四项输出。
- 当前交易日的全 A 上涨/下跌/平盘数量、上涨占比和涨跌幅中位数。
- 日期化涨停、跌停、炸板与最高连板生态。
- 行业排名和大成交额个股方向线索。
- 01 至 09 文档导航、桌面与移动布局、数据加载和错误状态。
- `chapter01` 作为原 `indices` / `summary` 契约的可选向后兼容扩展。
- 完整聚合接口继续兼容既有调用；网页使用核心接口和章节按需接口渐进展示数据。
- 市场广度和容量方向按交易日持久化并可在盘后预计算；服务重启或同机 worker 切换后仍可复用精确日期快照。
- 数据质量允许附加缓存状态、快照抓取时间、后台刷新状态和刷新 warning；陈旧快照必须显式标记，不能伪装为刚获取的数据。
- 数据采集页覆盖核心指数、市场广度、涨跌停生态、行业板块和容量方向，并分别展示当前可用状态与最近采集结果；核心指数可展开查看五个指数子项。
- 每个数据集独立保存成功结果，一键采集中的单项失败不得停止或回滚其他数据集；失败时保留同日期最后一次成功快照并标记刷新错误。
- 手工采集写操作默认开启，可通过 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` 显式关闭；历史日期必须遵守 provider 日期能力，禁止将最新快照写成历史数据。无应用认证时，启用写入口的网络暴露必须由负责人显式接受。TrueNAS 单节点部署已接受固定 `NodePort:32001` 的匿名写入口：所有能路由到该端口的客户端均可触发 provider 调用和 PostgreSQL 写入；NodePort 不提供身份认证、客户端授权或子网限制，且不得对公网转发。
- 东方财富采集在单进程内全局串行执行；瞬态连接/读取错误、429 和 5xx 有界重试，403 不盲目重试。行业、涨跌停池与容量方向主域失败或返回无效载荷后允许降级到兼容延迟域，并保留实际来源、每个子请求的错误和降级 warning；容量方向的两个来源必须执行相同的必需字段、最小样本和成交额排序校验。涨跌停池的日期证据优先使用响应中的实际日期；`push2ex` 省略顶层日期但请求包含明确 `date` 时，可记录 `dateEvidence=request-parameter` 绑定该请求日期，并继续校验所有显式行日期，出现冲突仍拒绝 V1 完整事实。
- 行业行的领涨股展示真实证券名称；provider 只返回代码或缺少名称时保持 `null`，不得把代码冒充名称。
- 涨跌停生态以扶摇三类日期化股票池为主源、东方财富为降级与交叉核对源；交易日历确认请求日期后允许记录 `dateEvidence=request-parameter`，分页总数、规范身份或显式日期冲突任一不完整时不得写成成功集合。两源集合不一致时按规范身份取并集，扶摇字段优先，东方财富独有行和整日质量标记 `degraded` 并保留 warning。
- 盘后定时采集使用与 Dashboard 相同镜像并通过同一 PostgreSQL Service/Secret 访问运行时状态，不通过无认证 HTTP 写接口，也不复用只生成交易规则 Artifact 的 GitHub Actions workflow。
- 定时任务支持部署级关闭、暂停和受限的单一工作日 schedule 覆盖；Helm 默认值必须保持 `enabled=false`、`suspend=true`。通用 Dashboard install/upgrade/application rollback 只使用 fail-closed 部署入口与完整 baseline values，不带 scheduling overlay，不继承历史 release values、直接执行 Helm write、执行原始 uninstall 或恢复含未知调度状态的历史 revision。入口按 render 得到的 release-derived exact name 读取 live CronJob，不依赖 instance label selector；它在 build/write 前与 Helm write 前证明 stored/live application CronJob 均 absent，并从同一只读 chart/values packet 重渲染和绑定 disabled hash，active/suspended 必须先经受审 `--disable-schedule`。成功后必须证明 exact live CronJob absent，任何失败都返回非零并把意外 active CronJob 补偿、验证为 absent/suspended，否则保持 uncertain/NO-GO。所有调度布尔值必须是 typed boolean，业务时区固定为 `Asia/Shanghai`。controller 策略必须先完成只读 preflight，并通过 no-provider canary 实际观察预测触发（配置断言不能替代 canary 证据）。canary 通过后，允许继续非覆盖备份、suspended release 和一次命名 provider-backed Job；本次操作责任人书面确认 release/namespace/镜像 digest 与明确 catch-up 行为、且 live diff 仅含 `suspend` 后，才可解除暂停。默认禁止任务重叠，`partial` 不自动重跑全部五项。
- 通用部署必须在首个 render、build、image、环境或目标访问前校验最终合并值是 typed `enabled=false,suspend=true`。`--disable-schedule` 必须使用 rollback-only canonical-digest authorization ref，且 active-to-off 的失败补偿按 release-derived exact API name 工作：label/shape drift 不能阻止紧急暂停，读回无法证明 absent/typed suspended 时保持 uncertain/NO-GO。
- 周末调度命令应无 provider 调用并返回 skipped；第一版不维护交易所节假日日历，工作日节假日仍可触发，但不得把上一交易日数据写成当天快照。

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
- 单项重新采集只运行目标数据集；一键重新采集创建五个独立任务，一个失败时父批次返回 `partial`，其他成功结果立即可用。
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
- TrueNAS 直连候选启用手工采集时，完整 values render 为固定 `NodePort:32001`，且文档与验收不得将可路由网络误述为经过认证、授权或仅限特定客户端。
- 开市前（09:30 前）首次打开数据采集页时，默认日期为后端解析的上一工作日对应的真实交易日（周末跳过）；节假日或 provider 日期证据不足时保持 `insufficient`/`failed` 并拒绝写入，不得将前一日数据写入当日键。开市后才可按上海当天采集 `sectors` 等 latest-only 数据集；研究页仍保持 15:00 前默认上一日期的规则。
- 行业主域瞬态失败时按有界策略恢复或降级到延迟域；两个端点均失败时只允许保留同日期成功快照，并区分 `failed-retained` 与 `failed-missing`。
- 行业 `leader` 字段来自 provider 的名称字段，不返回领涨股证券代码。
- 容量方向主域有效时不请求延迟域；主域恢复失败而延迟域有效时保存 `eastmoney-clist-delay` / `fallback` 结果并保留主域 warning。
- 容量方向延迟域不足 30 个有效样本、缺少代码/名称/成交额或未按成交额非递增排列时必须拒绝保存；两个端点均失败时只保留同日期成功快照，不得跨日期替代。
- 合法的 native CronJob 在 `Asia/Shanghai` 工作日 16:30 调用 scheduled-refresh，并覆盖 `core`、`breadth`、`limits`、`sectors` 和 `activeDirection`；1.26 controller 兼容路径的 no-provider canary 只能证明触发映射，不能单独使周期调度可用。只有非覆盖备份、suspended release、一个 provider-backed Job、本次操作责任人书面确认（明确 catch-up 行为）与 suspend-only live diff 全部通过后才可激活。
- scheduled-refresh 在结算时间前拒绝运行，周末返回 skipped；单项失败时其他成功数据仍落盘，父批次状态和每项 warning 可在 `/data-collection` 查看。
- CronJob 与手工触发同日期同数据集时不产生重复 provider 调用；异常退出后的 task 按现有 lease 过期规则恢复。
- 禁用或暂停定时采集不影响 Dashboard、本地快照读取、手工 CLI 或开发期开关控制的 HTTP 采集。
- 无 scheduling overlay 的默认 Helm render 不包含 CronJob；所有文档化通用生产写操作均调用 `scripts/deploy-truenas-k3s.sh`，不得出现原始 Helm write 或绕过专用调度入口恢复 active schedule。
- 后端测试、前端生产构建和 docs-contract 完整门禁通过。
- 第 03 页完整矩阵在完整、空池、部分池、相邻日期缺失和刷新失败 fixture 下均保留上述状态与元数据；缺失证据不得渲染为伪造的 0、百分比或规则结论。
- 扶摇替换边界：limits 继续使用扶摇主源与东方财富降级/交叉核对；其余四个数据集只有在 capability 状态 `eligible`、批准 revision、离线契约、shadow 和隔离盘后验证均通过后才能 opt-in。默认状态为 `unverified`/关闭。
- shadow 仅作为可审计比较，不改变正式来源；差异显示为 `mismatch`、`degraded` 或 `insufficient`，缺失字段保持 `null`/`missing`，不使用零值或其他日期补齐。
