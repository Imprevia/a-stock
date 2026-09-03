## Why

行业板块采集在交易日 15:00 前默认选中上一日期，导致 latest-only 数据集被确定性禁用；即使切换到当天，东方财富 `push2` 主域的瞬态断连也会因为缺少重试和降级而直接形成 `failed-missing`。当前行业字段映射还把领涨股代码当作名称，真实响应与测试契约不一致。

## What Changes

- 让数据采集页默认使用后端认定的上海市场当天，行情研究页继续使用最近已结算日期。
- 对东方财富请求实行跨采集任务的真正串行访问，并对连接中断、429 和 5xx 进行有界退避重试；403 保持不重试。
- 行业排名主域失败时降级到已验证同口径的 `push2delay` 端点，并通过质量元数据明确标记 fallback。
- 修正行业领涨股字段，请求并使用真实名称字段，不再把证券代码显示为名称。
- 增加日期默认值、瞬态恢复、403、并发串行、行业降级、字段解析和失败保留测试。
- 同步市场环境产品规格、架构、runbook、状态和执行计划证据。

## Capabilities

### New Capabilities

- `sector-data-collection-stability`: 定义行业板块采集的可采集日期、东方财富请求恢复与降级、字段语义和可审计质量状态。

### Modified Capabilities

无。

## Impact

- 后端：`src/trading_system/data/providers.py`、`src/market_environment/providers.py` 及相关采集/API 测试。
- 前端：数据采集页日期初始化、日期工具和单元测试；现有行情看板默认日期行为保持兼容。
- 运维与事实源：`docs/product-specs/market-environment-dashboard.md`、`docs/architecture.md`、`docs/runbooks.md`、`docs/status.md` 和 active exec plan。
- 外部依赖：不增加新依赖，继续使用 `requests`/`urllib3` 已提供的连接池与重试能力。
