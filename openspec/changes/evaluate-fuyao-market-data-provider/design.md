## Context

现有采集协调器按 `core`、`breadth`、`limits`、`sectors` 和 `activeDirection` 分离任务，快照按精确交易日持久化。扶摇客户端目前只覆盖交易日历、代码表和三类涨跌停池；`limits` 已采用扶摇主源加东方财富降级/交叉核对，其他数据集仍有独立的字段、排序、历史和日期证据要求。当前 provider 层主要通过方法名约定协作，没有可以直接替换的通用 provider protocol。

## Goals / Non-Goals

**Goals:**

- 让扶摇能力按数据集被发现、验证、审计和独立启用。
- 为 `core`、`breadth`、`sectors`、`activeDirection` 提供不改变既有 payload/quality/date 语义的适配边界。
- 支持正式 provider 与扶摇并行 shadow，对账失败时保持旧 provider 和同日期快照。
- 让缺失 key、权限、限流、字段不足、历史不可证明和日期冲突都 fail closed。
- 保持旧快照、旧客户端、limits 既有主源和五类任务的失败隔离兼容。

**Non-Goals:**

- 不在本 change 中删除或替换现有 mootdx、百度、腾讯、东方财富链路。
- 不重写已完成的 limits 接入，不移除东方财富交叉核对或降级。
- 不承诺扶摇尚未证明的 500--750 日历史覆盖、行业主力资金或全市场排序能力。
- 不在普通 PR 测试、匿名生产入口或共享生产数据库中执行真实 provider smoke。
- 不改变交易规则 ID、阈值、校准状态或前端研究页面的计算逻辑。

## Decisions

### 1. 保留现有 FuyaoClient，新增通用能力层

扶摇三类 limits 池的分页、身份和交易日历校验已经稳定，继续由现有专用客户端负责。新增一个独立的市场数据客户端/adapter 层，负责指数快照与 K 线、全市场行情、指数目录/成分和其他已公开能力；不把现有 `FuyaoClient` 强行改造成五类数据集的总 provider。

原因是 limits 的响应信封和失败语义与行情、指数、全市场分页不同，拆开可以避免对已验证路径产生回归。适配层通过现有 provider 方法边界输出标准结果，暂不引入跨项目的抽象 protocol。

### 2. 能力报告采用内部版本化记录，正式切换必须绑定 revision

新增一个小型的 `provider_capability_reports` 存储记录，按 provider、dataset、revision 保存状态、证据 JSON、检查时间和校验和；PostgreSQL 与 SQLite 均采用加法迁移。能力 probe CLI 生成该记录和脱敏 JSON 报告，运行时 cutover 只接受状态为 `eligible` 且 revision 与配置批准值一致的报告。

这样既能审计“为什么允许切换”，又不把临时 provider 响应塞进公开快照。没有批准报告或校验和不匹配时，默认继续旧 provider。

### 3. 每个数据集使用独立的能力门槛

- `core` 必须证明五个指数的代码映射、历史 K 线数量、OHLC/成交额字段、精确日期和当前报价交叉校验。
- `breadth` 必须证明全 A 涨跌幅快照的完整分页、有效样本和历史日期；只有最新快照时不得启用历史采集。
- `activeDirection` 必须证明成交额 Top-N 的排序或全量下载的完整性，并满足现有至少 30 个有效样本、代码、名称和成交额校验。
- `sectors` 必须证明行业排名、成交额、涨跌/资金字段以及领涨股名称字段；代码不得冒充名称。
- `limits` 只登记为已接入能力，不参与本次新数据集 cutover。

任一必需证据缺失即为 `unverified`/`ineligible`，不通过推导、默认值或其他日期补齐。

### 4. Shadow 结果只写任务元数据，不写正式快照

shadow 运行沿用同一 dataset/date lease，但正式 provider 仍负责快照写入。对账结果放入 collection task 的 `timings_json`/结果 JSON，至少包含两方 source revision、比较样本数、身份缺失、字段差异、数值容差和结论；不改变 snapshot payload、checksum 或公开数据集状态。

选择任务元数据而非新公开 API，是为了让现有采集页能展示来源和 warning，同时避免把未批准的扶摇数据误当成研究事实。后续若需要长期统计，可从任务结果导出，不阻塞首次迁移。

### 5. 正式 provider 选择采用 fail-closed 链

默认配置关闭四个新数据集的扶摇正式来源。启用时先验证批准的 capability revision，再按顺序执行：扶摇请求与契约校验 -> 标准 payload/quality 归一化 -> 可选旧 provider 交叉核对 -> 成功快照写入。扶摇运行时失败时按数据集配置回退当前 provider；若没有可用回退，则使用现有 `failed-retained`/`failed-missing` 语义。不得因为 fallback 成功而隐藏扶摇失败 warning。

### 6. 日期和限流边界沿用现有采集规则

所有需要历史日期的请求都必须先通过交易日历和响应日期证据校验；最新-only 接口仍拒绝历史采集。扶摇请求使用共享串行/有界并发门、有限重试和响应 envelope 错误分类；完整全市场拉取不得与五类任务无限制并发。所有 provider 预算、超时和 429/5xx 结果进入能力报告或任务 warning。

## Risks / Trade-offs

- [字段和语义不一致] -> 以现有 payload contract 为准，缺字段直接 `ineligible`，不做静默映射。
- [扶摇快照不回显日期或历史保留期不足] -> 交易日历 + 响应时间戳双重校验；只承诺验证过的日期窗口。
- [全市场分页导致请求量和延迟上升] -> 优先使用服务器排序/导出能力；否则设定页数、请求预算和最小样本门槛，超限即失败。
- [两源差异导致研究结论变化] -> shadow 先于正式切换，差异保留 warning；正式切换必须逐数据集审批，不能自动升级。
- [新元数据表与旧 SQLite/PG 不一致] -> 只做加法迁移、版本化 checksum 和跨后端 contract tests；旧快照读取路径保持不变。
- [Secret 泄露或匿名入口触发 provider] -> 独立 Secret/环境注入，默认关闭开关；日志、报告、fixture 和 API 均做脱敏，真实 smoke 只走显式隔离命令。

## Migration Plan

1. 先实现能力模型、加法 schema、离线 fixture 和 probe CLI；默认所有新数据集为 `unverified`，不改变正式采集。
2. 在隔离 PostgreSQL 中用脱敏 fixture 验证报告校验和、任务元数据、失败保留和 provider-free GET。
3. 对扶摇公开接口执行显式盘后 shadow，按数据集生成 capability revision 和差异报告；历史能力不足的数据集停留在 `unverified`。
4. 只对通过门槛的数据集设置 opt-in 开关，先保留旧 provider 作为降级路径，验证一段受控交易日窗口后再评估扩大范围。
5. 发生异常时关闭对应数据集开关并重启采集进程；保留既有快照、任务记录和 capability 报告，不删除表、不跨日期回填。

