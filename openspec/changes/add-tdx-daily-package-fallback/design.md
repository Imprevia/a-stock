## Context

现有 `MarketDataProvider` 在 `breadth` 和 `activeDirection` 上先使用东方财富主域，再使用 `push2delay`；两个域共用同一供应商故障面。采集协调器已经负责独立任务、精确日期、失败保留和 provider-free 状态读取，因此本 change 只需要扩展 provider 候选链，不需要新增快照表或公开 API。

`a-stock-data` 的 `tdx_daily_package(date)` 是嵌入在 Apache-2.0 `SKILL.md` 中的取数实现，不是运行时服务，也不应成为生产环境的在线依赖。盘后包可以按指定日期提供全市场日线和成交额，但当前项目必须自行保留日期证据、完整性校验和失败语义。

## Goals / Non-Goals

**Goals:**

- 在 Eastmoney 主域和延迟域均失败后，为 `breadth` 和 `activeDirection` 增加独立的通达信盘后包备用路径。
- 将盘后包规范化为现有 quality、payload、`asOf`、warning 和快照写入契约。
- 对盘后包的请求日期、包内日期、完整下载、证券身份、数值字段和排序证据执行 fail-closed 校验。
- 使 `activeDirection` 的名称解析独立于 Eastmoney；名称缺失时拒绝候选结果。
- 让离线 fixture、provider 单元测试和 collection integration 测试覆盖成功、日期冲突、包缺失、字段缺失、名称缺失和失败保留。

**Non-Goals:**

- 不替换 Eastmoney 主源，不改变现有主源到延迟源的顺序。
- 不接入 `sectors`、`limits` 或 `core`，不修改扶摇 limits 合并链路。
- 不从 GitHub 在线下载代码或数据，不把 GitHub 仓库作为生产运行时服务。
- 不通过盘后包补齐无法证明的历史日期，不修改数据库 schema、公开 API 字段或交易规则。
- 不在 PR 测试中执行真实通达信、腾讯或其他 provider smoke。

## Decisions

### 1. 在现有 provider 边界增加第三候选源

保持 `MarketDataProvider.fetch_chapter01_breadth()` 和 `fetch_chapter01_active_direction()` 的公开边界不变。每个数据集继续执行：

```text
Eastmoney primary
        |
        +-- success --> existing payload
        |
        v
Eastmoney delayed
        |
        +-- success --> fallback payload
        |
        v
TDX daily package(as_of)
        |
        +-- validated --> fallback/degraded payload
        +-- rejected --> failed or retained
```

这样 collection coordinator、快照存储和前端无需知道新的请求协议；质量元数据中的 `source` 和 warning 仍然提供可审计来源。

### 2. 提取最小盘后包实现，不运行时依赖 GitHub

新增一个小型盘后包客户端/解析模块，提取或按 Apache-2.0 代码重新实现 `a-stock-data` 中的必要 HTTP、压缩包、记录解析和来源元数据逻辑。模块必须保留 Apache-2.0 attribution/notice，并使用固定版本或明确 revision 记录，不在服务运行时访问 GitHub。

客户端返回内部标准记录，至少包含 `code`、`date`、`close`、`amount` 和可用的 `previous_close`；原始响应中的名称、涨跌幅和市场标记如果存在则一并保留。读取必须验证 HTTP 成功、压缩包完整结束、记录格式、日期、重复证券身份、数值有限性和支持的 A 股市场范围。

### 3. 广度优先使用包内涨跌幅，否则用前一交易日包计算

`breadth` 优先使用盘后包直接提供的涨跌幅/前收字段。若盘后包只有收盘价，则按交易日历获取紧邻的前一交易日盘后包，以相同证券代码连接收盘价计算涨跌幅；前一日包不可用、日期不一致或匹配覆盖率不足时，整个候选结果保持 `insufficient`，不得用当前报价或其他日期替代。

### 4. activeDirection 只接受来源排序证据

盘后包的原始记录按成交额降序校验；系统不得先将任意全市场数据本地排序后宣称来源已排序。至少 30 行必须同时具备规范证券代码、可信名称和有限数值成交额。

名称解析按以下顺序执行：

1. 盘后包自身提供且通过格式校验的证券名称；
2. 对包内 Top-N 代码使用批量腾讯行情仅解析名称，不使用腾讯价格、成交额或日期替代盘后包事实；
3. 两者均无法得到名称时拒绝 active-direction 候选。

名称解析失败、返回代码作为名称、代码重复、成交额缺失或排序逆序都属于 `insufficient`/失败，不生成 Top-10 展示结果。

### 5. 运行时开关和来源状态

新增独立的 `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED` 开关，默认关闭，先通过离线契约和一次明确的盘后 real probe 后再启用。启用后仅在两个 Eastmoney 路径失败时触发；主源成功时不得额外请求盘后包。

盘后包成功时使用稳定来源标识 `tdx-daily-package`，状态为现有兼容的 `fallback` 或 `degraded`，warning 包含前序 Eastmoney 故障。客户端失败时把脱敏错误写入质量 warning，不暴露完整 URL 响应、压缩包内容或任何凭据。

### 6. 测试与生产边界

fixture 覆盖有效包、空包、截断包、重复代码、日期冲突、前收缺失、名称缺失、名称回退成功、名称回退失败、少于 30 行和成交额逆序。provider 测试验证调用顺序：Eastmoney 主源成功时零额外调用，主/延迟失败时才调用盘后包。

真实 provider probe 只能使用显式盘后命令和隔离输出，先确认目标日期、包源日期、行数、名称覆盖率、请求耗时和结果质量；不得将真实响应或生产数据库写入 PR 门禁。

## Risks / Trade-offs

- [盘后包发布时间晚于 CronJob] -> 包未发布时保持失败/保留语义；由显式后续重试获取，不使用临时行情补齐。
- [盘后包没有涨跌幅或前收] -> 获取前一交易日包并做覆盖率校验；无法证明时输出 `insufficient`。
- [盘后包没有证券名称] -> 只对 Top-N 使用批量腾讯名称解析；解析不全即拒绝，绝不把代码当名称。
- [包格式变化或下载截断] -> 严格验证压缩包 EOF、记录数、日期和重复身份；解析异常进入 warning 并触发原有失败保留。
- [盘后包与 Eastmoney 口径不同] -> 首期只在 Eastmoney 完全失败时使用，保留来源和 warning；后续可通过 shadow 统计差异，不自动覆盖成功主源。
- [复制上游代码的许可和供应链风险] -> 固定上游 revision，保留 Apache-2.0 notice，只提取最小逻辑，不在生产运行时执行远程代码。

## Migration Plan

1. 先实现客户端、解析器、规范化函数和离线 fixture，开关默认关闭。
2. 接入 provider fallback，运行定向 provider/collection 测试和 docs-contract；确认 Eastmoney 成功路径的调用数量与 payload 不变。
3. 使用显式盘后命令对一个近期交易日执行 real probe，只输出脱敏报告，不写生产快照。
4. 在受控环境启用开关，观察 `breadth`、`activeDirection` 的来源、日期、观测数和失败保留行为；任何异常先关闭开关即可回到原链路。
5. 只有经过一段交易日窗口验证后，才考虑将该 fallback 的默认开关从关闭调整为开启；本 change 不自动改变生产部署开关。
