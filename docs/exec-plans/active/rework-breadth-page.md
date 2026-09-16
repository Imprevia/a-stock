# 02 页 · 上涨家数、下跌家数和涨跌幅中位数重构

## Stage

Implementation

## Status

completed

## Acceptance

- 后端 `BreadthEvidence` 与 `BreadthAnalysis` 同步新增 11 个字段（`declineRatio` / `advanceDeclineSpread` / 3 个 250 日分位 / `momentum` / `momentumPercentile` / `indexConsistent` / `widthLabel` / `widthLabelReason` / `history` / `percentile250`）；新增 `BreadthHistoryPoint` 模型。**已落地**（[schemas.py](file:///G:/workspaces/a-stock/src/market_environment/schemas.py)）。
- 后端 `_breadth_result` 通过 `snapshot_store.get("breadth", date)` 拉取最近 5 个交易日历史快照计算 250 日分位、5 日动量、指数广度一致性与 6 档宽度标签（含自然语言依据）。**已落地**（[service.py](file:///G:/workspaces/a-stock/src/market_environment/service.py) `_enrich_breadth`）。
- 前端 `BreadthAnalysis` TypeScript 接口同步扩展；02 页模板由 2 section 替换为 5 section（复盘卡 / 量化证据 / 近 5 日趋势 / 指数一致性矩阵 / 次日验证项 + 质量元数据）；新增独立 `breadthChart` ECharts 实例绘制双轴折线。**已落地**（[App.vue](file:///G:/workspaces/a-stock/apps/market-environment-dashboard/src/App.vue) 第 02 页分支 + `breadth-page.test.ts`）。
- 全部新文字 ≥ 14px；390px 移动视口不出现页面级横向溢出（宽表自身滚动）。**已验证**（`breadth-page.test.ts` 中 390 viewport 断言）。
- Python 测试（calculations / providers / service）、前端 Vitest、`python scripts/check-docs-contract.py --mode=fast`、`python -m src.trading_system.cli rules validate`、`python -m src.trading_system.cli rules coverage` 全部通过。docs-contract `--mode=full` 在 code/plan 同步后通过。
- 不修改交易规则 `QTS-01-02-01..05` 的 ID、阈值、权重；`trading-rules/coverage.yaml` 不增不减。**已验证**（`rules validate` 输出 `{"ruleSets": 1, "rules": 49}`，`rules coverage` 输出 `{"documentedRules": 330, "executableRules": 49}`）。
- 不引入新 provider、新 API 路由、新 PostgreSQL schema、新采集任务。**已验证**（git diff 与 architecture.md 第 02 页派生边界小节）。

## Completion Evidence

- `python -m pytest tests/test_market_environment_calculations.py tests/test_market_environment_providers.py tests/test_market_environment_collection.py tests/test_market_environment_database.py tests/test_market_environment_date_relabel.py tests/test_market_environment_refresh.py tests/test_market_environment_snapshot_store.py tests/test_market_environment_service.py tests/test_market_environment_limit_contract.py tests/test_market_environment_limit_performance.py tests/test_market_environment_limit_promotion.py tests/test_market_environment_api.py tests/test_market_environment_limit_facts.py tests/test_market_environment_limit_fixtures.py tests/test_trading_rule_platform.py -q`：**278 passed, 3 skipped**（脱敏输出）。
- `cd apps/market-environment-dashboard && npm test`：**46 passed**（39 原有 + 7 新增 breadth-page.test.ts）。
- `cd apps/market-environment-dashboard && npm run build`：Vite 生产构建通过（dist/index.html 0.47 kB / index.css 45.93 kB / index.js 1,224.77 kB）。
- `python -m src.trading_system.cli rules validate` → `{"ruleSets": 1, "rules": 49}`。
- `python -m src.trading_system.cli rules coverage` → `{"documentedRules": 330, "executableRules": 49}`。
- `python scripts/check-docs-contract.py --mode=fast` → 通过。
- `python scripts/check-docs-contract.py --mode=full` → 通过（code 0 / docs 0 / plan 0）。
- 桌面 + 390px 视觉证据：依赖 Vitest `breadth-page.test.ts` 中的 viewport assertion（content-shell scrollWidth ≤ 390）；本地未跑 Playwright 截屏（与既有 plan 同粒度）。

## Remaining Gaps

- 宽度标签是后端派生的固定规则，初版可能与个别用户主观判断存在偏差；前端不提供覆写，分歧由用户在笔记或评论中记录。
- 250 日分位在前期 PostgreSQL 历史快照不足 60 个观察时全部标记 `insufficient`，不补 0。
- 5 日趋势与指数一致性矩阵依赖 PostgreSQL 历史快照存在；缺失日不补假数据，UI 显示 `--`。
- 与 03 页 limit-ecosystem parity 同粒度，桌面 + 390px 视觉证据依赖 Vitest 的 viewport assertion，未在 CI 中跑 Playwright 截屏。

## Next Step

- 进入 OpenSpec 归档流程 `/opsx-archive rework-market-breadth-page`；归档前确认 CI 与 docs-contract 通过。