## Why

市场环境看板第 02 页"上涨家数、下跌家数和涨跌幅中位数"目前只暴露 7 个原始字段（上涨家数 / 下跌家数 / 平盘家数 / 上涨占比 / 中位数 / 状态 / 数据质量）和一个三段堆叠条，无法支持盘后复盘所需的"宽度标签、量化证据、近 5 日走势、指数 × 广度一致性、次交易日验证项"等结构化判断。文档 `搭建交易系统/01-如何判断市场环境/02.上涨家数、下跌家数和涨跌幅中位数.md` 第 9-47 行的"先做再学"5 日复盘卡 与量化版 `搭建交易系统-量化版/01-如何判断市场环境/02.上涨家数、下跌家数和涨跌幅中位数.md` 的 5 条规则（`QTS-01-02-01..05`）在页面里都看不到可读证据，复盘只能凭印象，文档也无法直接对照。

## What Changes

- 扩展后端 `BreadthEvidence` / `BreadthAnalysis`契约，新增 11 个字段：`declineRatio`、`advanceDeclineSpread`、`advanceRatioPercentile`、`medianReturnPercentile`、`spreadPercentile`、`momentum`、`momentumPercentile`、`indexConsistent`、`widthLabel`、`widthLabelReason`、近 5 日 `history`（含同步 250 日 `percentile250` 覆盖信息）。
- 扩展 `providers.py` 中 `_breadth_result` 与 `_build_breadth`：在快照完成后从 `snapshot_store` 拉取最近 5 个交易日 breadth 快照，计算 250 日滚动分位、5 日动量、指数广度一致性与 6 档宽度标签（含自然语言依据）。
- 新增 `BreadthHistoryPoint` 模型（参照 `LimitHistoryPoint` 形态）。
- 前端 `BreadthAnalysis` TypeScript 类型同步扩展；02 页面由当前的 2 个 section（4 卡 + 堆叠条 + 组合判定）重构为 5 个 section（复盘卡 + 量化证据 + 5 日趋势表 + 指数 × 广度矩阵 + 验证项 + 质量元数据）。
- 新增 ECharts 折线图实例（独立 `breadthChart`，不与 `chart` / `volumeChart` 共用），用于"近 5 日宽度趋势"双轴折线图。
- 同步测试：`test_market_environment_calculations`（动量 / 分位）、`test_market_environment_providers`（6 档宽度标签 / 新字段填充）、`test_market_environment_service`（章节契约）、前端 Vitest 02 页 snapshot。
- 同步 docs：`docs/exec-plans/active/rework-breadth-page.md`（首版 plan）、`docs/status.md` 完成条目、`docs/architecture.md` 仅在数据流发生实质改变时更新。

## Capabilities

### New Capabilities

- `market-breadth-page`: 第 02 页"上涨家数、下跌家数和涨跌幅中位数"完整复盘卡 + 量化证据 + 5 日趋势 + 指数一致性矩阵 + 次交易日验证项，覆盖后端契约、计算、API 章节输出与前端渲染。

### Modified Capabilities

（无现有 capability 的 REQUIREMENTS 改变；现有 `market-data-snapshot-cache` 仅被复用，不修改其要求。）

## Impact

- 后端：`src/market_environment/schemas.py`、`src/market_environment/providers.py`、`src/market_environment/calculations.py`（如复用现有 `_metric_percentile` 不足则小扩展）、`src/market_environment/service.py`（章节契约聚合）、`tests/test_market_environment_*.py`。
- 前端：`apps/market-environment-dashboard/src/types.ts`、`apps/market-environment-dashboard/src/App.vue`（02 页模板、computed、chart 渲染管线）、`apps/market-environment-dashboard/src/styles.css`（如需新增折线图样式 token）、`apps/market-environment-dashboard/src/**/*.test.ts`。
- 数据：复用现有 `snapshot_store.get("breadth", date)` 拉取近 5 日快照；不动 PostgreSQL schema，不动 provider，不动 API 路由。
- 文档：`docs/exec-plans/active/rework-breadth-page.md`（新建）、`docs/status.md`（完成条目新增）、`docs/architecture.md`（仅在数据流出现新依赖时更新）。
- 不影响：交易规则 ID `QTS-01-02-01..05`、量化版阈值、`trading-rules/coverage.yaml`、部署清单。
- 风险：宽度标签是基于规则的派生字段，初版可能与用户主观判断存在偏差；前端不提供"用户覆写"按钮，复盘分歧由用户在评论或笔记中记录，初版在 `widthLabelReason` 中暴露派生依据。