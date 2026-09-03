## Why

容量方向采集只请求东方财富 `push2` 主域；当前网络环境中该主域在有界重试后仍会以 `RemoteDisconnected` 失败，导致 `activeDirection` 没有同日期旧值时直接成为 `failed-missing`。同口径 `push2delay` 端点已经实测能够返回满足成交额 Top-N 排序、最小样本和行业字段约束的数据，因此应补齐可审计的确定性降级链。

## What Changes

- 容量方向先请求东方财富主域，主域恢复失败后降级到同口径延迟域。
- 对主域和延迟域统一执行必需字段、最小样本数量和成交额降序校验，任何无效载荷都不得保存为成功快照。
- 延迟域成功时通过质量元数据标记 `eastmoney-clist-delay` 和 `fallback`，并保留主域失败 warning。
- 两个端点都失败时继续使用现有精确日期的 `failed-retained` / `failed-missing` 语义，不跨日期回填或用零值替代。
- 增加容量方向主域恢复、延迟域降级、双端点失败、无效延迟载荷和同日期快照保留测试。
- 同步市场环境产品规格、架构、runbook、状态和 active exec plan 的行为与验证证据。

## Capabilities

### New Capabilities

- `active-direction-data-collection-stability`: 定义容量方向 Top-N 采集的主域优先、延迟域降级、载荷校验、质量元数据和失败保留行为。

### Modified Capabilities

无。

## Impact

- 后端：`src/market_environment/providers.py` 的容量方向请求与质量元数据，以及相关 provider、collection、service 和 snapshot 测试。
- API：不改变现有路径或业务字段；仅使既有 `quality.source`、`quality.status` 和 warning 准确反映降级来源。
- 数据与运维：继续使用现有 SQLite 精确日期快照、共享东方财富串行限流和有界重试，不增加 schema 或外部依赖。
- 事实源：实施时更新 `docs/product-specs/market-environment-dashboard.md`、`docs/architecture.md`、`docs/runbooks.md`、`docs/status.md` 和 active exec plan。
