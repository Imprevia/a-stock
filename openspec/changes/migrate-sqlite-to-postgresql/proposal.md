## Why

市场环境服务目前把 SQLite 文件同时作为快照数据库和跨进程协调边界，Dashboard Deployment 与盘后 CronJob 必须共享 RWO PVC，无法安全扩展到并发访问或多副本运行。将运行时状态迁移到 PostgreSQL 可提供事务级并发、清晰的数据库运维边界，并消除应用工作负载对共享 SQLite 文件的依赖。

## What Changes

- **BREAKING** 将市场环境运行时存储从 SQLite 迁移到 PostgreSQL，应用运行时不再接受 SQLite 文件路径作为数据库配置。
- 使用 SQLAlchemy 2 Core、psycopg 3 和 Alembic 重建快照、采集任务、lease/fencing、聚合、limits 事实、日期审计及时区偏好存储。
- 在 Helm Chart 中增加单主 PostgreSQL StatefulSet、ClusterIP Service、独立 RWO PVC 和 existingSecret 凭据合同。
- 移除 Dashboard Deployment 与 CronJob 的 SQLite PVC 挂载，改为通过 Secret 注入 PostgreSQL 连接配置。
- 增加停写后一次性 SQLite 导入、校验和切换工具；旧 SQLite PVC 保留但脱离应用。
- 保持现有 API、CLI、数据质量、失败保留、精确日期和 dataset/date lease 语义。
- 更新架构、runbook、状态记录、部署测试和 CI PostgreSQL 集成测试。

## Capabilities

### New Capabilities

- `postgresql-runtime-storage`: 为市场环境提供并发 PostgreSQL 存储、schema migration、连接配置和 SQLite 导入校验。
- `postgresql-helm-deployment`: 在 Helm/k3s 中部署单主 PostgreSQL，并使 Dashboard/CronJob 通过 ClusterIP 并发访问且不挂载 SQLite PVC。

### Modified Capabilities

- `market-data-snapshot-cache`: 将持久化和 single-flight lease 的存储后端从 SQLite 改为 PostgreSQL，同时保留精确日期、checksum、失败保留和 provider-free 读取契约。
- `market-data-collection-management`: 将 collection run/task、lease/fencing、聚合和状态读取迁移到 PostgreSQL 并保持并发行为。
- `after-market-data-collection-scheduling`: scheduled collection 改为写入共享 PostgreSQL，CronJob 不再挂载或依赖 SQLite 文件。

## Impact

- 影响 `src/market_environment/` 存储、迁移、CLI、日期重标和时区偏好代码。
- 增加 SQLAlchemy、psycopg、Alembic 依赖及 PostgreSQL 集成测试服务。
- 影响 `deploy/helm/a-stock/` 的 values、Deployment、CronJob、组件依赖和新增 StatefulSet/Service/PVC 模板。
- 需要一次受控停写迁移；生产 PostgreSQL 首次写入后不自动回切到旧 SQLite。
