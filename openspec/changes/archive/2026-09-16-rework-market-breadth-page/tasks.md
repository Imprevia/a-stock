## 1. 后端契约扩展

- [ ] 1.1 在 `src/market_environment/schemas.py` 中新增 `BreadthHistoryPoint` 模型（asOf + 5 个计数字段 + 4 个比率/动量字段 + widthLabel + indexConsistent + quality）。
- [ ] 1.2 扩展 `BreadthEvidence` 字段：新增 `declineRatio` / `advanceDeclineSpread` / `advanceRatioPercentile` / `medianReturnPercentile` / `spreadPercentile` / `momentum` / `momentumPercentile` / `indexConsistent` / `widthLabel` / `widthLabelReason`；扩展 `BreadthAnalysis` 新增 `history: list[BreadthHistoryPoint]` 与 `percentile250` 覆盖字典。

## 2. 后端计算逻辑

- [ ] 2.1 在 `src/market_environment/calculations.py` 中新增 `breadth_momentum(history: list[float], window: int = 6) -> float | None`：实现 `mean(t-2..t) - mean(t-5..t-3)` 公式；窗口不足返回 None。
- [ ] 2.2 在 `src/market_environment/calculations.py` 中新增 `breadth_index_consistency(index_returns: list[float], median_return: float | None) -> bool | None`：过半数指数 `sign(changePct) == sign(medianReturn)` 则 True，否则 False；任一缺失返回 None。
- [ ] 2.3 在 `src/market_environment/calculations.py` 中新增 `breadth_width_label(advance_ratio, median_return, index_change_pcts, previous_advance_ratio, previous_median_return) -> tuple[str, str]`：6 档判定 + 自然语言依据；按提案 §D6 顺序短路返回。

## 3. Provider 计算串接

- [ ] 3.1 在 `src/market_environment/providers.py` `_breadth_result` 内部串联派生字段：先按现有逻辑算 7 个原始字段；接着通过 `snapshot_store.get("breadth", date)` 拉最近 5 个历史快照（沿用 `service.py` 第 249-273 行的拉取模式）。
- [ ] 3.2 在 `_breadth_result` 内计算 3 个 250 日分位（调用 `calculations._metric_percentile`，窗口 250 / 最小 60）；返回 `{value, confidence, reason}` 字典。
- [ ] 3.3 在 `_breadth_result` 内计算 `momentum` / `momentumPercentile`（先用 `breadth_momentum`，再调用分位）；计算 `indexConsistent`（调用 `breadth_index_consistency`）；计算 `widthLabel` / `widthLabelReason`（调用 `breadth_width_label`）。
- [ ] 3.4 在 `_breadth_result` 内组装 `history`（最多 5 个 `BreadthHistoryPoint`，每个含质量标记）与 `percentile250` 覆盖统计。

## 4. 后端测试

- [ ] 4.1 在 `tests/test_market_environment_calculations.py` 新增 `breadth_momentum` 单元测试：覆盖 t-2..t 窗口、t-5..t-3 窗口、窗口不足返回 None 三类场景。
- [ ] 4.2 在 `tests/test_market_environment_calculations.py` 新增 `breadth_index_consistency` 单元测试：覆盖 5/5 一致、4/5 多数一致、3/5 分歧、缺失指数四类场景。
- [ ] 4.3 在 `tests/test_market_environment_calculations.py` 新增 `breadth_width_label` 单元测试：覆盖 6 档各场景（含数据不足、指数强个股弱、指数弱个股修复、同向增强、同向走弱、混合）。
- [ ] 4.4 在 `tests/test_market_environment_providers.py` 中新增 `_breadth_result` 集成测试：覆盖 11 个新字段全部填充、历史不足时 `history` 缩短、分位窗口不足时 `confidence=insufficient`。
- [ ] 4.5 在 `tests/test_market_environment_service.py` 中新增第 02 页章节契约测试：覆盖 JSON 输出含全部新字段、`history` 缺失日处理、章节请求 `breadth` 不触发其它数据集采集。

## 5. 前端类型与样式

- [ ] 5.1 在 `apps/market-environment-dashboard/src/types.ts` 中扩展 `BreadthAnalysis` 接口：同步后端 11 个新字段 + `history: BreadthHistoryPoint[]` + `percentile250: Record<string, number | null>`；新增 `BreadthHistoryPoint` 接口。
- [ ] 5.2 在 `apps/market-environment-dashboard/src/styles.css` 中新增 `metric-grid six`、`metric-grid three`、`breadth-consistency-table` 三个 class（仅在样式确有差异时新增，避免与 `metric-grid four` / `combination-matrix` 重复）；其它视觉一律沿用现有 token。

## 6. 前端 02 页面重构

- [ ] 6.1 在 `App.vue` 第 598-602 行 `<template v-else-if="selectedDocumentId === '02'">` 内替换为 5 个 section：复盘卡 / 量化证据 / 近 5 日宽度趋势 / 指数一致性矩阵 / 次交易日验证项 + 质量元数据。
- [ ] 6.2 新增 computed：`breadthAdvanceDeclineSpread`、`breadthHistory`、`breadthMomentum`、`breadthWidthLabel`、`breadthIndexConsistent`、`breadthPercentile250`、`breadthIndexConsistencyRows`（5 个指数 × 一致性矩阵行）。
- [ ] 6.3 新增 `breadthChart: echarts.ECharts | null` 实例；新增 `renderBreadthChart()` 函数：双轴折线（左轴上涨占比 % / 右轴涨跌幅中位数 %），5 个数据点，当日加粗；`disposeBreadthChart()` 与 `disposeCharts()` 协同；watch `selectedDate` / `selectedDocumentId` 触发重渲染。
- [ ] 6.4 在 `App.vue` 的 `sectionWarning` / `sectionError` 逻辑中追加 02 页章节的 quality warning 与数据警告展示；不破坏现有 `chapter.breadth?.quality.warning` 路径。
- [ ] 6.5 在 App.vue `formatPosition` / `formatPct` 已有能力上补充 `formatRatioDelta` / `formatReturnDelta` 已有工具的使用；验证项"一键复制"复用现有 `copyReviewSentence` copy 按钮模式与样式。

## 7. 前端测试

- [ ] 7.1 在 `apps/market-environment-dashboard/src/` 新增 `breadth-page.test.ts`（或扩展 `app.test.ts`）：覆盖 5 section 渲染快照、宽度标签 color-tone、5 日趋势表列数、验证项 copy 按钮存在。
- [ ] 7.2 在 `apps/market-environment-dashboard/src/` 新增 `breadth-chart.test.ts`（或合并到 7.1）：mock ECharts，验证 `renderBreadthChart` 在 5 日历史齐全 / 不足时分别绘制 5 / N 个数据点。
- [ ] 7.3 在 `apps/market-environment-dashboard/src/` 新增 `breadth-page-390.test.ts`：用 Vitest + Vue Test Utils 渲染 02 页 viewport=390px，断言不存在页面级横向溢出；宽表自身滚动。

## 8. 验证

- [ ] 8.1 运行 `python -m pytest tests -q`，全量通过；记录未运行的检查。
- [ ] 8.2 运行 `python -m src.trading_system.cli rules validate` 与 `python -m src.trading_system.cli rules coverage`，确认 `QTS-01-02-01..05` 不被本 change 影响（依然 `defined` / `needs-backtest`）。
- [ ] 8.3 运行 `python -m src.trading_system.cli docs sync-check`，确认文档契约通过。
- [ ] 8.4 运行 `python scripts/check-docs-contract.py --mode=full`，确认 docs-contract full 通过。
- [ ] 8.5 在 `apps/market-environment-dashboard/` 执行 `npm run test` 与 `npm run build`，确认 Vitest 与生产构建均通过。
- [ ] 8.6 用 Playwright 在桌面（≥ 1024px）与移动（390px）视口各跑一次 02 页，截图留档作为视觉证据；写入 `evidence/rework-breadth-page/` 目录。

## 9. 文档与计划同步

- [ ] 9.1 创建 `docs/exec-plans/active/rework-breadth-page.md`：6 字段齐全（Stage / Status / Acceptance / Completion Evidence / Remaining Gaps / Next Step）。
- [ ] 9.2 在 `docs/status.md` "最近完成"区段追加本 change 的完成条目（与第 03 页 limit-ecosystem parity 条目同等粒度）。
- [ ] 9.3 评估 `docs/architecture.md` 是否需要更新（仅在数据流出现新依赖时更新）；如无更新则在 plan 的 Remaining Gaps 中写明"未变更"。
- [ ] 9.4 在 plan 的 `Completion Evidence` 字段写明：commit SHA、测试运行输出（脱敏）、前后端 build 通过截图路径、桌面 + 390px 视觉证据路径。
- [ ] 9.5 本 change 不触发 `trading-rules/coverage.yaml` 增量（仅做事实源扩展，不引入新规则 ID）；在 plan 的 Acceptance 中显式声明此约束。

## 10. 收尾

- [ ] 10.1 运行 `git status` / `git diff --stat`，确认改动文件清单符合预期（后端 schemas / providers / calculations / service / tests；前端 types / App.vue / styles.css / 新增测试）。
- [ ] 10.2 运行 `python scripts/check-docs-contract.py --mode=fast`，确认 commit 前本地 gate 通过。
- [ ] 10.3 在 OpenSpec 完成实施后，运行 `/opsx-archive` 归档 `rework-market-breadth-page`。