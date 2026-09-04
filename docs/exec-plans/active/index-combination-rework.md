# 指数、趋势位置和成交额补全与第四部分呈现重做

## Stage

Implementation

## Status

completed

## Acceptance

- 完成 OpenSpec `index-combination-rework` 的 16 项任务。
- 规则、API、前端、文档与测试保持同步，既有评分组和 golden trace 不变。
- `check-docs-contract`、规则校验、全量测试及 OpenSpec strict 校验通过。

## Completion Evidence

- `python -m src.trading_system.cli rules validate`：1 个规则集、49 条规则通过。
- `python -m src.trading_system.cli rules coverage`：330 条文档规则、49 条 executable 通过。
- `.venv/Scripts/python -m pytest -q`：132 passed、3 skipped（仅有 Starlette/httpx 弃用 warning）。
- `npm test`：12 passed，包含矩阵渲染、行联动与四种缺失文案；`npm run build`：生产构建通过。
- `python scripts/check-docs-contract.py --mode=fast`：通过。
- `python scripts/check-docs-contract.py --mode=full`：通过（代码 13 / 文档 7 / plan 1）。
- `openspec validate index-combination-rework --strict`：通过。
- 五指数显式本地 provider 冒烟：上证/中证500 走新浪，其余走百度，均返回 280 根；单项 4.71–9.70 秒，总耗时 28.70 秒。
- Midscene 桌面断言通过：五指数乘六组合矩阵、中证500行联动、证据展开和收束句面板无重叠。
- Playwright 截图：`.artifacts/index-combination-rework/desktop.png`、`.artifacts/index-combination-rework/mobile.png`；移动端矩阵在组件内横向滚动，页面无整体溢出。
- OpenSpec 主规格已同步并通过 `openspec validate --specs`（10 passed）；变更已归档至 `openspec/changes/archive/2026-09-04-index-combination-rework/`。

## Remaining Gaps

- 既有历史 SQLite 核心快照仍可能只有旧版 160 根输入；不回填，分位按 `insufficient-history` 或降置信呈现。

## Next Step

实现工作树变更提交后，将本计划移入 `docs/exec-plans/completed/`；后续自然采集的 280 根快照会持续积累分位校准样本。
