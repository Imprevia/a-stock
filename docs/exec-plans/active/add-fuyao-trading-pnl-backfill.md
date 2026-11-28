# 盈亏日历 Fuyao 历史行情补齐

## Stage

本地实现与离线验收完成。

## Status

completed-local-only（OpenSpec 已归档）

## Acceptance

- 显式选择日期范围后补齐精确交易日和不复权收盘价，保留本地合格证据及尚缺原因。
- 补录或更正后链接到受影响日期，重新确认流水后按新持仓恢复后续盈亏。
- 使用固定 Fuyao 响应、隔离 PostgreSQL 和桌面及手机布局验收。

## Completion Evidence

- 10 项 OpenSpec 任务全部完成，已同步 [盈亏日历主规格](../../../openspec/specs/trading-pnl-calendar/spec.md) 并归档 [OpenSpec 任务和验收范围](../../../openspec/changes/archive/2026-11-28-add-fuyao-trading-pnl-backfill/tasks.md)。
- 独立 PostgreSQL 使用合成交易、固定 Fuyao 响应及容器内中文 Tesseract。定向后端回归 114 项通过，另通过区间首日需补前一交易日估值的回归。
- 验证了 1 月 21 日仅补所需估值、部分失败后重试、重复无新增、并发时保留已有证据、3 月 20 日只撤销当天覆盖并恢复卖清或部分卖出的持仓。
- 前端 Vitest 177 项通过，Vite 构建成功。Chromium 在 390px 和 1440px 验证显式补齐、剩余缺项及日期链接，文字至少 14px，页面无横向溢出。
- OpenSpec 严格校验、架构检查、docs-contract full、规则校验和文档同步检查通过。

## Remaining Gaps

- 全仓权威门禁在测试收集阶段遇到仓库已有的 `fuyao_client` 同名导入冲突，受影响模块为 `tests/test_a_stock_qts04_sector_direction_skill.py`。权威棘轮验证和基线审核待完成。
- 线上发布与历史台账写入待独立授权。公司行动和停牌估值仍使用可核实的独立证据。

## Next Step

处理全仓测试收集问题和基线审核后，再安排线上发布。
