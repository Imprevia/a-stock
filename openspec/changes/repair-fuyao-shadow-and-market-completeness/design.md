## Context

当前 Fuyao 文档说明 A 股 snapshot 的 timestamp 是该次快照中最新上游有效时间，因此分页间出现秒级差异是正常现象；sectors 端点只承诺行业指数代码、名称、涨跌幅和成交额。core shadow 的真实差异需要区分日期错位、字段缺失和 provider 口径差异。

## Goals / Non-Goals

**Goals:**

- 用上海日期而非原始 timestamp 相等判断 breadth 是否同日，同时保留漂移证据。
- 让 core shadow 报告按字段和指数归因，避免通过扩大容差隐藏差异。
- 让 sectors 只消费真实可证明字段；必要时通过文档支持的补充端点获取成分名称或资金信息。

**Non-Goals:**

- 不把 breadth latest-only 接口用于历史日期。
- 不将缺失的 sectors 资金流、涨跌家数或领涨股转换成零值、代码或推测名称。
- 不批准任何生产 Fuyao revision，不改变默认开关。

## Decisions

- breadth 的接受条件改为所有页 `total` 稳定、所有页 timestamp 均可解析并转换到同一上海交易日且等于 `as_of`；原始 timestamp 可按页漂移，但必须保存原始集合、最小/最大值、`timestampSpanMs`、`timestampExactStable` 和日期稳定证据。
- core comparator 保留现有字段容差，仅新增差异分类和日期/字段缺口摘要；真实数值差异继续为 `mismatch`。
- sectors 先按 Fuyao 文档探测补充 endpoint；补充数据缺失时只允许批准四个已证明字段的 `fallback` capability，不能把结果宣称为全字段替换。

## Risks / Trade-offs

- [分页跨越交易日] → 上海日期一致性仍是硬门槛，跨日继续 `insufficient`。
- [指数数据源口径不同] → 报告保留逐指数/逐字段差异，不自动升级 capability。
- [sectors 补充接口权限不足] → 记录脱敏权限错误并保留缺失字段，不阻断其他数据集。

## Migration Plan

先运行离线契约测试，再运行盘后隔离 real-probe 和 shadow；若 core 仍 mismatch 或 sectors 缺字段，保持对应数据集关闭并保留旧快照。
