# SQLite 迁移至 PostgreSQL

## Stage（阶段）

Stage 1 — PostgreSQL 存储、SQLite 导入、Helm/k3s 单主数据库与离线验证。

## Status（状态）

`completed-without-production-write`（实现、离线部署验证和测试已完成；生产迁移与真实 provider 写入仍需独立维护窗口授权）

## Scope（范围）

- 运行时存储统一迁移到 PostgreSQL；SQLite 只保留为一次性只读导入源。
- Helm Chart 内置单主 PostgreSQL StatefulSet、ClusterIP Service、独立 RWO PVC 和 existingSecret 合同。
- Dashboard Deployment 与 CronJob 不再挂载数据库 PVC 或 `/data/snapshots.sqlite3`。
- 使用 SQLAlchemy 2 Core、psycopg 3 和 Alembic，保留现有 API、精确日期、checksum、lease/fencing、失败保留和 provider-free GET 语义。
- 增加停写导入、校验、切换和回滚运行手册；不执行生产集群或真实 provider 写操作。

## Acceptance（验收）

- PostgreSQL schema 覆盖快照、采集、lease/fencing、聚合、limits、交易日、日期重标和时区偏好。
- Dashboard/CronJob 通过 PostgreSQL Service 并发访问，只有 StatefulSet 挂载数据库 RWO PVC。
- SQLite 导入为默认 dry-run、显式 apply、幂等并校验 quick-check、表统计、日期与 checksum；active lease 不作为有效所有权迁移。
- PostgreSQL 集成测试、迁移测试、Helm lint/template、OpenSpec strict 和 docs-contract full 通过。

## Completion Evidence（完成证据）

- OpenSpec change `migrate-sqlite-to-postgresql` 的 proposal、design、五份 delta spec 与 tasks 已创建并通过 strict validation。
- `tests/test_market_environment_database.py` 包含真实 PostgreSQL service 下的 schema、并发 lease/CAS、collection run/task、limits facts、materialized aggregate、SQLite apply import 与重复导入幂等验证；本次本地全量环境未提供 PostgreSQL 容器，3 个需要连接的集成用例按约定 skip；日期重标、快照/采集/API 聚焦套件通过。
- Helm lint 与带 existingSecret 的 template 通过；schema migration Job 使用 `post-install,post-upgrade` hook，依赖顺序为 `postgresql -> schema migration -> service -> schedule`。
- Helm render 已验证应用 Deployment/CronJob 不含 SQLite 路径或 PVC 挂载；PostgreSQL StatefulSet 独占 Retain RWO PVC。
- `docs/architecture.md`、`docs/runbooks.md`、`README.md` 和本计划已同步 PostgreSQL Secret、备份恢复、停写切换及回滚边界；CI PR workflow 已配置固定 digest PostgreSQL service；未执行生产集群写操作。
- 最终离线验证：`629 passed, 3 skipped`（pytest，2 个既有 FastAPI deprecation warning）、前端 `39 passed` 与 Vite production build；`helm lint --strict`、Helm/k3s render、CLI rules/docs checks、OpenSpec strict、docs-contract full、`compileall` 和 `git diff --check` 均通过。

## Remaining Gaps（剩余缺口）

- 默认服务构造仍保留显式 SQLite fixture seam，供离线测试和一次性迁移输入使用；生产 Helm/TrueNAS workload 已 fail-closed 注入 PostgreSQL URL，后续可将服务启动路径进一步拆分为只接受 PostgreSQL 的构造器。
- `SnapshotStore` 的部分 SQL 仍经 `postgres_compat.py` 翻译 qmark，占位 seam 后续应逐步替换为 SQLAlchemy `text()`/Core statements，并继续保持现有 API 语义。
- TrueNAS operator override 的生产资源尚未执行 PostgreSQL 切换；生产迁移与真实 provider 写入未执行。

## Next Step（下一步）

实现阶段已完成。下一步仅在获批维护窗口执行停写 before-image、PostgreSQL 导入校验和受控切换；不得在本计划内删除旧 SQLite PVC、回切过期 SQLite 或执行生产 provider 写入。
