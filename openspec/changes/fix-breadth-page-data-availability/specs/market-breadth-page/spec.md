## ADDED Requirements

### Requirement: 当日广度摘要与历史证据独立可用
系统 MUST 将精确日期的 breadth 摘要与 breadth history 作为独立读取结果处理。当日摘要已成功返回且关键字段完整时，历史读取失败、历史为空或历史质量不足 MUST NOT 清空 `advanceCount`、`declineCount`、`flatCount`、`validCount`、`advanceRatio`、`declineRatio`、`medianReturn`、`widthLabel` 或当日质量元数据，也 MUST NOT 关闭其它已可用的 V2 资源。

#### Scenario: 历史请求失败但当日摘要完整
- **WHEN** 精确日期 breadth 摘要返回成功且关键字段完整，而 breadth history 返回服务错误
- **THEN** 第 02 页继续显示当日上涨家数、下跌家数、中位数、宽度标签和摘要质量，并将历史区域单独标记为加载失败或不可用

#### Scenario: 历史证据不足但当日摘要完整
- **WHEN** 当日 breadth 摘要完整，但本地历史有效观察少于 60 个交易日
- **THEN** 当日复盘卡和基于当日事实的宽度标签保持可用，历史分位字段为 `null`，历史质量明确为 `insufficient`

### Requirement: V2 历史展示保留真实窗口与覆盖口径
第 02 页 MUST 只在趋势表和图表中展示截至所选日期最近 5 个已验证 breadth 交易日，并 MUST 使用 `requiredObservations=60`、`windowDays=250` 和实际有效观察数报告分位覆盖。系统 MUST NOT 将实际返回条数同时用作所需观察数、窗口长度或满覆盖率。

#### Scenario: 历史接口返回超过五个交易日
- **WHEN** V2 breadth history 返回超过 5 个按日期升序排列的有效点位
- **THEN** 页面只展示最近 5 个点位，同时使用全部不超过 250 个点位计算并展示真实有效观察数和覆盖率

#### Scenario: 历史接口仅返回部分交易日
- **WHEN** V2 breadth history 返回 N 个有效点位且 N 小于 60
- **THEN** 元数据显示 `N / 60`、250 日窗口和不足状态，不将 N 显示为所需观察数，也不把覆盖率显示为 100%

### Requirement: breadth 历史补齐保持显式和精确日期
系统 MUST 仅通过显式、有限且可审计的维护操作补齐 breadth 历史快照。每个候选日期 MUST 由数据源证明实际日期等于目标交易日；不能证明日期、包不存在、样本不足或质量校验失败时 MUST 不写入成功快照。普通 GET、页面加载和默认部署 MUST NOT 触发该操作。

#### Scenario: 精确历史包通过校验
- **WHEN** 获得授权的维护操作请求一个有限日期集合，且某日期的 TDX 包能证明精确日期、普通 A 股 universe 和完整关键字段
- **THEN** 系统按该日期独立提交 breadth 快照、审计来源和质量，并重建同日期聚合

#### Scenario: 历史包不可用或日期不匹配
- **WHEN** 目标日期的包不可用、实际日期不匹配或过滤后样本不足
- **THEN** 该日期记录明确失败且不产生成功快照，不覆盖既有同日期成功证据，也不使用其它日期数据替代

#### Scenario: 未获生产写入授权
- **WHEN** 仅执行离线验证、capability probe 或普通页面读取
- **THEN** 系统产生零正式 provider 写入、零生产快照修改，并保留历史分位不足状态

## MODIFIED Requirements

### Requirement: 后端契约同时扩展 11 个新字段
`BreadthEvidence`（后端 Pydantic） MUST 包含：`declineRatio`、`advanceDeclineSpread`、`advanceRatioPercentile`、`medianReturnPercentile`、`spreadPercentile`、`momentum`、`momentumPercentile`、`indexConsistent`、`widthLabel`、`widthLabelReason`。`BreadthAnalysis`（章节契约） MUST 额外包含 `history: list[BreadthHistoryPoint]` 与 `percentile250: dict[str, float | None]`（覆盖与有效观察统计）。`BreadthHistoryPoint` MUST 包含 `asOf` / 5 个计数字段 / `advanceRatio` / `declineRatio` / `advanceDeclineSpread` / `medianReturn` / `momentum` / `widthLabel` / `indexConsistent` / `quality`。所有可缺失字段 MUST 返回 `null` 而非 0；当日摘要质量与历史分位质量 MUST 分开表达。

#### Scenario: 字段填充完整
- **WHEN** `validCount` ≥ 1、所有当日关键字段有效且 PostgreSQL 中至少 60 个历史交易日可用
- **THEN** 当日派生字段、4 个历史分位字段和宽度标签均返回非空，嵌入式 `history` 包含最近 5 个可用点位

#### Scenario: 历史不足或样本失效
- **WHEN** 当日关键字段有效，但 PostgreSQL 中有效 breadth 历史快照少于 60 个
- **THEN** 当日计数、比率、中位数、指数一致性和宽度标签保持可用，历史分位字段返回 `null`，历史质量标记为 `insufficient` 并报告真实观察数

#### Scenario: 当日样本失效
- **WHEN** `validCount` 为 0、当日关键字段为空或当日质量为 `missing` / `failed` / `insufficient`
- **THEN** 当日不可证明字段返回 `null`，`widthLabel=数据不足`，原因列出具体缺失项；已有合法历史点位仍可独立返回但不得伪造当日结论
