## Context

现有 `SnapshotStore` 和 `TimezonePreferenceStore` 直接使用 SQLite DB-API、SQLite 事务语法和文件路径；Dashboard 与 CronJob 通过共享 RWO PVC 访问同一个数据库文件。目标部署仍是单节点 k3s，但两个工作负载需要独立调度并发读写。现有 API、collection coordinator、日期重标和失败保留语义必须保持兼容。

## Goals / Non-Goals

**Goals:**

- 以 PostgreSQL 作为唯一运行时存储，并以事务和行锁替代 SQLite 文件锁。
- 保留现有数据模型的业务语义、checksum、精确日期、lease fencing 和 provider-free 读取。
- 在同一 Helm Chart 中提供单主 PostgreSQL StatefulSet、Service、PVC、迁移依赖和 Secret 合同。
- 提供可审计、可重试、幂等的 SQLite 导入与校验流程。

**Non-Goals:**

- 不实现 PostgreSQL 主从、自动故障转移、读副本或跨节点 HA。
- 不在应用运行时长期维护 SQLite 双写或双读后端。
- 不删除旧 SQLite PVC，不执行生产集群写入或真实 provider smoke。

## Decisions

### 存储技术

采用 SQLAlchemy 2 Core + psycopg 3 + Alembic。SQLAlchemy 提供连接池、事务和 PostgreSQL 类型适配；Alembic 替代 `PRAGMA user_version` 和手工 schema 演进。保留 `SnapshotStore` 的领域方法接口，内部改为 SQLAlchemy Core statement/transaction，以避免上层 service、collection 和 API 契约变化。

相比继续扩展 SQLite/psycopg 双实现，单一 PostgreSQL 实现避免两套 lease/CAS 语义长期漂移。SQLite 只由迁移工具以只读方式打开。

### 数据类型和并发

- 交易日使用 `DATE`，审计时间使用 UTC `TIMESTAMPTZ`，JSON payload 使用 `JSONB`。
- SQLite `rowid` 依赖改为 identity 主键；所有排序和最新记录查询使用显式 identity 字段或时间字段。
- lease acquire 在一个事务内对 dataset/date 行执行 `SELECT FOR UPDATE`，必要时插入占位行，再检查 expires/generation 并更新 token；唯一约束保证单活跃 lease。
- lease fence、snapshot commit、collection task transition 和 materialized aggregate 使用显式事务；冲突通过 generation/CAS 检查拒绝，不使用应用进程内锁作为正确性边界。
- PostgreSQL trigger 或同一事务更新 materialization component revision，保证 aggregate 重建的输入版本可验证。

### 配置和凭据

服务只接受 `MARKET_ENVIRONMENT_DATABASE_URL`（或等价的拆分连接配置）；缺失或不可达时 fail closed，不回退到 SQLite。Helm 只引用 `existingSecret` 的 key，禁止在 values、模板输出或命令行中写明文密码。数据库 Service 仅为 ClusterIP。

### Helm 资源和依赖

Chart 新增 `postgresql` 组件：StatefulSet、Service、PVC 和 readiness/liveness。应用 Deployment/CronJob 不挂载数据库 PVC，使用同一 Service 和 Secret。migration Job 在 service/schedule 之前运行；schedule 默认仍 disabled/suspended，数据库 ready 和迁移成功不能自动取得生产调度授权。

PostgreSQL 使用固定主版本和可审计的不可变镜像引用。数据库 PVC 采用 Retain，只有 StatefulSet 挂载。

### SQLite 导入

迁移命令接受显式 SQLite 源路径和 PostgreSQL URL，默认 dry-run；apply 前要求源文件已备份并通过 `PRAGMA quick_check`、schema version、表清单和 checksum 检查。导入按依赖顺序执行，使用 `ON CONFLICT` 实现幂等，全部历史数据和审计记录在 PostgreSQL 事务中提交。active lease ownership 不迁移为有效持有者，改为过期/可重试状态并保留 fence 事件。

导入后比较每表行数、主键范围、日期覆盖、payload checksum 和 materialized aggregate checksum。校验失败回滚导入事务；源 SQLite 保持不变。

### 切换和回滚

切换前暂停 CronJob、关闭手工采集并停止 Dashboard 写入。先部署数据库和迁移 Job，再更新应用连接配置并执行 provider-free 读取和并发 lease 验证。旧 SQLite PVC 和 before-image 保留但从应用工作负载脱离。

PostgreSQL 首次写入前失败时，可恢复旧镜像和 SQLite PVC。首次写入后不自动回切旧 SQLite，因为其内容已过时；此时使用 PostgreSQL 备份/恢复或前向修复。

## Risks / Trade-offs

- [连接配置错误导致启动失败] -> 使用 Secret key 校验、Service readiness 和 fail-closed Helm/render 检查。
- [迁移遗漏或类型转换改变 checksum] -> 导入前后执行表级统计、payload checksum、日期覆盖和 aggregate checksum 对比。
- [PostgreSQL 单点故障] -> 明确单主非 HA 范围，启用 PVC Retain、备份 runbook 和 readiness 探针。
- [连接池耗尽或长事务阻塞] -> 配置有限连接池、statement/transaction timeout，测试 Dashboard/CronJob 并发读写和冲突重试。
- [旧计划/测试仍假设 SQLite] -> 同步架构、runbook、README、active plan 和部署断言；SQLite 文件只在迁移测试中出现。
