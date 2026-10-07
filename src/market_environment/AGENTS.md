# `src/market_environment` 目录说明

适用范围：本文件及其子目录。本文档记录当前代码布局、运行时边界和重构后的兼容面，更新时间为 2026-10-07。

## 先说结论

这个目录不是“重构后可以整体删除的旧目录”。它现在是一个已完成主要分层、但仍保留稳定导入和数据迁移兼容面的模块化单体。判断文件是否还在使用时，不能只看文件是否位于根目录，也不能只看文件名里有没有 `legacy`：

- `bootstrap/`、`interfaces/`、`application/`、`domain/`、`infrastructure/` 组成当前目标架构。
- `api.py`、`cli.py`、`collection.py`、`schemas.py`、`database.py` 等根文件仍是稳定入口或过渡装配面，不能按“旧文件”处理。
- `infrastructure/legacy/service.py` 不再由正常 HTTP 查询路径装配；但 `infrastructure/legacy/providers.py` 和 `infrastructure/legacy/snapshot_store.py` 仍通过兼容 shim 被当前采集器或 PostgreSQL 运行时适配器传递使用，不能直接删除。
- 根目录的 `service.py`、`providers.py`、`snapshot_store.py` 是稳定导入 shim，不应继续添加业务逻辑，也不应仅因代码很短而删除。
- SQLite 只允许出现在显式测试、停写迁移、日期重标记或诊断路径；正常运行时必须使用 PostgreSQL，普通 GET 不得触发 provider 采集。

事实源和变更背景见：

- `docs/architecture.md`
- `docs/repository-guide.md` 的“市场环境后端内部地图”
- `docs/runbooks.md` 的采集、迁移、部署和故障处理章节
- `docs/exec-plans/active/refactor-market-environment-backend-architecture.md`

## 当前运行链路

### HTTP

```text
src.market_environment.api:app
  -> bootstrap.app.create_app
  -> bootstrap.container.build_container
  -> interfaces.http routers/dependencies/mappers
  -> application queries/commands
  -> domain 纯模型与分析
  -> infrastructure PostgreSQL repositories / provider collectors / executor
```

普通市场环境 GET、collection status 和 next-session 查询必须 provider-free：只读取本地精确日期快照或 materialized aggregate，缺数据时返回 `pending`、`missing` 或 `insufficient`，不得跨日期补齐，也不得偷偷启动采集。

### CLI

稳定入口是 `python -m src.market_environment.cli`。CLI 通过 `interfaces/cli/container.py` 复用同一个 bootstrap container，但仍保留显式的迁移、日期重标记、Fuyao/TDX capability probe 等运维命令。CLI 中出现的旧类型导入不等于普通 API 运行时会走旧 service；具体以命令分支和 `build_cli_container` 为准。

### 采集与存储

```text
collection.CollectionCoordinator
  -> application.collection.DatasetCollectorRegistry
  -> infrastructure.providers/{core,breadth,limits,sectors,active_direction}
  -> provider transport / fallback / quality checks
  -> PostgreSQL-backed snapshot, task, lease and aggregate persistence
```

生产运行时存储边界是 PostgreSQL。`PostgresRuntimeStore` 当前仍复用兼容性的 snapshot store 实现作为存储 facade，再由 PostgreSQL URL 选择 PostgreSQL backend；这属于渐进式迁移的兼容 seam，不是允许新增 SQLite 回退的理由。

## 状态标签

目录清单使用以下标签：

- **运行时主路径**：正常 HTTP/CLI/采集请求会经过，修改需同步架构和 runbook。
- **运行时支撑 / 过渡**：当前运行时仍会用到，但职责正在向新分层迁移；应保持兼容，不要继续扩大旧耦合。
- **纯领域 / 共享算法**：无网络和持久化副作用，可被多层调用。
- **显式维护 / 迁移**：只在明确的本地命令、迁移、probe 或测试中使用，不属于普通请求路径。
- **兼容 shim / legacy**：为了稳定导入、历史测试或旧数据迁移而保留；是否可删除必须先完成调用方迁移并更新 active plan。

## 子目录地图

| 路径 | 当前职责 | 状态与边界 |
|---|---|---|
| `bootstrap/` | 环境配置、composition container、FastAPI app factory、lifespan、资源关闭 | **运行时主路径**；唯一具体装配位置。不得在 router/query 中自行构造 provider、repository 或 executor。 |
| `interfaces/http/` | HTTP router、依赖、时区/身份上下文、错误映射、响应 DTO mapper | **运行时主路径**；只依赖 application/domain。 |
| `interfaces/cli/` | CLI 到 application command/query 的装配边界 | **运行时主路径**；不得因为 CLI 有维护命令而把网络或数据库副作用放到 import 阶段。 |
| `application/ports/` | repository、unit-of-work、collector、executor 等 Protocol | **运行时主路径**；只定义边界，不放具体 SQL、HTTP 或 FastAPI 逻辑。 |
| `application/queries/` | provider-free 的市场环境、状态、next-session、时区和 limits 查询 | **运行时主路径**；禁止导入 provider、collector 或 infrastructure。 |
| `application/commands/` | collection run、dataset refresh、aggregate rebuild、时区更新 | **运行时主路径**；写操作必须经 port 和明确 command。 |
| `application/collection/` | 五个稳定数据集 ID 的 registry 和确定性查找 | **运行时主路径**；数据集顺序和 ID 是稳定接口。 |
| `domain/models/` | 数据集、日期、质量、任务状态、采集结果和 revision 等类型化值 | **纯领域 / 共享算法**；不依赖 FastAPI、SQLAlchemy、requests 或 infrastructure。 |
| `domain/analysis/` | 指数、广度、动量、分位数、一致性和标签等纯计算 | **纯领域 / 共享算法**；不得读取数据库或调用 provider。 |
| `domain/policies/` | limits promotion 质量叠加等确定性策略 | **纯领域 / 共享算法**。 |
| `infrastructure/providers/` | 五类 dataset collector、Fuyao/TDX/Eastmoney 降级、质量和 shadow 证据 | **运行时主路径**；只能通过 application collector port 进入，不得被 query 直接调用。 |
| `infrastructure/persistence/postgres/` | PostgreSQL connection、UoW、snapshot/task/lease/aggregate/limits/timezone repositories | **运行时主路径**；生产唯一正式存储，禁止静默切到 SQLite。 |
| `infrastructure/persistence/sqlite_import/` | 停写迁移或显式 fixture 的 SQLite adapter | **显式维护 / 迁移**；不允许进入无参数的普通 runtime composition。 |
| `infrastructure/execution/` | 有界进程内 task executor | **运行时主路径**；负责 running + queued 容量门禁和幂等关闭。 |
| `infrastructure/compatibility.py` | 新 ports/use cases 与旧 coordinator/store 之间的 typed adapter | **运行时支撑 / 过渡**；是渐进迁移 seam，不是新业务逻辑存放处。 |
| `infrastructure/materialization_support.py` | provider-free materialized aggregate 组装和缓存元数据 | **运行时主路径**；只使用本地快照、纯分析和 schema 校验。 |
| `infrastructure/materialized_aggregate_factory.py` | aggregate composer/rebuilder 的构造 | **运行时主路径**。 |
| `infrastructure/legacy/` | 旧 provider、旧 service、兼容 snapshot store 的物理实现 | **兼容/过渡**；三个文件的使用情况不同，见下一节，不能整体视为死代码。 |

## 根目录 Python 文件清单

根目录文件是历史兼容面和新架构之间的交界。新增逻辑应优先放入对应子包，而不是继续把根文件变成“大杂烩”。

### 根目录白名单与新增规则

当前根目录的 `.py` 文件均属于本文件下方的逐文件清单，形成迁移期间的显式白名单。白名单只登记现有稳定入口、运行时过渡面、共享兼容导出和显式维护脚本；它不是新业务代码的默认落点。

- 新增 HTTP 路由、查询、命令、领域计算、provider、持久化、DTO 或迁移实现时，必须放入既有 `interfaces/`、`application/`、`domain/` 或 `infrastructure/` 子包。
- 新增根目录 `.py` 默认视为架构违规；只有新的稳定公共入口或经评审的兼容 shim 才能加入白名单，并且必须同时记录状态、目标归属、调用方和删除前置条件。
- 根级 shim 只能转发、重导出、保留别名或承接稳定入口，不得新增 SQL、provider 请求、业务分支、线程提交或资源装配。
- 迁移完成后应逐项缩减白名单；删除根级模块前必须先完成调用方迁移、兼容矩阵和 active plan 证据。

布局门禁以本清单为人工事实源，并额外校验根目录是否出现未登记模块；门禁失败时应指出目标子包和登记位置，不得通过删除测试或放宽依赖规则绕过。

### 入口、装配和公共契约

| 文件 | 状态 | 说明 |
|---|---|---|
| `api.py` | **运行时主路径** | 稳定的 Uvicorn 入口，只负责导出 `app = create_app()`；保持薄，不要在此连接数据库或请求 provider。 |
| `cli.py` | **运行时主路径 + 显式维护入口** | `python -m ...cli` 的稳定入口，包含 snapshots/database/fuyao/tdx 等命令解析；导入兼容类型是历史 CLI 合同的一部分。 |
| `collection.py` | **兼容 shim** | `CollectionCoordinator` 实现已迁到 `infrastructure/collection/coordinator.py`；bootstrap、CLI 和 adapter 使用目标路径，根路径只保留稳定导出。五类采集实现仍位于 `infrastructure/providers/`。 |
| `schemas.py` | **兼容 shim** | 实现已迁到 `interfaces/http/schemas/models.py`；根路径只保留 HTTP/API 响应模型的稳定导出，字段兼容性由 API golden/characterization 测试保护。 |
| `database.py` | **运行时主路径** | PostgreSQL 配置、engine 创建和连接检查；禁止把 SQLite URL 重新加入正常 runtime 配置。 |
| `refresh.py` | **兼容 shim** | 上海时区、effective market date、settlement boundary 和 `SnapshotRefresher` 已迁到 `infrastructure/collection/refresh.py`；根路径只保留稳定导出，日期边界仍由目标模块维护。 |

### 共享计算、时区和交易日

| 文件 | 状态 | 说明 |
|---|---|---|
| `calculations.py` | **兼容 shim** | 实现已迁到 `domain/analysis/calculations.py`；根路径只保留稳定导出，adapter、Fuyao market 和测试仍可通过旧路径导入。 |
| `trading_sessions.py` | **运行时支撑** | 交易日解析和 limits 历史会话边界；缺失交易日必须返回明确状态，不得用自然日或其他日期冒充。 |
| `timezone_preferences.py` | **运行时主路径** | 时区偏好存储、校验和审计；API 通过 application query/command 访问。 |

### Provider、降级和能力证据

| 文件 | 状态 | 说明 |
|---|---|---|
| `fuyao.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/fuyao/limits_client.py`；根路径仅保留 limits 客户端稳定导出，真实访问仍只允许显式盘后 probe 或采集命令。 |
| `fuyao_market.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/fuyao/market.py`；core/breadth/sectors 的生产调用均使用目标路径。 |
| `fuyao_config.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/fuyao/config.py`；dataset 级开关仍默认 fail closed。 |
| `fuyao_request_gate.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/fuyao/request_gate.py`；两个 Fuyao 客户端继续共享同一进程级请求门。 |
| `tdx_config.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/tdx/config.py`；TDX fallback 与派生开关不变。 |
| `tdx_daily.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/tdx/daily_package.py`；普通 GET 不调用，只有 collector 或显式 `tdx real-probe` 使用。 |
| `provider_capability.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/capability.py`；保留 capability report 的稳定导出，不能把 `unverified` 升级为成功。 |
| `provider_shadow.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/shadow.py`；collector 通过目标子包记录非破坏性 shadow evidence。 |
| `sector_enrichment.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/sector_enrichment.py`；保留旧导入，不能放宽保守匹配条件。 |
| `industry_mapping.py` | **兼容 shim** | 实现已迁到 `infrastructure/providers/industry_mapping.py`；保留版本化 identity boundary 的旧导入。 |

### 涨跌停生态

| 文件 | 状态 | 说明 |
|---|---|---|
| `limit_facts.py` | **兼容 shim** | 实现已迁到 `domain/policies/limit_facts.py`；保留涨跌停明细标准化、checksum 和事实记录的旧导入。 |
| `limit_promotion.py` | **运行时支撑** | promotion 规则、feature gate 和质量状态聚合；缺失/不完整证据不得伪造成成功。 |
| `limit_ecosystem.py` | **运行时支撑** | 本地 limits membership/facts 的生态组合，供 materialization 和 application query 使用。 |

### 存储兼容、迁移和日期维护

| 文件 | 状态 | 说明 |
|---|---|---|
| `snapshot_store.py` | **兼容 shim** | 从 `infrastructure/legacy/snapshot_store.py` 导出稳定类型和 `SnapshotStore`；新代码不要在这里加实现。 |
| `postgres_compat.py` | **兼容 shim** | 实现已迁到 `infrastructure/persistence/postgres/compat.py`；继续作为旧 qmark/row 导入面，不是第二个存储后端。 |
| `postgres_schema.py` | **显式维护 / 迁移** | 历史 schema bootstrap/helper；正式 schema 所有权以 Alembic 和 runbook 为准，runtime 不得重新调用 `create_schema`。 |
| `postgres_migration.py` | **兼容 shim** | 实现已迁到 `infrastructure/persistence/sqlite_import/migration.py`；只读 SQLite fingerprint、备份和显式导入不会由普通 API 请求调用。 |
| `date_relabel.py` | **兼容 shim** | 实现已迁到 `infrastructure/persistence/sqlite_import/date_relabel.py`；默认 dry-run，必须显式 `--apply` 才写入。 |
| `snapshot_migration.py` | **兼容 shim** | 旧日期迁移导入名，转发到 `date_relabel.py`；保持历史脚本和测试兼容。 |

### 根级兼容导入

| 文件 | 状态 | 说明 |
|---|---|---|
| `providers.py` | **兼容 shim** | 转发到 `infrastructure/legacy/providers.py`。当前 collector runtime 仍通过 `CollectorProviderRuntime` 间接使用其中的 vendor transport，因此不能直接删除；新 provider 逻辑应放到 `infrastructure/providers/`。 |
| `service.py` | **兼容 shim** | 转发到 `infrastructure/legacy/service.py`。正常 bootstrap query/materialization 不构造 `MarketEnvironmentService`，但旧测试、外部脚本和交易系统数据适配仍可能导入它。 |
| `__init__.py` | **包入口** | 只保留包说明和稳定的最小导出，避免导入时产生 I/O。 |

## 根级 shim 退役矩阵

根级 shim 的保留不代表新代码可以继续依赖它。架构门禁禁止 production 子包新增对已迁移根实现的引用；当前只登记以下过渡例外：`infrastructure` 的 materialization/limits/legacy service 仍经 `schemas.py` 校验 HTTP DTO，HTTP dependency 仍经 `refresh.py` 读取 effective market date，collection router 仍经 `collection.py` 读取 manual-refresh 开关。这些例外是明确的迁移债务，不是新增依赖的模板。

| 根级 shim | 目标实现与剩余调用方 | 删除前置条件 |
|---|---|---|
| `calculations.py` | `domain/analysis/calculations.py`；生产内部已迁移，旧测试/脚本仍可导入根路径 | 完成公共导入弃用窗口并迁移仓库外消费者 |
| `limit_facts.py` | `domain/policies/limit_facts.py`；生产内部已迁移，limits fixture/兼容测试仍使用旧路径 | 迁移兼容测试与外部事实处理脚本，并保留 checksum 契约证明 |
| `schemas.py` | `interfaces/http/schemas/models.py`；API 兼容测试及 4 个已登记 infrastructure seam 仍使用 | 先移除 infrastructure 对 HTTP DTO 的校验耦合，再完成公共响应模型导入迁移 |
| `collection.py` | `infrastructure/collection/coordinator.py`；生产装配已迁移，HTTP manual-refresh seam、旧测试/脚本仍使用 | 将开关注入 HTTP 边界并完成旧 coordinator 导入迁移 |
| `refresh.py` | `infrastructure/collection/refresh.py`；HTTP effective-date seam、旧测试/脚本仍使用 | 将市场日期策略提取到 domain/application port，并迁移旧导入 |
| `fuyao.py` | `infrastructure/providers/fuyao/limits_client.py`；生产内部已迁移，provider 兼容测试仍使用 | 完成 provider 客户端根路径弃用窗口 |
| `fuyao_market.py` | `infrastructure/providers/fuyao/market.py`；生产内部已迁移，provider/fixture 测试仍使用 | 迁移仓库内兼容测试并确认无外部脚本使用 |
| `fuyao_config.py` | `infrastructure/providers/fuyao/config.py`；生产内部已迁移，配置测试仍使用 | 迁移配置消费者并保留 fail-closed 开关测试 |
| `fuyao_request_gate.py` | `infrastructure/providers/fuyao/request_gate.py`；生产内部已迁移，请求门测试仍使用 | 迁移测试/脚本且证明两个客户端仍共享同一 gate |
| `tdx_config.py` | `infrastructure/providers/tdx/config.py`；生产内部已迁移，配置测试仍使用 | 迁移配置消费者并保留默认关闭证明 |
| `tdx_daily.py` | `infrastructure/providers/tdx/daily_package.py`；生产内部已迁移，解析/兼容测试仍使用 | 迁移测试/脚本并保留日期、包校验和下载边界契约 |
| `provider_capability.py` | `infrastructure/providers/capability.py`；生产内部已迁移，兼容测试仍使用 | 迁移报告消费者并保留 eligible/unverified 语义测试 |
| `provider_shadow.py` | `infrastructure/providers/shadow.py`；生产内部已迁移，shadow 兼容测试仍使用 | 迁移测试/脚本并保留非破坏性 evidence 契约 |
| `sector_enrichment.py` | `infrastructure/providers/sector_enrichment.py`；生产内部已迁移，兼容测试仍使用 | 迁移调用方并保留保守匹配测试 |
| `industry_mapping.py` | `infrastructure/providers/industry_mapping.py`；生产内部已迁移，TDX 兼容测试仍使用 | 迁移调用方并保留版本化 identity 契约 |
| `postgres_compat.py` | `infrastructure/persistence/postgres/compat.py`；生产内部已迁移，数据库兼容测试仍使用 | 迁移测试/脚本并保留 qmark、row 与事务行为测试 |
| `postgres_migration.py` | `infrastructure/persistence/sqlite_import/migration.py`；CLI 已迁移，迁移测试仍使用 | 迁移维护脚本且证明普通 runtime 不选择 SQLite |
| `date_relabel.py` / `snapshot_migration.py` | `infrastructure/persistence/sqlite_import/date_relabel.py`；CLI 已迁移，历史维护脚本/测试仍使用两个旧名 | 合并历史命令调用方并保留 dry-run、审计与回滚证明 |
| `providers.py` | `infrastructure/legacy/providers.py`；collector runtime 仍通过 `CollectorProviderRuntime` 间接使用 transport | 先提取 transport/normalizer 到正式 provider 包，再迁移 runtime 与外部脚本 |
| `service.py` | `infrastructure/legacy/service.py`；正常 HTTP 不构造，旧测试、脚本和交易系统适配可能使用 | 完成所有 facade 消费者迁移并评审破坏性删除 |
| `snapshot_store.py` | `infrastructure/legacy/snapshot_store.py`；`PostgresRuntimeStore` 仍间接复用 facade/backend | 先完成 PostgreSQL-native facade 替换和 SQLite fixture adapter 拆分 |

本次没有删除上述 shim：每个条目仍有稳定兼容调用或未完成的 runtime seam。任务完成的判据是“实现已归类、内部新依赖被门禁、保留原因可审计”，不是为了减少文件数而制造未经评审的 import break。

## `infrastructure/legacy` 三个大文件应如何理解

这是最容易误判的区域：

- `legacy/service.py`：旧的聚合 service facade。正常 HTTP query/materialization runtime 不再构造它；它主要服务兼容测试、历史脚本和旧导入面。
- `legacy/providers.py`：旧 provider transport 和部分共享 normalizer。五个新 collector 已在 `infrastructure/providers/`，但 `CollectorProviderRuntime` 仍以这里的 `MarketDataProvider` 作为 vendor transport 基类，因此它目前仍有运行时传递依赖。
- `legacy/snapshot_store.py`：旧的 snapshot store 实现和 record 类型。`PostgresRuntimeStore` 继承兼容 `SnapshotStore`，因此 PostgreSQL runtime 仍会经过这里的 facade/backend 逻辑；同时它也承载显式 SQLite fixture/migration 兼容。

所以，“legacy”在这里表示“迁移隔离和兼容边界”，不等于“没有调用者”。删除这些文件前必须：

1. 用 `rg` 检查 `src/`、`tests/`、`scripts/` 和 CLI 的直接/间接导入。
2. 先把需要保留的 transport、record、异常和 migration contract 迁到新位置。
3. 更新 `docs/architecture.md`、`docs/runbooks.md` 和 active plan。
4. 运行架构 AST 门禁、兼容矩阵和全量离线测试。

## 修改规则

- 新 HTTP 路由放 `interfaces/http/routers/`；响应投影放 `interfaces/http/schemas/mappers.py`。
- 新读路径放 `application/queries/`，必须 provider-free；不要在 query 中导入 `infrastructure`、`providers` 或 `collection`。
- 新写路径放 `application/commands/`，通过 `application/ports/` 访问存储、采集和 executor。
- 新纯计算放 `domain/analysis/` 或 `domain/policies/`；禁止在纯领域层读取数据库、环境 provider 或 FastAPI。
- 新 provider/fallback 放 `infrastructure/providers/`，并保留 exact-date、source、quality、warning、failure-retention 和 fail-closed 语义。
- 新 PostgreSQL 持久化放 `infrastructure/persistence/postgres/`；不要在 application 或 router 中写 SQL。
- 根级 shim 只允许转发、兼容别名或极薄的稳定入口；不要把新业务逻辑继续塞进 `service.py`、`providers.py`、`snapshot_store.py`。
- 不要把真实 provider smoke、生产数据库写入、CronJob 激活或 Kubernetes/Helm 写操作混入普通测试。
- 不要提交 `__pycache__/`、真实快照、凭据、私有环境文件或运行时产物。

## 变更后的最小验证

按改动范围选择验证；以下命令均应在仓库根目录执行：

```bash
python scripts/check_market_environment_architecture.py
python -m pytest tests/test_market_environment_architecture.py tests/test_market_environment_bootstrap.py tests/test_market_environment_queries.py -q
python -m pytest tests -q
python scripts/check-docs-contract.py --mode=full
```

涉及 API/采集/存储时，还要运行对应的 `tests/test_market_environment_*.py` focused 集合，并在交付说明中记录跳过的真实 PostgreSQL、provider 或部署验证。任何层边界、数据源、存储或 API 契约变化都必须同步 `docs/architecture.md`、`docs/repository-guide.md`、`docs/runbooks.md` 和相应 active plan。
