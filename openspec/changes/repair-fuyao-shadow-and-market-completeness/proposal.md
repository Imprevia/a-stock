## Why

盘后真实验证显示 Fuyao v2 的 core 与现有新浪 fallback 存在明显 shadow 差异，breadth 分页 timestamp 出现秒级漂移，sectors 返回的数据字段不足以满足现有行业事实契约。需要修复证据判定和数据补充边界，避免把正常上游时间漂移误判为换日，也避免用不存在的资金或领涨字段伪造完整结果。

## What Changes

- 细化 core shadow 的日期、字段和来源口径归因，保留真实 mismatch，不以放宽容差掩盖差异。
- 将 breadth 分页 timestamp 按上海交易日归一化，保留原始值、范围和漂移证据。
- 为 sectors 探索并接入文档明确支持的补充数据；无法取得的字段继续显式缺失并阻止 capability 晋级。
- 增加真实 probe、shadow 和隔离 PostgreSQL 回归证据，保持正式切换开关关闭。

## Capabilities

### New Capabilities

- `fuyao-market-completeness`: 定义 core shadow、breadth 日期证据和 sectors 字段完整性的可审计边界。

### Modified Capabilities

- `openspec/changes/evaluate-fuyao-market-data-provider/specs/fuyao-market-data-provider/spec.md`: 修改 v2 日期、shadow 和字段完整性要求。
- `openspec/changes/evaluate-fuyao-market-data-provider/specs/market-data-collection-management/spec.md`: 修改 shadow 失败和正式快照保留语义说明。

## Impact

影响 `src/market_environment/fuyao_market.py`、`src/market_environment/provider_shadow.py`、`src/market_environment/cli.py`、采集集成测试、Fuyao fixtures、active plan 和 capability 报告。不会修改生产 Secret、生产数据库或正式切换默认值。
