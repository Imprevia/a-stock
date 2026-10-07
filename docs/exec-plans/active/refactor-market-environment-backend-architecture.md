# 市场环境后端分层重构

## Stage

Stage 5/8 — dataset collector 抽取；Stage 4 PostgreSQL repository、unit-of-work 与 Alembic compatibility migration 已完成。

## Status

in-progress（OpenSpec apply 34/51；任务 5.5 已完成，下一步抽取 5.6 LimitsCollector）

## Scope

- 将 `src/market_environment/` 重构为 `bootstrap`、`interfaces`、`application`、`domain`、`infrastructure` 五层模块化单体。
- 保持 `src.market_environment.api:app`、`python -m src.market_environment.cli`、现有 HTTP 路径、JSON 字段、状态码和数据集 ID 兼容。
- 普通 GET、状态和 next-session 查询继续只读本地精确日期证据，禁止触发 provider。
- 将五类采集拆为独立 collector，同时保持 provider 顺序、日期能力、质量状态、warning、失败留存和兄弟任务隔离。
- 将快照、任务、lease、交易日、聚合、能力报告、limits fact 和时区偏好拆为 repository，但原子操作继续共用 PostgreSQL unit of work。
- PostgreSQL 是唯一正式运行时存储；SQLite 仅作为测试或停写迁移输入；运行时 schema 继续由 Alembic 管理，并通过非破坏性 `0003_provider_capability_reports` 明确 version 6/provider capability schema 所有权。
- 同步校准调度默认 `enabled=false`、`suspend=true` 及 Dashboard/CronJob 共用 PostgreSQL 的文档和 OpenSpec 事实。
- 不引入微服务、Celery、Kafka、新 provider、新业务指标或破坏性数据库迁移。
- 本计划不授权真实 provider smoke、生产 PostgreSQL 写入、TrueNAS/k3s/Helm 写操作、CronJob 激活、feature flag 启用或远端分支变更。

## Stages

1. 建立 active plan、架构事实源、调度/存储契约和离线特征基线。
2. 引入配置、composition container、`create_app`、lifespan、router 和 CLI 装配边界。
3. 建立 typed application values、ports、provider-free query 与 command use case。
4. 拆分 PostgreSQL repository/unit of work，收缩 SQLite 到 legacy/test/migration adapter。
5. 按 core、breadth、activeDirection、sectors、limits 顺序抽取 collector。
6. 拆分 aggregate、core/breadth/limits analysis 和 API response mapper。
7. 移除运行时旧 facade，增加 AST/import 架构门禁和完整兼容矩阵。
8. 同步文档、运行全量离线验证并完成计划证据。

## Acceptance

- OpenSpec tasks 51/51 完成，strict validation 通过。
- `api:app` 和 CLI 入口兼容；导入入口不连接数据库、不建表、不请求 provider、不提交线程任务。
- HTTP 路由、Pydantic schema、现有响应字段和错误状态码保持兼容。
- 普通 GET、collection status 和 next-session provider 调用数为 0，warm local read 维持小于 500ms 的既有门槛。
- 五类 collector 的来源、fallback、日期证据、质量状态、warning、observations、失败留存和 partial 行为与基线一致。
- PostgreSQL lease/fencing、checksum、task transition、materialized aggregate CAS 和 limits fact 事务边界通过回归。
- 运行时不调用 `create_schema`，不静默回退 SQLite；Alembic `0003_provider_capability_reports` 可从现有 head 前向升级到 schema version 6，且不重写既有表、payload 或 checksum。
- 架构门禁可阻止 domain/application 反向依赖、router 直接装配基础设施及 query 导入 provider。
- 后端全量 pytest、OpenSpec strict、docs-contract full 和 `git diff --check` 通过。
- 未访问真实 provider、生产数据库或 Kubernetes 写入口，未修改生产调度和 feature flag。

## Baseline Evidence

- 规划：`refactor-market-environment-backend-architecture` 的 proposal、delta spec、design、tasks 已生成；2026-10-06 strict validation 通过。
- 工作区起点：仅存在未提交的本 change OpenSpec 规划目录；无其他业务代码修改。
- 重构前物理行数（UTF-8 `splitlines()`）：`snapshot_store.py` 2896、`providers.py` 2862、`service.py` 1544、`collection.py` 1534，合计 8836 行。
- 重构前包内 AST 导入耦合（`source_fan_in/source_fan_out`）与直接测试导入者数：`snapshot_store` 为 `8/6`、15 个测试模块；`providers` 为 `4/7`、7 个；`service` 为 `2/7`、7 个；`collection` 为 `2/10`、8 个。统计只计算 `src.market_environment` 内直接模块导入，不把标准库、第三方库或传递依赖计入。
- focused 测试收集：`.venv\\Scripts\\python.exe -m pytest tests --collect-only -q -k market_environment` 为 `426/778 tests collected (352 deselected) in 2.15s`，其中包含本变更新增的 6 个 API 特征测试。
- provider-free 断言：materialized aggregate、next-session、collection status、degraded status 和 failed-retained status 五条精确日期读路径均以会记录调用的 fake provider 执行；`.venv\\Scripts\\python.exe -m pytest ... -q` 为 `5 passed in 1.03s`，provider 调用数均为 0。
- warm-read 基线：使用临时 SQLite fixture、fake limits provider 和已物化聚合执行 100 次 `service.get(CURRENT)`；min `8.9659ms`、median `10.2877ms`、p95 `13.2140ms`、max `54.5817ms`，100 次读取新增 provider 调用数为 0，低于既有 500ms 门槛。
- 基线采集范围：仅执行 AST/文件统计、pytest 收集、本地 TestClient/fake provider 和临时 SQLite；未访问真实 provider、生产 PostgreSQL、Kubernetes、Helm release 或远端服务。

## Rollback

- 每阶段先建立兼容 seam，再切换调用方，最后删除旧路径；任何阶段失败时恢复上一阶段 composition/facade wiring，不修改 PostgreSQL 已有数据。
- 本变更不包含生产部署，因此不执行 Helm/kubectl/数据库生产回滚。后续生产 rollout 必须另建受审计划并获取外部写入授权。
- 不使用 `git reset --hard`、PVC 删除、release uninstall 或跨日期数据替换作为清理手段。

## Completion Evidence

- 已完成：OpenSpec 规划产物 4/4，strict validation 通过，设计明确渐进迁移和无生产写入边界。
- Stage 1 文档：`docs/architecture.md` 与 `docs/repository-guide.md` 已先于代码记录目标分层；runbook/product 已校准 PostgreSQL 与 fail-closed 调度文字。
- 调度离线 focused：`.venv\\Scripts\\python.exe -m pytest tests/test_deployment_manifests.py -q -k "fail_closed_configurable_scheduled_collection or component_schedule_renders_only_suspended_cronjob or sqlite_import_job_is_explicit_read_only_and_secret_backed or render_supports_disabled_suspended_and_custom_native_schedule"` 为 `1 passed, 3 skipped, 184 deselected`；Helm CLI 相关案例在本机缺少 Helm 时按既有 skip 条件跳过，直接 values 默认值断言通过，未访问集群。
- API 特征契约：新增 `tests/test_market_environment_api_characterization.py`，冻结 success、partial、missing、degraded、failed-retained、503 和 422 响应中的路径、alias、状态码、source、warning、精确日期与 quality 字段；`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_api.py tests/test_market_environment_api_characterization.py -q` 为 `24 passed in 1.78s`。
- Stage 1 基线：四个热点模块合计 8836 行；focused 测试 426 条；五条 provider-free 精确日期读断言通过；100 次 warm read 的 p95 为 `13.2140ms`、max 为 `54.5817ms` 且新增 provider 调用为 0。
- Stage 2 骨架：新增 `bootstrap`、`interfaces`、`application`、`domain`、`infrastructure` 包及无资源构造的 immutable `MarketEnvironmentSettings`；`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_bootstrap.py tests/test_market_environment_database.py -q` 为 `12 passed, 3 skipped in 0.80s`，3 条 PostgreSQL integration 按既有环境条件跳过。
- Stage 2 container：新增 `ApplicationContainer`、独立 `ReadDependencies`/`CommandDependencies` 和 legacy adapter seam，并为 service/coordinator 加入可注入 executor/analysis seam；`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_bootstrap.py tests/test_market_environment_api.py tests/test_market_environment_collection.py -q` 为 `49 passed in 4.41s`，fake repository、collector、clock、executor 构造及关闭行为通过。
- Stage 2 app factory：新增 `bootstrap.app.create_app` 和 lifespan container ownership，`src.market_environment.api:app` 保持稳定；导入守卫会在 database/store/provider/schema/executor 被构造时立即失败，且验证导入不创建 SQLite 文件；`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_bootstrap.py tests/test_market_environment_api.py tests/test_market_environment_api_characterization.py -q` 为 `30 passed in 3.18s`。
- Stage 2 routers：health、market-environment、collection、timezone-preference 已拆为独立 router，HTTP dependency functions 使用 Protocol 类型，RuntimeError/ValueError 与 403/404/422 映射集中在 `interfaces/http/errors.py`；OpenAPI 路径/方法/response model/success status 固定测试通过，`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_bootstrap.py tests/test_market_environment_api.py tests/test_market_environment_api_characterization.py tests/test_market_environment_limit_contract.py tests/test_market_environment_limit_promotion.py -q` 为 `90 passed in 7.01s`。
- Stage 2 API test seams：新增 `tests/market_environment_api_support.py`，API/characterization/limits 测试全部通过 `create_app().dependency_overrides` 注入 query、command、clock fake；`api.py` 已删除 mutable service/coordinator/executor/timezone globals，并有显式断言；同一组 API/limit/bootstrap 测试为 `91 passed in 6.96s`。
- Stage 2 CLI：新增 `interfaces.cli.container.build_cli_container`，复用同一 settings 与 `build_container` lower-level factory，但导入链不含 FastAPI；refresh/scheduled-refresh 使用显式 scope 并关闭自建 container，help 与离线 capability fixture 不构造 runtime；`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_cli_bootstrap.py tests/test_market_environment_collection.py tests/test_market_environment_fuyao_collection_integration.py -q` 为 `45 passed in 4.55s`。
- Stage 2 entry points：`uvicorn` 的 `src.market_environment.api:app` 与 `python -m src.market_environment.cli --help` 均在 subprocess 中离线导入且不创建配置的 snapshot 文件；lifespan 对 fake executor 调用 shutdown，并对 database repository engine 调用 dispose；`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_bootstrap.py tests/test_market_environment_cli_bootstrap.py -q` 为 `12 passed in 4.71s`。
- Stage 3 values：新增 dataset/date、candidate/outcome、quality/cache、run/task state、materialization revision typed values 及 API quality/snapshot storage 双向 mapper；`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_domain_values.py tests/test_market_environment_snapshot_store.py tests/test_market_environment_api_characterization.py -q` 为 `22 passed in 1.47s`，现有存储 record 与 API quality shape round-trip 等价。
- Stage 3 ports：新增 snapshot/run/task/lease/session/aggregate/capability/limits/timezone repositories、shared unit-of-work、dataset collector 和 task executor Protocol；AST 与 subprocess 测试禁止 FastAPI、SQLAlchemy、requests、bootstrap/interfaces/infrastructure 及旧 concrete modules 进入 ports；`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_application_ports.py tests/test_market_environment_domain_values.py -q` 为 `7 passed in 0.41s`。
- Stage 3 compatibility adapters：`SnapshotStore` 通过 typed candidate mapper 实现 snapshot repository seam，`MarketDataProvider` + `CollectionCoordinator` 通过 dataset collector adapter 暴露 typed outcome，service/coordinator query/command adapter 已接入 container；adapter/port/bootstrap 测试为 `14 passed in 3.24s`，`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_service.py tests/test_market_environment_collection.py tests/test_market_environment_providers.py -q` 为 `88 passed in 4.32s`。
- Stage 3 provider-free market queries：新增 full aggregate、core、Chapter 01 与 next-session query use case；构造函数仅接受 read ports 和纯 `review_evidence_builder`，聚合缺失不会在读取中重建或写入，snapshot identity、`actual_as_of`、payload `asOf` 均执行精确日期校验；query AST 禁止 provider/collector/infrastructure 导入。目标测试为 `12 passed in 0.79s`；service/next-session/API/characterization/adapter/bootstrap 回归为 `71 passed in 5.99s`。
- Stage 3 status/timezone use cases：新增 collection-status、run-status、timezone-preference query 与 timezone update command，并将 timezone port 拆成显式 reader/writer；用例构造关系不暴露 provider/collector/coordinator/executor，错误日期状态会 fail closed。`.venv/Scripts/python.exe -m pytest tests/test_market_environment_status_queries.py tests/test_market_environment_queries.py tests/test_market_environment_application_ports.py -q` 为 `15 passed in 0.21s`；API/collection/bootstrap/adapter 回归为 `58 passed in 7.54s`。一次附带不存在的 timezone 专用测试文件命令未收集测试，随后使用仓库实际测试文件完成验证。
- Stage 3 command use cases/executor：新增 start-run、execute-run、submit-run、dataset refresh、aggregate rebuild command，并扩展 legacy adapter 保持同步 refresh 行为；新增 `BoundedTaskExecutor`，以非阻塞容量门禁限制 running + queued work，支持幂等 shutdown。`.venv/Scripts/python.exe -m pytest tests/test_market_environment_commands.py tests/test_market_environment_application_ports.py tests/test_market_environment_compatibility_adapters.py tests/test_market_environment_api.py -q` 为 `29 passed in 2.10s`，POST 继续返回 202、run 为既有 `collecting`、task 为 `queued`，no-op executor 下 provider 调用为 0；collection/CLI/bootstrap/API characterization 回归为 `45 passed in 7.40s`。
- Stage 3 wiring：HTTP/CLI container 继续暴露兼容协议，但 `LegacyMarketEnvironmentQueryAdapter`、collection/status、timezone、aggregate 与 refresh adapters 内部已调用新 use case；CLI `coordinator` 属性改为 command adapter，保留 `collect`/history compatibility；collection runtime executor 切换为 `BoundedTaskExecutor`。API/collection/CLI/next-session/service 回归为 `91 passed in 7.46s`，Fuyao/limits 回归为 `74 passed in 4.96s`；docs-contract fast 与 `git diff --check` 均为退出码 0（仅现有 Windows LF→CRLF 提示）。
- Stage 4 PostgreSQL connection/UoW：新增 read-only runtime schema compatibility check（连通性、12 张必需表、最小 schema version 6）与共享 `READ COMMITTED` transaction UoW；显式 commit，异常/遗漏 commit 自动 rollback，repository factory 接收同一 connection。`.venv/Scripts/python.exe -m pytest tests/test_market_environment_postgres_uow.py tests/test_market_environment_database.py tests/test_market_environment_application_ports.py -q` 为 `17 passed, 3 skipped in 0.47s`，skip 均为未配置真实 PostgreSQL 的既有 integration case；新 runtime 模块不导入 `create_schema`，捕获 SQL 全部为 SELECT。
- Stage 4 snapshot/session/capability repositories：新增共享 connection 的 `PostgresSnapshotRepository`、`PostgresTradingSessionRepository`、`PostgresProviderCapabilityRepository`；写入前校验 dataset/actual/payload/quality 精确日期，读取校验 payload/session/capability checksum，snapshot 日期倒序列举、session `after` 过滤、capability revision immutable/filter list 均有 contract 覆盖。新 repository/UoW/port 测试为 `12 passed in 0.46s`（仅 SQLAlchemy Python 3.14 SQLite fixture adapter deprecation warning），既有 snapshot/capability/limit-facts/next-session 回归为 `39 passed in 1.06s`。
- Stage 4 run/task/core-index repositories：新增 collection run 合法状态机、task expected-status 原子迁移、latest/active 查询、无有效 lease 的 restart recovery，以及 core-index result upsert/list；恢复任务按同日期 snapshot 是否存在区分 `failed-retained` / `failed-missing`。新 repository/基础 contract 为 `16 passed in 0.39s`（仅 SQLite fixture adapter deprecation warning），既有 collection/snapshot/API lifecycle 为 `59 passed in 4.78s`。
- Stage 4 lease/fencing repository：新增 advisory-lock + row-lock PostgreSQL acquisition、generation ledger、opaque token、renew/release、validity assertion、同 connection fenced writer 与 fingerprint-only fence event；过期接管 generation 单调增加且 ledger 永不保存明文 token。`.venv/Scripts/python.exe -m pytest tests/test_market_environment_postgres_lease_repository.py tests/test_market_environment_postgres_collection_repositories.py tests/test_market_environment_postgres_uow.py tests/test_market_environment_application_ports.py -q` 为 `14 passed, 1 skipped in 0.37s`，skip 为未配置显式 PostgreSQL test URL 的 advisory-lock concurrency；既有 snapshot/collection/limits/date-relabel 回归为 `68 passed in 3.55s`。
- Stage 4 aggregate CAS repository：新增精确日期 materialized read/checksum、完整 component-state revision hash、PostgreSQL component table SHARE lock 与 compare-and-swap；payload `_componentRevision` 必须与 CAS token 一致，serialization failure 归一为 domain conflict，optional lease 可复用同 connection fenced writer。aggregate/lease/UoW/query contract 为 `17 passed, 1 skipped in 0.36s`；既有 service/limit promotion/performance/API materialization 回归为 `56 passed in 7.15s`。
- Stage 4 limits repository：新增共享 connection 的 `PostgresLimitDetailRepository`，manifest、facts replacement 与 checksum 在调用方同一 transaction 内提交；写入校验精确日期、row/dataset checksum 与 excluded count，读取重新验证完整数据集并识别篡改。limit repository/aggregate/UoW/port contract 为 `14 passed in 0.41s`；既有 limit contract/fixture/facts/promotion/performance/date-relabel 回归为 `102 passed in 5.87s`。
- Stage 4 timezone repository：新增共享 connection 的 `PostgresTimezonePreferenceRepository`，保留 personal/workspace key 规则、IANA 校验、无变化不追加 audit、PostgreSQL advisory transaction lock 与 row lock；repository rollback、HTTP workspace authorization 和 browser fallback 一并验证。timezone/status/API/UoW/port 回归为 `37 passed in 2.14s`。
- Stage 4 compatibility facade：公开 `SnapshotStore` 仅保留 backend 注入、`from_backend` 与属性委托，原混合实现显式命名为 `LegacySnapshotStoreAdapter`；AST contract 断言 facade 类体不含 SELECT/INSERT/UPDATE/DELETE，application package 不直接依赖 facade。snapshot/collection/service/date-relabel/compatibility 回归为 `83 passed in 5.19s`。
- Stage 4 SQLite/runtime boundary：新增惰性加载的 `infrastructure.persistence.sqlite_import.LegacySqliteSnapshotStore`，CLI 显式 `--path` 分支改用该 adapter；无参 `SnapshotStore` 和无 database/adapters 的正常 container 均 fail closed，PostgreSQL 与 sqlite_import package exports 改为惰性加载以保持骨架导入无 legacy 副作用。bootstrap/CLI/snapshot/API/date-relabel/database 回归为 `70 passed, 3 skipped in 5.78s`。
- Stage 4 repository-contract audit：任务 4.10 的 schema 核对发现 Alembic head 仅有 `0001_postgresql_initial` 与 `0002_limit_membership_details`，其中 `0002` 只登记 schema version 5；runtime `PostgresConnectionFactory` 明确要求 version 6 和 `provider_capability_reports`，而 version 6/table 目前仅由可变的 `create_schema` helper 补齐。该事实不能证明“无需 migration”，也与 Alembic authoritative/runtime 不执行 DDL 的目标冲突，因此 4.10 未勾选。
- 暂停前自检：全部新 PostgreSQL repository/UoW/port 测试为 `28 passed, 1 skipped in 0.69s`，skip 为未配置显式 PostgreSQL concurrency URL；`git diff --check` 退出码 0（仅 LF→CRLF 提示）；docs-contract fast 退出码 0，但因大量新增文件尚未跟踪而报告“无变更”，不作为最终门禁证据。
- Stage 4 Alembic/repository contracts：新增非破坏性 `0003_provider_capability_reports`，Alembic runtime 删除 `create_schema` bootstrap；migration contract 固定 revision 链、capability table/column/primary-key/index、schema version 6 ledger、无 ALTER/DROP/UPDATE/DELETE/TRUNCATE 及非破坏性 downgrade。共享 snapshot repository contract 同时覆盖显式 legacy SQLite adapter 与 PostgreSQL repository 的 exact-date put/get、missing、date list、payload/source/status/observations/warnings/settled/quality round-trip 和 checksum 篡改识别；另新增仅由 `MARKET_ENVIRONMENT_TEST_DATABASE_URL` 启用的真实 PostgreSQL commit/rollback 与 stale fencing 验证。focused 结果为 `21 passed, 3 skipped in 1.28s`，完整 repository 回归为 `35 passed, 3 skipped in 1.03s`；3 个 skip 均因未配置显式隔离 PostgreSQL test URL，未访问生产数据库。
- Stage 5 collector registry：新增 application `DatasetCollectorRegistry`，按 `core`、`breadth`、`limits`、`sectors`、`activeDirection` 稳定顺序解析 collector；unsupported、duplicate、incomplete 和 unknown lookup 都以确定消息 fail closed。`build_legacy_provider_collector_registry` 将既有 provider/coordinator 路径装入完整 registry，不改 fallback 算法；registry/compatibility/ports/current collection 回归为 `36 passed in 5.01s`。
- Stage 5 CoreCollector：将五指数采集、当前日独立报价校验、Fuyao formal/shadow 与既有 provider 回退、逐指数 sub-result 审计、同日期 retained、session evidence 和 snapshot/task 结果组装机械迁入 `infrastructure.providers.CoreCollector`；`CollectionCoordinator._collect_core` 收缩为单行委托并保留注入 seam。core/index/quote/history focused 为 `15 passed, 56 deselected in 2.07s`，完整 provider/Fuyao/collection/registry/compatibility 回归为 `77 passed in 5.48s`。
- Stage 5 BreadthCollector：将 Fuyao formal/shadow gate、既有 provider 的 TDX daily package/stock-universe/Eastmoney fallback 调用、exact-date quality 校验、missing/insufficient 处理及 snapshot/task 组装迁入 `infrastructure.providers.BreadthCollector`；coordinator 不再含 breadth provider 分支。breadth/TDX/universe focused 为 `44 passed, 66 deselected in 5.11s`，完整 collection/Fuyao/TDX/provider/registry/compatibility 回归为 `116 passed in 8.78s`。
- Stage 5 ActiveDirectionCollector：将既有 provider 内 Eastmoney primary/delay 与独立 capability gate 的 TDX-derived fallback 调用、ranking metadata、`fallback-derived`→partial 映射、exact-date quality 与 snapshot/task 组装迁入 `infrastructure.providers.ActiveDirectionCollector`；未引入 Fuyao 路由。focused 为 `18 passed, 92 deselected in 0.82s`，完整 collection/Fuyao/TDX/provider/registry/compatibility 回归为 `116 passed in 8.42s`。
- Stage 5 SectorsCollector：将 Eastmoney primary/delay、capability-gated Fuyao fallback、当前上海交易日且结算后的可选 dataapi enrichment、lineage/timing 与 shadow 迁入 `infrastructure.providers.SectorsCollector`；coordinator 删除原 sector/enrichment 方法。focused 为 `15 passed, 56 deselected in 1.06s`，完整 collection/Fuyao/TDX/provider/registry/compatibility 回归为 `116 passed in 8.24s`。
- 待完成：17 项 apply 任务、limits collector/coordinator 收缩与 query decomposition、focused/full tests、完整架构门禁、docs-contract full 和最终 scope review。

## Remaining Gaps

- compatibility adapters 仍委托 `SnapshotStore`、`MarketEnvironmentService` 与 `CollectionCoordinator`；core 算法已进入独立 collector，但 registry 仍通过 legacy adapter 调用 coordinator，需由任务 5.3–5.7 继续替换并最终移除旧 facade。
- application container 的正常路径已要求 PostgreSQL，但仍通过过渡 facade 构造旧 PostgreSQL backend；新 connection factory/UoW 的完整 runtime wiring 与 `create_schema` 移除仍待后续 facade cleanup，不能视为最终生产装配完成。
- Alembic `0003_provider_capability_reports` 与 shared repository contracts 已实现；真实 PostgreSQL transaction/concurrency/fencing integration 仅在显式隔离 test URL 下运行，本机未配置该 URL，因此相关 3 个 integration case 本轮按安全门控跳过。
- `snapshot_store.py`、`providers.py`、`service.py`、`collection.py` 仍为迁移期混合职责模块，Stage 4–6 需按 repository、collector 与 analysis 边界拆分。
- 当前仅有 ports/query 局部 AST 约束，完整分层、bootstrap-only assembly 与 thin entry-point 架构门禁尚待任务 7.1。

## Next Step

实施任务 5.6：最后抽取 `LimitsCollector`，保持 Fuyao/Eastmoney membership merge、日期证据、normalization、facts、promotion dependency、失败留存和 transactional detail writes。
