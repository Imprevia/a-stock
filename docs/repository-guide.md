# 仓库指南（repository guide）

## 仓库目的

a-stock：面向盘后研究的 A 股分析与交易规则工程工作区。产品范围见 `docs/product-specs/market-environment-dashboard.md`、`docs/product-specs/trading-rule-engineering.md` 与 `docs/product-specs/trading-knowledge-mcp.md`；市场环境看板设计规范见 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。

## 顶层目录地图

| 路径 | 用途 | 修改策略 |
|------|------|----------|
| `AGENTS.md` | agent 顶层路由与硬规则 | 改规则须同步 `scripts/check-docs-contract.py` 错误消息 |
| `README.md` | 产品面一页概述 | 低频更新 |
| `docs/` | 事实源（规格 / 架构 / runbook / plan / status） | 高频更新，见下方映射表 |
| `docs/exec-plans/active/` | 活动执行计划（多步工作入口） | 每次多步任务先改这里 |
| `docs/exec-plans/completed/` | 已归档计划 | 只读，完成时移入 |
| `scripts/` | 本地门禁与工具脚本；`deploy-truenas-k3s.sh` 是 TrueNAS k3s 的 all/database/service 入口，对两个历史 CronJob identity 与 namespace Job 做只读 fail-closed 检测，database 只运行一次 schema hook、最终 all 以 `--no-hooks` 收敛；Hermes caller/prompt 是版本化外部调度集成资产 | 改动须同步 `docs/runbooks.md` 与 `docs/architecture.md` |
| `.githooks/` | git hook 薄入口 | 只做转发，规则不写在这里 |
| `.codegraph/` | 代码索引缓存（已 gitignore） | 不手工编辑 |
| `搭建交易系统/` | 交易系统知识库；按 `01`—`11` 章节目录归档，章节总览使用 `0-主题.md`，正文直接位于对应目录 | 维护章节目录内的 Markdown；新增章节时同步更新本表 |
| `搭建交易系统-量化版/` | 原交易系统知识库的一对一量化重写；统一规则 ID、数据口径、公式、阈值状态、评分和否决条件 | 与原目录保持相对路径一致；规则变化同步量化版索引和状态文档 |
| `trading-rules/` | YAML 机器规则事实源、schema 和 327 条规则覆盖清单 | 规则变化必须同步量化文档、测试和证据引用 |
| `src/trading_system/` | 规则加载、标准快照、确定性执行、证据、回测和 CLI | 修改契约时同步产品规格、架构和 runbook |
| `src/trading_knowledge/` | 本地交易知识源解析、SQLite FTS5 索引、只读查询和 MCP stdio 服务 | 修改知识源边界、引用契约或工具 schema 时同步产品规格、架构和 runbook |
| `evidence/` | 可入库的验证清单和月度 SHA-256 摘要 | 不提交大体积输入快照和 trace |
| `.github/workflows/` | 离线 PR 门禁和盘后证据运行 | PR workflow 禁止依赖外部行情网络 |
| `src/market_environment/` | 分层模块化市场环境后端：composition、HTTP/CLI、use case、typed acquisition、PostgreSQL、source adapter 与 collector；目录级文件状态见 `src/market_environment/AGENTS.md` | 修改分层、数据源、计算公式或 API 契约时同步 `docs/architecture.md`、产品规格与 `docs/runbooks.md` |
| `apps/market-environment-dashboard/` | Vue 3 + Vite + ECharts 第 01 章市场环境分析看板 | 修改页面结构、接口字段或运行命令时同步产品规格、`docs/architecture.md` 与 `docs/runbooks.md`；构建验证必需 |
| `deploy/k3s/` | 市场环境看板的 Dashboard-only k3s Kustomize base；不得包含 application-owned market-data CronJob | 修改镜像、端口、探针、存储、资源或入口时同步 `docs/architecture.md` 与 `docs/runbooks.md` |
| `deploy/helm/a-stock/` | k3s 部署的可参数化 Helm Chart；`component` 只控制 database/service/all 资源集合，不提供 schedule values 或 CronJob template | 修改 values、模板、探针、存储或入口时同步 `README.md`、`docs/architecture.md` 与 `docs/runbooks.md` |
| `deploy/truenas/` | TrueNAS 1.20 与 VM 1.21 的发布参数、PostgreSQL Secret/Service 合同及旧 SQLite 迁移输入边界；不再包含 Helm scheduling overlay | 不提交真实 SSH、存储路径或证书信息；参数变更同步 `docs/runbooks.md` 与 `docs/architecture.md` |
| `openspec/` | OpenSpec 规格目录（并发产生，归属待确认） | 勿移动/覆盖；与 docs/exec-plans 的关系待定 |
| `.codex/`、`.opencode/` | agent 工具会话目录 | 是否入库待确认 |

## 主要行为在哪

- 文档契约检查：`scripts/check-docs-contract.py`
- hook 安装：`scripts/install-hooks.py`
- 业务代码：`src/market_environment/` 与 `apps/market-environment-dashboard/`；边界、数据流和降级策略见 `docs/architecture.md`，页面设计与验收基线见 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。
- 交易系统原始知识库：`搭建交易系统/01-如何判断市场环境/` 至 `搭建交易系统/11-量化交易环境下的应对/`；每章目录包含 `0-主题.md` 总览和按 `01.`、`02.` 编号的正文。
- 交易系统量化说明层：`搭建交易系统-量化版/`；与原版保持一对一路径，解释规则口径并引用稳定规则 ID。
- 交易系统机器规则库：`trading-rules/`；YAML 是执行事实源，`coverage.yaml` 覆盖全部文档规则 ID。
- 交易知识 MCP：`src/trading_knowledge/`；消费上述 Git 事实源，索引放在被忽略的 `.artifacts/knowledge-base/`，不进入市场环境 API 或生产数据库。
- 交易系统目录索引：`docs/trading-system-directory.md` 与 `docs/trading-system-quantified-directory.md`；目录结构变化时与 `AGENTS.md` 一并更新。

### 市场环境后端内部地图

| 路径 | 事实职责 | 允许依赖 |
|------|----------|----------|
| `src/market_environment/bootstrap/` | 配置、composition container、FastAPI app factory、lifespan、CLI composition、完整 registry 与进程内唯一 transport gateway | 可引用 interfaces/application/infrastructure；是唯一具体装配位置，任何外部 I/O 前 fail-closed 校验注册完整性 |
| `src/market_environment/interfaces/http/` | router、依赖获取、身份/时区上下文、DTO mapper 和 HTTP 错误映射 | application/domain；不得直接构造 provider、repository、executor |
| `src/market_environment/interfaces/cli/` | CLI 参数到 application command/query 的适配 | application/domain；具体实现由 bootstrap 注入 |
| `src/market_environment/application/ports/` | repository、unit-of-work、collector、committer、local projector、executor、持久 idempotency claim/replay/submission 等 typed 协议 | domain 与标准库，不依赖具体基础设施、vendor 或 native transport 类型 |
| `src/market_environment/application/queries/` | provider-free 精确日期读取、状态和 next-session | 只读 ports、domain；不得导入 collector/provider |
| `src/market_environment/application/commands/` | collection run、刷新、sync-first full automation、materialization command，以及默认 dry-run/显式授权的有界 breadth 历史维护；服务端决定日期与固定七数据集 | 写 ports、collector registry、executor、domain；维护命令不得被 GET、启动或默认部署调用 |
| `src/market_environment/application/collection/` | 七个 stable dataset identifier 的 collector/committer/local-projector registry、确定性注册与查找 | application ports、domain；不依赖具体 provider、persistence 或 native response |
| `src/market_environment/domain/` | 领域值、日期/质量/留存策略、normalized candidate/outcome/failure/evidence 与纯分析 | 标准库/Pydantic 边界外的纯模块；不依赖 FastAPI、SQLAlchemy、requests、Scrapling |
| `src/market_environment/infrastructure/persistence/postgres/` | PostgreSQL repository、unit of work、lease/fencing、持久 idempotency/submission、structured failure、aggregate CAS，以及 breadth/limits V2 历史的条件式 typed date predicate 与 `limit + 1` keyset 查询 | application ports/domain/SQLAlchemy；禁止 nullable untyped optional bind |
| `src/market_environment/infrastructure/persistence/sqlite_import/` | 测试或停写迁移 SQLite 适配器 | application ports/domain；不得成为生产静默回退 |
| `src/market_environment/infrastructure/providers/` | source adapter、dataset acquisition plan、七类 collector、`CollectorProviderRuntime` 与共享 core identity contract；Fuyao 实现归入 `fuyao/`，TDX 实现归入 `tdx/` | application ports、domain、共享 policy gateway；不得自行提交快照或管理 task/lease |
| `src/market_environment/infrastructure/collection/` | coordinator、typed committer、local projector 与采集维护命令适配 | application ports/domain/PostgreSQL UoW；不得解释 vendor payload 或反射发现 collector 方法 |
| `src/trading_system/data/provider_http.py` 及其 transport 子模块 | engine-neutral HTTP contract、默认 requests engine、可选 Scrapling static engine、进程内共享 policy gateway | engine 只执行单次请求；重试/限速/缓存/熔断/脱敏由 gateway 独占，不向上暴露 native response |
| `src/market_environment/infrastructure/execution/` | 有界进程内 task executor；提交状态必须可由同 key replay 恢复而不创建替代 run | application executor port |
| `src/market_environment/infrastructure/legacy/` | 明确隔离的兼容面：provider 文件仅重导出正式 runtime 并提供稳定 alias；service 主要供兼容/测试；snapshot store 仍被当前 PostgreSQL runtime adapter 传递使用 | 不得在 query/router 或 normal bootstrap 中直接构造；删除前必须完成调用方迁移并更新 `src/market_environment/AGENTS.md`、active plan 和验证证据 |

稳定兼容入口保留 `src/market_environment/api.py`、`src/market_environment/cli.py` 以及清单登记的根级导入 shim；
计算、DTO、迁移、Fuyao/TDX 与 provider 支撑 shim 分别转发到 `domain`、`interfaces` 或 `infrastructure` 的目标实现，
`service.py`、`providers.py`、`snapshot_store.py` 继续转发到登记的 compatibility target；其中 provider 的真实实现由
`infrastructure/providers/runtime.py` 持有，legacy 文件只保留重导出/alias。普通 query/materialization runtime 使用
application query/command、`MaterializationSupport` 和明确命名的 runtime adapters，不再构造旧 provider/service 或
coordinator `Legacy*` facade。新增业务模块不得进入根目录；布局门禁会拒绝未登记文件、含业务逻辑的 shim、normal runtime
重新导入 legacy provider、compatibility shim 嵌套 coordinator，以及 production
子包重新依赖已迁移根实现。
根目录与 legacy 文件的逐文件状态、哪些仍被 runtime 间接使用以及迁移/删除前的检查清单，维护在
`src/market_environment/AGENTS.md`；该文件是目录导航，不替代本仓库的架构、runbook 和 active plan 事实源。

## 安全修改区

### AI 市场数据 v2 的代码—文档映射

| 代码区 | 预期职责 | 必须同步的事实文档 |
|---|---|---|
| `src/market_environment/interfaces/http/routers/`、`interfaces/http/schemas/`、`interfaces/http/errors.py` | additive v2/discovery routes、专用 envelope/resource DTO、ETag/304/404/409/422 与 `snapshot_integrity_error` 503 stable mapping；不得复用完整 Chapter 01 DTO | `docs/architecture.md`、`docs/product-specs/market-environment-dashboard.md`、`docs/runbooks.md`、active plan |
| `src/market_environment/application/queries/`、`application/ports/` | provider-free resource facade、exact-date typed read ports、opaque revision/cursor validation；不得导入 provider、HTTP 或 infrastructure implementation | `docs/architecture.md`、产品规格、active plan |
| `src/market_environment/infrastructure/persistence/postgres/v2_market_data.py`、`application/queries/` 与 V2 history routers | breadth/limits history 只追加实际存在的 typed date/cursor predicate，保持升序、`limit + 1`、revision/cursor 校验、provider-free/write-free 和 integrity fail-closed | `docs/architecture.md`、产品规格、`docs/runbooks.md`、OpenSpec `fix-breadth-page-data-availability`、active plan |
| `src/market_environment/infrastructure/providers/core_acquisition.py`、`infrastructure/collection/core_*`、`infrastructure/legacy/snapshot_store.py` 与其余 `infrastructure/persistence/postgres/` | core 单指数精确日期证明、同日留存、compatibility/typed snapshot 严格写入、materialized aggregate CAS 与 component revision；跨日期候选不得进入新写，普通读取 fail closed | `docs/architecture.md`、产品规格、`docs/runbooks.md`、active plan |
| `src/market_environment/infrastructure/providers/fuyao/config.py`、`domain/policies/capability.py`、`src/market_environment/cli.py` | Fuyao core v2 正式门禁、自包含 capability evidence/promotion 与脱敏 probe；core 正式启用必须关闭 shadow，禁止跨 provider comparison 字段 | `docs/architecture.md`、产品规格、`docs/runbooks.md`、active plan |
| `deploy/truenas/values-fuyao-core-*.yaml`、`scripts/validate-scheduling-packet.py`、`scripts/deploy-truenas-k3s.sh` | complete core-off/enabled packet、仅 core enabled flag 的语义 diff、冻结镜像、exact disabled Pod promotion 与 hook-free enable/rollback | `docs/architecture.md`、`docs/runbooks.md`、active plan |
| `src/market_environment/bootstrap/`、`src/market_environment/api.py` | composition root additive 注册 v2 与 discovery，无 mutable module singleton，legacy routes 始终保留 | `docs/architecture.md`、`docs/runbooks.md`、active plan |
| `apps/market-environment-dashboard/src/stores/market.ts`、`types.ts`、第 02 页组件与对应 tests | v2 envelope/revision/cursor/error client、breadth summary/history 独立提交与重试、409 整组重启、60/250 coverage、最近 5 日展示；integrity error 不 fallback | 产品规格、设计规范、`docs/runbooks.md`、OpenSpec `fix-breadth-page-data-availability`、active plan |
| `src/market_environment/application/commands/`、`interfaces/cli/`、`src/market_environment/cli.py` 与 breadth acquisition/collection/materialization 测试 | 默认 dry-run、有限预算、显式授权、逐日独立的 breadth 历史维护；复用 exact-date TDX、coordinator、lease/fencing、typed committer、audit 与依赖 aggregate rebuild，禁止直接 snapshot SQL | `docs/architecture.md`、产品规格、`docs/runbooks.md`、OpenSpec `fix-breadth-page-data-availability`、active plan |
| `tests/test_market_environment_*` 与前端 `*.test.ts` | legacy characterization、真实 PostgreSQL breadth/limits history、HTTP provider/write-free、integrity、summary/history 隔离、60/250 与渐进迁移回归 | OpenSpec `add-ai-market-data-api` 与 `fix-breadth-page-data-availability` specs/tasks、active plan |

上述映射不授权 provider、生产数据库、部署或调度写操作。`src/trading_knowledge/` 不在本 change 范围；发现文档只描述受支持的 read surface，不把 MCP 扩展为行情服务。若实现证明需要 migration、新 provider 或新写路径，必须先回到 OpenSpec 和本映射修订范围，不能静默吸收。

### Hermes 全量采集与 Kubernetes 调度退役的代码—文档映射

| 代码区 | 事实职责 | 必须同步的事实文档 |
|---|---|---|
| `src/market_environment/domain/`、`application/ports/` | semantic fingerprint、idempotency claim/replay/conflict、submission state、redaction-safe structured failure | `docs/architecture.md`、产品规格、active plan |
| `src/market_environment/application/commands/`、`interfaces/http/` | 服务端上海日期、固定七数据集、settlement/weekend、sync-first 200/202 full endpoint、status response | `docs/architecture.md`、产品规格、`docs/runbooks.md` |
| `src/market_environment/infrastructure/persistence/postgres/`、`postgres_schema.py`、`alembic/versions/` | 原子 key→run/tasks binding、submission recovery、failure round-trip、schema migration | `docs/architecture.md`、`docs/runbooks.md`、active plan |
| `scripts/` 中的 Hermes caller/prompt 资产 | 15:30 schedule-slot key、有限重放/轮询、16:00 catch-up 截止、中文摘要；不得获得 provider/DB/deploy 能力 | `docs/runbooks.md`、产品规格、active plan |
| `deploy/helm/a-stock/`、`deploy/k3s/`、`deploy/truenas/` | 不创建 CronJob；只配置 automation gate 并保持 manual 独立；所有 render 无 scheduled workload | `docs/architecture.md`、`docs/runbooks.md`、active plan |
| `scripts/deploy-truenas-k3s.sh` 及部署 validator | 普通部署只读拒绝 stored/live `a-stock-data-collection` 与 `market-data-collection`；起始与成功后 namespace Job absent，只允许 database 阶段执行精确 `a-stock-schema-migration` hook 一次，service/final all 使用 `--no-hooks`；失败停止后续收敛并保留 failed Job 证据；不提供正向 schedule mutation | `docs/architecture.md`、`docs/runbooks.md`、active plan |
| `apps/market-environment-dashboard/` | 兼容 nullable structured failure，优先 safe message 且保留 warning fallback | 产品规格、设计规范、`docs/runbooks.md` |

该 change 不构成其他生产或 Hermes 外部写的 blanket authorization。tasks 7.2–7.5 已分别获得授权：backend/schema
rollout、automation canary/replay、Hermes 资产/job，以及两个自然交易日观察；当前批准的 job 定义为工作日
15:30 和飞书当前会话。主动运行 job/caller、额外 THS provider 重采和 task 7.6 仍未授权。
`Idempotency-Key`、CORS、UI 和 lease 是可靠性机制，不是鉴权；
automation gate 开启后，所有可路由到 `192.168.1.20:32001` 的客户端都能调用 full endpoint。
重新引入 Kubernetes scheduling 必须新建受审 change，不能把历史模板、overlay 或 CLI 恢复为回滚路径。

### 第 05 页持续性分析的代码—文档映射（规划归属）

| 代码区 | 预期职责 | 必须同步的事实文档 |
|---|---|---|
| `src/market_environment/domain/models/` | taxonomy revision、industry identity、membership interval、security/benchmark fact、aggregate、continuity result、backfill 状态等不可变模型 | `docs/architecture.md`、`docs/product-specs/market-environment-dashboard.md` |
| `src/market_environment/domain/analysis/` | 五项规则纯函数、midrank、候选/阶段/抱团否决和唯一验证项渲染 | 第 05 页产品规格、量化版规则说明、active plan |
| `src/market_environment/application/ports/` | repository/UoW、capability、backfill、provider-free query 和 typed lineage 协议 | `docs/architecture.md`、`docs/runbooks.md` |
| `src/market_environment/application/commands/` | 显式、有限、可恢复 backfill 与写入编排 | `docs/runbooks.md`、active plan |
| `src/market_environment/application/queries/` | 精确日期 observation/analysis/readiness/status 只读投影 | `docs/product-specs/market-environment-dashboard.md`、`docs/runbooks.md` |
| `src/market_environment/infrastructure/persistence/postgres/` | additive migration、PostgreSQL repositories、UoW、lease/fencing、snapshot v2 materialization | `docs/architecture.md`、`docs/runbooks.md` |
| `src/market_environment/infrastructure/providers/` | Shenwan taxonomy/membership、adjusted price、TDX original facts、benchmark adapters 与 capability reports | `docs/architecture.md`、`docs/runbooks.md` |
| `src/market_environment/interfaces/http/` | `SectorEvidence.analysis`、readiness/backfill DTO 和 observation/analysis 错误映射 | 产品规格、API 契约、active plan |
| `src/trading_system/data/` | snapshot v2 `metricProvenance`、canonical sector bridge 和 hash 输入 | `docs/architecture.md`、交易规则工程规格、runbook |
| `apps/market-environment-dashboard/` | 第 05 页 observation/analysis 双区与数据管理页 readiness 只读展示 | 产品规格、设计规范、runbook |

上述路径是预计归属，不授权提前实现。backfill 不得塞入根级 shim、普通 query、七数据集 collector 或自动化触发；SQL 只进入 PostgreSQL persistence，provider 只进入 infrastructure adapter，纯计算不得反向依赖 FastAPI、SQLAlchemy、requests 或 vendor 类型。根级兼容文件只能转发到正式目标，不得新增业务逻辑。

### THS 目录与量价历史的代码—文档映射（规划归属）

| 代码区 | 预期职责 | 必须同步的事实文档 |
|---|---|---|
| `src/market_environment/domain/models/`、`src/market_environment/domain/analysis/` | capability/catalog observation revision 分离、完整目录 checksum/ID、共享代码身份、snapshot observation availability、`missingLiveCodes`/`missingRankingCodes`、排名行质量、OHLC/volume/turnover、当日宽度、质量 lineage 和回填 checkpoint 等不可变模型与纯计算 | `docs/architecture.md`、`docs/product-specs/market-environment-dashboard.md` |
| `src/market_environment/application/ports/` | 目录/量价/宽度 repositories、UoW、capability、预算、checkpoint 和 provider-free query 协议 | `docs/architecture.md`、`docs/runbooks.md` |
| `src/market_environment/application/commands/` | 显式目录同步复用 daily collection 的完整目录/revision/partial 原子规则，另含单编号/60 编号分批历史回填、dump 导入、三数据集编排与可恢复写入 | `docs/runbooks.md`、active plan |
| `src/market_environment/application/queries/` | 目录、K 线、宽度、任务状态和回填进度的精确日期只读投影；隐式读取只选一个最新兼容 revision，显式读取不跨 revision 合并 | 产品规格、`docs/runbooks.md` |
| `src/market_environment/infrastructure/providers/fuyao/`、`src/market_environment/infrastructure/providers/tdx/` | Fuyao adapter 只做四类完整响应归一化、身份/日期验证和值可用性分类，TDX 负责精确日期降级；均只输出 typed provider facts 和脱敏证据，不决定目录持久化身份 | `docs/architecture.md`、`docs/runbooks.md` |
| `src/market_environment/infrastructure/persistence/postgres/`、`src/market_environment/postgres_schema.py`、`alembic/versions/` | 不可变 catalog observation、ranking quality/warning round-trip、显式/单一最新 revision 读取、目录/量价/宽度/checkpoint repositories、幂等冲突和 lease/fencing；本修复以 schema v10 / `0007_ths_catalog_identity` 删除不含交易日的冗余唯一约束，保留 revision identity；Alembic revision ID 必须适配默认 32 字符版本列 | `docs/architecture.md`、`docs/runbooks.md`、active plan |
| `src/market_environment/infrastructure/collection/`、`src/market_environment/bootstrap/registries.py` | `industry-ranking -> sector-turnover -> sector-breadth` 的完整 ranking、bar/gap 对账、same-date/same-revision compatible-partial 谓词、失败隔离、请求预算和公共 dataset 注册 | `docs/architecture.md`、`docs/runbooks.md`、active plan |
| `src/market_environment/infrastructure/materialization_support.py`、`src/trading_system/data/` | Chapter 01 的 `industryRanking`/`sectorTurnover`/`sectorBreadth`/`sectorAnalysis` 原子重建和 snapshot bridge | `docs/architecture.md`、产品规格、交易规则工程规格 |
| `src/market_environment/interfaces/http/`、`src/market_environment/interfaces/cli/`、`src/market_environment/cli.py` | provider-free GET、受门禁保护的显式 POST/CLI、opaque `catalogRevisionId`、optional typed/bounded THS diagnostics 与 legacy warning 兼容；稳定根级 CLI 只做转发 | 产品规格、API 契约、`docs/runbooks.md` |
| `apps/market-environment-dashboard/` | 数据管理页三任务 coverage/missing/reason/blockedBy 诊断，以及第 05 页 partial 排名、行级 unavailable、板块宽度、量价 K 线、申万持续性四视图 | 产品规格、设计规范、`docs/runbooks.md` |

上述路径由 `add-fuyao-ths-sector-datasets` 建立，`fix-ths-catalog-revision` 修复目录观察身份、partial
语义和诊断兼容，以 `0007` 删除一个冗余唯一约束，并补强生产停写、不可变镜像与 terminal Job 审计保留门禁。
真实 provider、生产 migration、非测试数据库、生产部署或调度操作仍只能在 active plan 记录的明确授权和
逐步 fail-closed 验收下执行，不能由代码落地或布尔开关自行授权。
THS 目录同步和回填不得进入申万 continuity backfill、普通 GET、根级兼容 shim 或默认调度；THS observation
不得作为申万一级 `QTS-01-05-*` 输入。旧 `sectors` 数据库证据只能由审计查询读取，不得在 migration、repository
或 materialization 中重命名、覆写或伪装成新数据集。

- `docs/**`：自由修改，保持链接有效。
- `scripts/**`、`.githooks/**`：改动后必须跑 `python scripts/check-docs-contract.py --mode=full` 验证。
- `scripts/check_market_environment_architecture.py`：离线 AST/import 门禁；改动分层或入口时同步运行并记录结果。

## 不安全修改区（改前必须有 active plan）

- `AGENTS.md` 的硬规则块
- `scripts/check-docs-contract.py` 的 gate 逻辑
- `.githooks/*` 的转发目标

## 代码-文档映射

### 第 06 页主动进攻方向工作台映射（2026-10-21）

| 代码区 | 事实职责 | 必须同步 |
|---|---|---|
| `src/market_environment/infrastructure/providers/runtime.py` | active-direction primary/delayed/TDX 派生样本校验、Top-30 retention、Top-10 projection | `docs/architecture.md`、`docs/runbooks.md`、active plan |
| `src/market_environment/domain/`、`application/queries/`、`infrastructure/materialization_support.py` | provider-free workbench facts、rule maturity、quality/lineage、missing semantics、failure isolation | `docs/architecture.md`、产品规格 |
| `src/market_environment/application/ports/v2_market_data.py`、`application/queries/v2_market_data.py`、`infrastructure/persistence/postgres/v2_market_data.py` | 精确日期 workbench read port、repository 和 revision precondition | `docs/architecture.md`、`docs/runbooks.md` |
| `src/market_environment/interfaces/http/routers/market_environment_v2.py`、`interfaces/http/schemas/models.py` | `/active-direction/workbench` DTO、links、ETag/revision 错误语义 | 产品规格、`docs/runbooks.md` |
| `apps/market-environment-dashboard/src/pages/dashboard/Document06ActiveDirectionPage.vue`、`stores/market.ts`、`types.ts` | 五视图、Top-30 选择传播、missing/partial 状态和 390px 样式 | 产品规格、`docs/architecture.md` |

工作台不得在前端拼接其他章节 endpoint，不得按名称猜测 identity；旧 `topStocks` 读取路径保持兼容。

业务代码落地后按下表扩展（映射非空时由 gate 强制执行）：

| 代码区 | 必需文档更新 | 门禁级别 |
|--------|-------------|----------|
| `src/**`（未来） | `docs/architecture.md` | fail |
| `src/market_environment/**` | `docs/architecture.md`, `docs/repository-guide.md`, `docs/runbooks.md`, active plan | fail |
| `src/trading_system/**` / `trading-rules/**` | `docs/product-specs/trading-rule-engineering.md`, `docs/architecture.md`, `docs/runbooks.md` | fail |
| `src/trading_knowledge/**` | `docs/product-specs/trading-knowledge-mcp.md`, `docs/architecture.md`, `docs/runbooks.md` | fail |
| `.github/workflows/**` | `docs/runbooks.md`, active plan | fail |
| `apps/**` | `docs/architecture.md`, `docs/runbooks.md` | fail |
| `deploy/truenas/**` | `docs/architecture.md`, `docs/runbooks.md`, active plan | fail |
| `docs/product-specs/**` 引用的代码路径 | 对应 spec | fail |
| `scripts/**` | `docs/runbooks.md`, `docs/architecture.md`（涉及部署边界时） | warn |
| `requirements*.txt` / `pyproject.toml` / `Dockerfile*` / enhanced profile | `docs/runbooks.md`, `README.md`, `docs/architecture.md`；部署 profile 同步离线渲染证据 | fail |

## 文档映射规则

- 新增顶层目录 → 更新本文件目录地图
- 交易系统原版或量化版增删、重命名 → 同步两个目录索引并检查一对一映射
- 新增 gate / 检查 → 更新 `AGENTS.md` 硬规则 + `docs/runbooks.md`
- 教训类内容 → `docs/lessons-learned.md`（发生 → 为何重要 → 仓库改了什么）
