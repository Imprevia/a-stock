## Why

当前 `a-stock-daily-tier-summary` 只输出高位、中位、低位和失败样本修复，用户还需要把同一交易日的五指数方向、MA20 位置、市场宽度和成交确认放进同一张复盘卡。现有人工拼接容易把不同交易日的环境证据与分层证据混在一起，也无法稳定复用用户确认的逐行格式。

## What Changes

- 扩展每日分层总结，使其在分层结论前输出五指数涨跌名单、MA20 上下方名单、全 A 上涨占比与涨跌幅中位数、五指数 5 日成交额比值中位数、放量上涨/下跌计数、宽度标签以及与指数一致或背离的核心证据。
- 从同一目标交易日、同一物化快照 revision 的只读 v2 `overview`、`indices`、`breadth` 和 `limits` 资源组合证据；禁止把不同日期的指数环境、昨日验证和分层结果拼成一份结论。
- 复用现有 `syncPattern` / `synchronizationAssessment`、MA20、宽度和成交确认语义，不在 Skill 中另建一套指数环境分类算法；缺少必要字段时只将受影响行标为数据不足。
- 固定用户确认的中文逐行输出格式，并要求第一行列出具体上涨/下跌指数、第二行列出具体位于 MA20 上方/下方的指数，而不是只输出数量。
- 保留两个互不替代的下一交易日验证闭环：分层段只验证一个风险层，环境段只验证一个宽度、趋势或成交字段；两者都必须带可观测阈值，数据不足时不得编造条件。
- 增加同日 revision 固定、指数名单渲染、宽度一致/背离、环境分类、双验证项、局部缺失和跨日期拒绝的合成 fixture 与离线测试。

## Capabilities

### New Capabilities

- `daily-tier-market-environment-review`: 为 `a-stock-daily-tier-summary` 增加同一精确交易日的指数环境证据、固定逐行复盘格式和独立的环境验证项，同时保留原有分层验证闭环。

### Modified Capabilities

- 无。现有 `index-synchronization-assessment`、`index-combination-analysis` 和市场数据 API 的计算与返回语义保持不变；本变更只作为只读消费者组合其既有字段。

## Impact

- 修改 `.agents/skills/a-stock-daily-tier-summary/` 下的入口说明、数据合同、判断方法和确定性分析脚本。
- 修改 `tests/test_a_stock_daily_tier_summary_skill.py` 及其小型合成 fixture，并同步 active exec plan、仓库指南或适用的 Skill 文档映射。
- 不修改 FastAPI 路由、数据库 schema、市场指标公式、交易规则 YAML、前端、部署、调度、凭据或生产快照。
- 普通执行继续只使用 provider-free GET；不会触发采集、回填、数据库写入或外部行情访问。
