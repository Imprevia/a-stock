## Why

每日分层总结读取 v2 三类涨跌停池时，可能得到“观察数非零、明细为空”的响应：PostgreSQL 查询以 `invalid_reason IS NULL` 替代领域层 `membership_valid`，把高级属性缺失和非涨停池的旧晋级排除原因错误用于成员过滤。已有持久化明细因此无法参与冻结样本、次日反馈和失败样本修复计算，需要修复读取投影，并补上真实 SQL 的回归验证。

## What Changes

- 统一 v2 涨停、跌停、炸板池与领域层的成员有效性语义：身份和精确日期有效的成员可见，高级属性不足只影响依赖该属性的判断；身份、日期、重复和跨池冲突行仍排除。
- 对齐 v2 `promoted` 明细与现有基础晋级聚合：使用精确相邻交易日完整涨停集合的有效身份交集，保留完整度、规则版本及校验和绑定门禁，不额外要求旧 `eligible=true`。
- 保留现有响应形状、行级 warning、池质量、失败保留、排序、分页与 revision 语义；缺失连板字段不升级为可分层证据。
- 在本变更的规格增量中明确成员、连板和高级属性三类证据边界，协调已完成 `restore-limit-ecosystem-data-availability` 变更与主规格尚未同步的晋级口径。实施时先完成受影响事实文档同步。
- 补充实际执行 PostgreSQL 查询的三池、晋级池、HTTP 与每日分层脚本回归，避免仅模拟 SQL 结果掩盖过滤错误。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `ai-market-data-api`: 明确 limits 池成员读取语义、晋级池与聚合的一致性、质量传播和有界读取要求。
- `limit-ecosystem-dashboard-parity`: 将主规格的旧严格资格口径对齐已实现的基础晋级口径，明确连板梯队和高级属性分层各自的证据门槛。

## Impact

- 实现归属：`src/market_environment/domain/policies/limit_facts.py` 的成员有效性事实源、`infrastructure/persistence/postgres/v2_market_data.py` 的 SQL 投影；按需对齐 `limit_ecosystem.py` 和兼容适配器的现有明细序列化，不重写晋级算法。
- 验证归属：现有 v2 adapter/resource 测试、隔离 PostgreSQL 集成测试及 `tests/test_a_stock_daily_tier_summary_skill.py`；全部使用合成数据，普通测试不访问生产或 provider。
- 实施前创建 `docs/exec-plans/active/restore-v2-limit-pool-membership.md` 并登记索引；同步 `docs/architecture.md`、`docs/product-specs/market-environment-dashboard.md`、`docs/runbooks.md` 及必要的代码-文档映射。
- 不引入依赖或 schema migration，不修改 provider、不重采或回填、不改每日总结的格式和交易阈值。部署、非测试数据库和外部写入均不在本变更范围；代码修复完成不等于生产已恢复。
