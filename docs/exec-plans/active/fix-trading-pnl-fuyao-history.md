# 修复盈亏日历 Fuyao 日线补齐

## Stage

实现、发布与规格归档完成。

## Status

completed-with-production-write（7/7，OpenSpec 已归档）。

## Acceptance

- 单股历史请求明确指定不复权日线。接受 Fuyao 官方响应结构，校验冲突回显、上海交易日、重复记录及无效收盘价。
- 补齐结果标明失败原因，并记录脱敏诊断。合格证据与已确认流水保留。
- 用固定响应和隔离 PostgreSQL 验证 2026-01-21 的单日补齐、盈亏重算与幂等性。用桌面和 390px 视口核对原因与明细链接。

## Completion Evidence

- 线上只读检查确认 2026-01-21 已录全流水，603019.SH 收盘价仍缺。上游错误码未知。
- 固定样本复现了旧适配器拒绝官方响应的问题。修复后，隔离 PostgreSQL 测试验证 2026-01-21 单日补齐，月历与明细显示相同的合成盈亏，重复补齐不新增证据，已有流水与估值保留。同批不同日期分别显示回显冲突及收盘价缺失。
- 后端定向测试 87 项通过，包含中文 OCR、台账、Fuyao 客户端与共享传输。前端 Vitest 177 项通过，Vite 构建通过。Chromium 390px 和 1440px 验证原因、明细链接及布局。
- 架构检查、OpenSpec 严格校验、docs-contract full 和 Git 空白检查通过。详见 [OpenSpec 任务](../../../openspec/changes/archive/2026-11-28-fix-trading-pnl-fuyao-history/tasks.md)。

- 生产版本 `31ceee3` 已发布至 Helm revision 161，详见[发布记录](deploy-fuyao-pnl-history-fix-20261128.md)。日线补齐要求及 3 个新增场景已同步到[盈亏日历主规格](../../../openspec/specs/trading-pnl-calendar/spec.md)。

## Remaining Gaps

真实上游的接口权限、实际收盘价和线上恢复待独立核验。未运行全仓测试和权威棘轮。

## Next Step

在盈亏日历显式重试所缺日期，核验真实 Fuyao 返回及台账结果。
