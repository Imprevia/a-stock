## Context

市场环境服务当前在普通查询路径中加载核心指数，并只为 `breadth` 和 `activeDirection` 提供 SQLite 持久快照。现有 `SnapshotRefresher` 已具备按 `(dataset, as_of)` 的 lease、成功结果保留和逐数据集刷新记录，但没有核心指数、`limits`、`sectors` 的统一采集模型，也没有面向开发者的状态页或异步 HTTP 控制面。

采集源的日期能力不同：核心指数和涨跌停池可按日期查询，`breadth`、`sectors` 和 `activeDirection` 只代表可验证的最新市场快照。东方财富请求还必须继续经过共享串行 limiter。数据采集可能持续数十秒，因此管理页面必须独立于行情查询路径，采集过程中继续展示已保存数据。

## Goals / Non-Goals

**Goals:**

- 统一管理核心指数、`breadth`、`limits`、`sectors` 和 `activeDirection` 五类数据的采集状态。
- 支持单项重新采集和一键全部重新采集，且任何单项失败不终止或回滚其他任务。
- 将最近一次采集结果与当前可服务的成功快照分开表达。
- 让核心指数内部的五个指数独立报告成功或失败，并允许部分可用。
- 让普通市场页面只读取本地快照和聚合结果，不因手工采集而阻塞。
- 保持现有查询接口、CLI、质量状态和精确日期隔离语义兼容。

**Non-Goals:**

- 本次不增加自动盘后调度、分布式任务队列、Redis、多 Pod 协调或完整用户权限系统。
- 本次不允许用最新快照伪造历史 `breadth`、`sectors` 或 `activeDirection`。
- 第一版不提供单个指数的独立重试按钮；核心指数行统一重采五个指数，但展示每个指数的子项状态。
- 本次不改变交易规则平台的 snapshot、evaluator 或 validated 状态。

## Decisions

### 1. 使用父批次和独立数据集任务

一次“一键全部重新采集”创建一个 collection run，并为五类数据创建独立 collection task。父批次只汇总进度和最终状态，不拥有跨数据集事务：全部成功为 `success`，部分成功为 `partial`，全部失败为 `failed`。单项采集使用同一模型，只包含一个 task。

每个 task 独立捕获异常并继续调度后续 task。外部采集可以按 provider 安全边界顺序执行；任务逻辑独立不等于必须并行访问数据源。相同 `(dataset, as_of)` 已有有效 lease 时，新请求复用活动任务或返回 `busy`，不得重复调用 provider。

替代方案是把五项视为一个事务，但这会让一个不稳定的行业或容量接口阻止其他成功数据落盘，不符合故障隔离目标。

### 2. 成功快照与采集尝试分开存储

`snapshot_entries` 继续表示每个数据集和日期最后一次可服务的成功结果。新增或扩展 collection run/task 记录，保存 `queued`、`collecting`、`success`、`partial`、`failed-retained`、`failed-missing` 和 `busy` 状态，以及开始/完成时间、耗时、来源、样本数和 warning。

失败 task 只更新采集记录和旧快照的 `refreshWarning`，不以失败 payload 覆盖成功快照。存在同日期成功快照时，状态页显示“最近采集失败、当前数据可用并保留旧值”；不存在时显示“失败且缺失”。任何回退都必须保持精确日期，禁止使用其他交易日数据。

### 3. 核心指数作为一个数据集、五个隔离子项

`core` 快照保存五个指数的规范化分析结果、核心 summary 和每个指数的采集元数据。采集器对五个指数分别捕获异常：五项全部成功为 `success`，至少一个可用且至少一个失败为 `partial`，没有任何可用指数为 `failed`。

当某个指数本次失败但同日期存在该指数的旧成功结果时，新 core 结果保留旧值并标记该子项 `failed-retained`；没有旧值时仅缺失该指数。状态页面可展开查看五个指数，但核心行的重试动作重新采集全部五项，以保持第一版操作简单。

### 4. 每个成功 task 后重建聚合快照

每个数据集成功提交后，服务从同一 `as_of` 的最新成功 `core`、`breadth`、`limits`、`sectors` 和 `activeDirection` 重新构建完整 `MarketEnvironmentResponse`，完成响应模型验证后原子替换该日期的 materialized aggregate。失败 task 不删除聚合中的旧成功数据；首次失败且无数据时保留对应 `missing` / `insufficient` 语义。

普通 `/api/market-environment`、`/core` 和 `/chapter-01` 查询逐步切换为优先读取 materialized aggregate 或数据集快照，查询路径不得因为缺失或陈旧数据自动启动外部采集。这样聚合可以混合相同日期不同采集时间的成功数据，但每个数据集必须暴露自己的来源和抓取时间。

### 5. 提供统一异步采集 API，并与 CLI 复用协调器

新增接口：

- `GET /api/market-environment/data-collection?as_of=<date>`：读取五类数据的可用状态、最近 task 和活动批次，不调用 provider。
- `POST /api/market-environment/collection-runs`：创建单项或批量采集；请求体包含 `asOf` 和可选 `datasets`，省略时采集全部五项，立即返回 `202` 和 `runId`。
- `GET /api/market-environment/collection-runs/{runId}`：返回父批次和每个 task 的进度、结果与错误。

HTTP 后台任务与 CLI 调用同一个 collection coordinator，不通过 shell 启动 CLI 子进程。使用有界进程内 executor 满足单机开发需求；SQLite task 状态和 lease 负责审计与崩溃后的有界恢复。API 进程重启导致的未完成 task 应在 lease 过期后标记为可重试，而不能永久保持 `collecting`。

### 6. 数据采集页面独立于市场证据页面

侧边栏新增“数据管理”区域和 kebab-case 路径 `/data-collection`。页面直接调用采集状态 API，不先调用 core，因此即使所有行情 provider 失败也能打开。页面采用工作台式表格：顶部日期、状态刷新和“一键全部重新采集”，表格每行显示数据可用状态、最近采集状态、来源、样本数、最近成功时间、耗时、warning 和“重新采集”动作。

页面同时展示旧值保留和最近失败，不用单一红色失败状态覆盖仍可服务的数据。采集时保留页面内容，只更新对应行的 spinner 和进度；批量采集显示已完成 task 数。成功或部分成功后刷新状态与普通看板数据，失败时提供就地重试。移动端将行内容改为无嵌套卡片的纵向字段布局，并保持操作按钮和日期控件不重叠。

### 7. 根据数据源日期能力控制采集

核心指数和 `limits` 可以为支持的历史日期单独采集。`breadth`、`sectors` 和 `activeDirection` 只有在服务能够证明所选日期等于最新市场快照对应交易日时才允许采集；否则对应按钮禁用并返回可解释的 422。历史日期无法满足全部五项时，“一键全部重新采集”禁用，用户仍可单独采集支持历史日期的数据集。

盘中为当天采集的最新数据标记为 `provisional`，结算边界后成功结果标记为 `settled`。不得因为使用开发模式而放宽日期真实性校验。

### 8. 手工采集默认关闭

新增 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED`，默认关闭。关闭时状态读取仍可用于诊断，但前端不显示写操作，POST 返回拒绝。开发环境显式开启后才允许采集，并将 CORS 的 POST 范围限制在现有开发来源。由于系统尚无认证，对外部署文档必须要求保持关闭。

## Risks / Trade-offs

- [各数据集独立提交会产生不同抓取时间] -> 聚合只组合相同交易日数据，并在每个数据集保留来源、抓取时间和质量；综合判断按缺失和降级规则降低置信度。
- [进程内后台任务会被开发服务器重载中断] -> 持久化 task 状态和 lease；重启后将过期活动任务识别为可重试，不承诺断点续跑。
- [批量任务顺序执行可能耗时较长] -> POST 立即返回，页面轮询进度且继续服务旧快照；优先保证 provider 限流和稳定性而非采集总时长。
- [无认证的写接口可能被滥用] -> 默认关闭手工采集，前后端同时检查能力开关，对外部署不启用。
- [核心部分成功可能改变已有五指数假设] -> 响应和聚合逻辑必须显式允许指数缺失并降低状态，测试所有指数和部分指数两类路径。
- [已有 SQLite schema 需要演进] -> 使用幂等前向迁移，保留现有 snapshot 表和数据；新功能可通过配置关闭并回退到 CLI 与原查询行为。

## Migration Plan

1. 创建 active exec plan，并先更新市场环境产品规格、架构和 runbook。
2. 以幂等迁移增加 collection run/task、核心指数和聚合快照存储，不改写既有成功记录。
3. 抽取统一 collection coordinator，让现有 CLI 和新 HTTP API 复用数据集采集逻辑。
4. 增加 `core`、`limits` 和 `sectors` 快照采集及核心指数子项隔离，再实现聚合快照重建。
5. 新增只读状态 API、异步 POST API、能力开关和日期校验。
6. 新增数据采集页面与导航，完成单项、一键采集、轮询、失败保留和响应式验证。
7. 切换普通查询为本地快照优先，验证 warm read 无 provider 调用。
8. 关闭开关即可隐藏写入口并拒绝 POST；SQLite 新表可保留，不需要破坏性回滚。

## Open Questions

- 无。第一版固定为核心行级重试、进程内异步执行和开发期开关；单指数重试、认证与定时调度留给后续 change。
