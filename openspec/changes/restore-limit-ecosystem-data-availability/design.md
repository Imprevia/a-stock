## Context

现有实现已经具备 PostgreSQL 事实表、相邻交易日解析、limits V1 开关、晋级聚合和第 03 页证据布局，但 `complete` 同时承担集合和高级属性完整度，导致东方财富缺少制度/板块等字段时所有晋级证据被拒绝。扶摇提供三类日期化股票池、标准 `thscode`、涨停连板数、交易日历和全量代码表，但池响应不回显交易日，行业/制度字段也不完整。

## Goals / Non-Goals

**Goals:**

- 将完整证券集合与高级属性完整度拆开，使基础晋级、梯队和短期历史可在真实数据上工作。
- 保持普通 GET provider-free、PostgreSQL 事务/lease/CAS、失败保留和旧五字段兼容。
- 提供可审计股票明细，并让第 03/04 页在日期与刷新变化后读取同一 limits section。

**Non-Goals:**

- 不推断行业板块或未被数据源证明的涨跌幅制度，不改变交易规则 ID、权重或 `needs-backtest`。
- 不在本 change 中部署生产、创建生产 Secret、写生产数据库或承诺扶摇未公开的长期历史保留期。

## Decisions

### 1. 扶摇主源与东方财富并联合并

新增独立扶摇客户端，顺序拉取 `limit-up-pool`、`limit-down-pool`、`limit-break-pool`，每页 200 条并校验 envelope、分页总数和规范身份。一次采集运行只拉取一次代码表并复用交易所/上市日期映射。HTTP 429、envelope `4001`、网络错误和 5xx 最多重试两次；权限错误和业务参数错误不重试。

两源均成功时以规范证券身份取并集，字段冲突使用扶摇值，东方财富独有行标记 degraded。扶摇失败时允许东方财富完整集合进入基础计算；两源均无法证明完整分页时不写成功事实。扶摇请求日期仅在交易日历确认后作为 `actual_as_of`，quality 标记 `dateEvidence=request-parameter` 并保留上游不回显日期 warning。

### 2. 拆分数据集完整度

在 `limit_security_datasets` 增加 `membership_complete`、`streak_complete` 和 `pool_quality_json`；原 `complete` 保留为旧严格 enrichment 完整度，旧行的新字段为 null，因此不会被自动升级。基础晋级只检查两日 `membership_complete` 和已绑定聚合 checksum；梯队检查涨停行 `streak_days`；ST、上市窗口、制度和板块各自扫描所需字段。

涨停池成员在盘后集合语义下记录 `closed_limit_up=true`，炸板池成员记录 `touched_limit_up=true/failed_limit_up=true`，依据为 provider pool membership，不通过价格阈值猜测。`eligible` 继续兼容旧记录，但基础晋级不再用它排除 ST、新股或高级属性缺失行。

### 3. 加法事实字段和公开明细

Alembic `0002` 和 fresh bootstrap 同步增加 `is_new`、涨停时间/原因、封单额、首次/最后跌停时间、开板次数、换手率、成交额、`row_quality`、`row_warnings_json`。checksum 覆盖逻辑证据但不包含抓取时间。

`LimitEvidence.securityDetails` 包含 `limitUp`、`limitDown`、`failedLimitUp`、`promoted` 四组，每组返回归一化后的 `total/rows/quality`。`promoted` 由相邻两日涨停集合交集生成，不额外持久化。章节接口一次返回全部行，前端负责搜索和分页，避免新增可能触发 provider 的网络路径。

### 4. 六日回填复用现有采集事务

为显式 `snapshots refresh` 增加 `--history-sessions N`，仅允许选择 limits 且 `N >= 1`。协调器先通过扶摇交易日历解析截至目标日的最近 N 个交易日，再按升序逐日调用现有 dataset/date lease 采集；单日失败记录失败并继续，其余成功日不回滚。默认 N=1，定时采集行为不变。六日数据产生最近五个可计算晋级点，60/250 日门槛不变。

### 5. 页面只消费 limits 真实证据

第 03 页用折叠明细区承载四组切换、关键词搜索、20 行本地分页和横向滚动。DashboardLayout 监听一次 core 加载从 loading 到完成，在当前路由声明 section 时调用 `loadSection`；这同时覆盖切换日期和同日期全局刷新，并复用现有 epoch/sequence 淘汰迟到响应。

第 04 页从 `stratifications[dimension=risk_tier]` 读取 high/middle/low 数量，从 `riskEvidence[code=failure-repair]` 读取修复率；每张卡使用自己的 quality。删除前端 `tierRisk` 类型和文档声明，不将样本数量冒充已经校准的亏钱效应分数。

### 6. Secret 与发布边界

运行时读取 `MARKET_ENVIRONMENT_FUYAO_API_KEY`，禁止写日志。Helm 增加独立 provider Secret 名称/键配置，并向 Dashboard 与 CronJob 注入；原生 k3s 清单使用同一变量名。`MARKET_ENVIRONMENT_LIMITS_V1_ENABLED` 默认仍为 0，启用但缺 Secret 时采集 fail closed。真实 smoke 只写隔离 PostgreSQL。

## Risks / Trade-offs

- [扶摇不回显交易日] → 交易日历先验证、记录 request-parameter 证据和 warning，任何响应日期冲突立即失败。
- [双源集合差异扩大计数] → 保留并集、逐行来源和集合差异 warning，整日标记 degraded，便于审计而不静默丢行。
- [明细放大章节 payload] → A 股三类池规模有限，单次返回并前端本地分页；测试序列化大小和响应时间。
- [旧 complete 语义混淆] → 新聚合只读显式 `membership_complete`，旧数据必须重新采集，不隐式升级。
- [历史部分失败] → 按日独立事务和质量记录，不用其他日期替代，不覆盖既有成功快照。

## Migration Plan

1. 先应用 Alembic 加法迁移并保持 V1 关闭；验证 fresh/upgrade schema 和旧快照读取。
2. 发布代码与 Secret 引用但不创建或修改生产 Secret；离线 fixture 验证通过后，在隔离 PostgreSQL 开启 V1。
3. 使用目标日和 `--history-sessions 6` 执行盘后隔离 smoke，验证集合、五个晋级点、明细与第 04 页来源。
4. 回滚时先关闭 V1，再恢复应用版本；保留 PostgreSQL 新列、事实、快照和 PVC，不执行降级删除。
