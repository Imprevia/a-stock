## Why

`src/market_environment` 已承载 HTTP API、市场分析、五类数据采集、provider 降级、质量判定、任务协调、lease/fencing、快照持久化和聚合重建，但仍采用扁平目录、巨型类和模块导入时全局装配。`snapshot_store.py`、`providers.py`、`service.py` 与 `collection.py` 合计约 8,800 行，变化原因相互交织，导致测试依赖全局 monkeypatch，新增或调整单个数据集时容易影响无关路径。

现在需要在不改变盘后研究产品行为和生产数据边界的前提下，建立可执行的依赖方向、应用装配边界和按职责拆分的模块结构，为后续 provider、指标和采集能力演进降低维护风险。

## What Changes

- 将后端重构为模块化单体，明确 `interfaces`、`application`、`domain`、`infrastructure` 与 `bootstrap` 的职责和单向依赖。
- 引入显式应用工厂、配置对象和生命周期管理，消除 `api.py` 导入时创建数据库、服务、协调器和线程池的副作用。
- 以应用端口隔离查询、采集、持久化和任务执行；普通只读用例不得依赖或触发外部 provider。
- 将单体 `SnapshotStore` 渐进拆分为快照、采集任务、lease、交易日、物化聚合和 provider capability repository，同时保留迁移期间的兼容 facade。
- 按 `core`、`breadth`、`limits`、`sectors`、`activeDirection` 拆分 dataset collector；`CollectionCoordinator` 只保留运行编排、任务状态、lease/fencing、失败隔离和提交职责。
- 将查询、物化聚合及核心/广度/涨跌停分析从 `MarketEnvironmentService` 拆成独立应用用例和领域服务，并逐步用明确类型替代跨层 `dict[str, Any]`。
- 将 PostgreSQL 固定为正式运行时持久化适配器；SQLite 仅保留为测试或停写迁移输入，运行时 schema 变更继续由 Alembic 管理。
- 增加架构依赖门禁、兼容性测试和 provider-free read 验证，防止重构后重新形成反向依赖或普通 GET 联网。
- 校准与本次架构边界冲突的文档描述，特别是 PostgreSQL 运行时和调度 fail-closed 默认值；不改变现有业务能力、API 路径或部署授权流程。
- 不引入微服务、Celery、Kafka、额外网络服务或新的市场数据源，不在本变更中调整指标公式、provider 优先级或 feature flag 默认值。

## Capabilities

### New Capabilities

无。本变更不引入新的产品能力。

### Modified Capabilities

- `after-market-data-collection-scheduling`：将陈旧的“默认启用、共享 SQLite”要求校准为仓库已经实施并由硬规则约束的 fail-closed 调度默认值和共享 PostgreSQL 运行时；不改变现有调度业务行为。

其他 `market-data-collection-management`、`market-data-snapshot-cache`、`provider-http-transport` 等能力继续作为兼容性约束，不修改其业务语义。

## Impact

- 主要影响 `src/market_environment/` 的应用装配、API 路由、服务、采集协调、provider 适配和持久化实现。
- 测试将从替换模块全局变量迁移为通过应用工厂、端口 fake 和 repository contract fixture 注入依赖；现有 API、采集、provider、快照和性能测试继续作为回归基线。
- 需要同步 `docs/architecture.md`、`docs/repository-guide.md`、`docs/runbooks.md`、相关产品规格、active exec plan 和状态记录，并修复已发现的 OpenSpec 调度存储/默认值陈旧描述。
- API 路径、JSON 现有字段、PostgreSQL 数据、checksum、lease/fencing、精确日期、同日期失败留存、质量状态和 provider 降级顺序保持兼容。
- 重构期间不执行真实 provider smoke、生产部署、CronJob 激活、PostgreSQL 生产写入或 feature flag 启用；这些仍属于各自已授权的变更和 runbook。
