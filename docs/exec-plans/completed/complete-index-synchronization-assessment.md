# 完善指数同步性联合研判

## Stage

Completed

## Status

completed

## Acceptance

- 保留既有五态 `syncPattern`，新增独立的 `synchronizationAssessment`，用市场广度、趋势位置和成交额解释并确认指数同步关系。
- 同步上涨、权重护盘、成长占优和普遍走弱均有可审计的确认、反驳、未确认和数据不足场景；没有充分证据时不得输出全面强势、个股偏弱或系统性下降等强结论。
- 上一交易日广度从指数历史确定的精确日期 SQLite 快照读取；缺失时不访问 provider，也不使用更早日期替代。
- 第 01 页独立展示同步模式、三项确认维度、结论、置信度、证据和风险，桌面及 390px 移动视口可读且无页面级横向溢出。
- Python 测试、前端测试与构建、规则回归、OpenSpec strict 校验和 docs-contract full gate 通过。

## Completion Evidence

- `.venv\\Scripts\\python.exe -m pytest tests -q`：`143 passed, 3 skipped`；包含五态阈值、六组合、49 条规则、aggregate member、评分与 golden trace 的确定性回归。
- `npm test`：`19 passed`；覆盖同步上涨、指数上涨但广度反驳、权重护盘、成长占优的确认/未确认、系统性下降和前一日广度缺失。`npm run build`：通过；仅保留既有 ECharts chunk-size 警告。
- `.venv\\Scripts\\python.exe -m src.trading_system.cli rules validate`：`{"ruleSets": 1, "rules": 49}`；`rules coverage`：`{"documentedRules": 330, "executableRules": 49}`。
- 本地隔离服务 `http://127.0.0.1:8002` 的浏览器 QA：2026-09-03 第 01 页呈现“分化未定型 / 待确认”和三项确认维度；桌面为三列约 `315.7px`，390px 为单列 `351px`，两种视口均无页面级横向溢出，联合研判可见文字均不低于 `14px`。
- `.venv\\Scripts\\python.exe scripts/check-docs-contract.py --mode=full`：通过（代码 14 / 文档 9 / plan 1）。`openspec validate complete-index-synchronization-assessment --strict`：通过。
- OpenSpec 主规格已同步并通过 `openspec validate --specs`（11 passed）；变更已归档至 `openspec/changes/archive/2026-09-04-complete-index-synchronization-assessment/`。

## Remaining Gaps

- 经验阈值仍为 `needs-backtest`，本变更不把任何阈值升级为已验证。
- 精确上一交易日广度快照可能未采集；此时比较维度必须保持 `insufficient`，不得将更早快照冒充前一交易日。

## Next Step

无；后续积累历史快照并回测经验阈值。
