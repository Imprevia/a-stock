# 修复扶摇 Shadow 差异与市场数据完整性

## Stage

Stage 3 — 处理已完成 v2 probe 暴露的 core 口径差异、breadth 分页日期证据和 sectors 字段边界。

## Status

completed (2026-09-29；正式 Fuyao 开关保持关闭)

## Acceptance

- core shadow 差异必须按指数、字段、日期和来源口径归因；不得仅通过放宽数值容差将 mismatch 改成 match。
- breadth 允许分页 timestamp 在秒级变化，但所有页转换到上海日期后必须一致且等于 `as_of`；原始 timestamp、范围和稳定性必须保留在证据中。
- sectors 只在 Fuyao 文档明确提供且真实返回的字段上生成事实；资金流、涨跌家数和领涨股缺失时保持 `null`/`insufficient`，不得伪造。
- 任何修复必须保持正式 Fuyao 开关关闭，shadow 失败不覆盖正式快照。

## Completion Evidence

- OpenSpec change `repair-fuyao-shadow-and-market-completeness` 通过 strict validate；docs contract full 已通过。
- 定向离线测试通过：core shadow + Fuyao adapter `34 passed`，collection integration `12 passed`；`git diff --check`、compile/import 检查通过。
- 2026-09-29 收盘后隔离 real-probe 使用 `deploy/truenas/deploy.env` 的 `FUYAO_API_KEY` 仅在子进程映射为 `MARKET_ENVIRONMENT_FUYAO_API_KEY`，未回显或写入仓库。core 为 5/5 指数、2425 条样本、最小 485 根、腾讯报价 5/5、请求 23 次总预算 80；breadth 为 5578 行/12 页/5559 有效，19 行缺失涨跌幅，timestamp 跨约 7 秒但上海日期一致；sectors 为目录/快照 320/320、4 批同日、10 行 fallback，五个未提供字段保持 null。
- 只读 core shadow 对账 5/5：状态仍为 `mismatch`，差异收敛为创业板成交额 1 项（约 0.714%），报告含 `provider-basis`/`amount-basis` 归因和 bounded summary；正式 provider 快照未被覆盖。之前完成的隔离 PostgreSQL capability/shadow smoke 证据仍有效，本次仅变更报告字段与归因，没有改变数据库 schema 或生产连接。

## Remaining Gaps

- core 仍有跨 provider 成交额口径差异，继续保持 `mismatch`，不批准 `fuyao-market-v2` 主源切换；只有在连续盘后 shadow 证明稳定或产品明确接受口径差异后再审批。
- breadth 真实快照存在 19 行无 `price_change_ratio_pct`，保持 `ineligible/partial`，不能补零或批准主源。
- sectors 目前只能证明代码、名称、涨跌幅和成交额；`mainNet`、`mainNetPct`、`upCount`、`downCount`、`leader` 继续为 null，保持东方财富主链 + Fuyao fallback，不宣称全字段替换。

## Next Step

继续收集连续盘后 shadow；在 core 成交额口径和 breadth 缺失行有明确产品策略前，不批准任何正式 Fuyao core/breadth revision。sectors 仅作为缺失字段明确的 fallback 保留。
