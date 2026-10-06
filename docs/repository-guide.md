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
| `scripts/` | 本地门禁与工具脚本；`deploy-truenas-k3s.sh` 是 TrueNAS k3s 的 all/database/service/schedule 入口，调度 CronJob 与 Helm release 统一 ownership | 改动须同步 `docs/runbooks.md` 与 `docs/architecture.md` |
| `.githooks/` | git hook 薄入口 | 只做转发，规则不写在这里 |
| `.codegraph/` | 代码索引缓存（已 gitignore） | 不手工编辑 |
| `搭建交易系统/` | 交易系统知识库；按 `01`—`11` 章节目录归档，章节总览使用 `0-主题.md`，正文直接位于对应目录 | 维护章节目录内的 Markdown；新增章节时同步更新本表 |
| `搭建交易系统-量化版/` | 原交易系统知识库的一对一量化重写；统一规则 ID、数据口径、公式、阈值状态、评分和否决条件 | 与原目录保持相对路径一致；规则变化同步量化版索引和状态文档 |
| `trading-rules/` | YAML 机器规则事实源、schema 和 327 条规则覆盖清单 | 规则变化必须同步量化文档、测试和证据引用 |
| `src/trading_system/` | 规则加载、标准快照、确定性执行、证据、回测和 CLI | 修改契约时同步产品规格、架构和 runbook |
| `src/trading_knowledge/` | 本地交易知识源解析、SQLite FTS5 索引、只读查询和 MCP stdio 服务 | 修改知识源边界、引用契约或工具 schema 时同步产品规格、架构和 runbook |
| `evidence/` | 可入库的验证清单和月度 SHA-256 摘要 | 不提交大体积输入快照和 trace |
| `.github/workflows/` | 离线 PR 门禁和盘后证据运行 | PR workflow 禁止依赖外部行情网络 |
| `src/market_environment/` | 分层模块化市场环境后端：composition、HTTP/CLI、use case、领域计算、PostgreSQL 与 provider collector | 修改分层、数据源、计算公式或 API 契约时同步 `docs/architecture.md` 与 `docs/runbooks.md` |
| `apps/market-environment-dashboard/` | Vue 3 + Vite + ECharts 第 01 章市场环境分析看板 | 修改页面结构、接口字段或运行命令时同步产品规格、`docs/architecture.md` 与 `docs/runbooks.md`；构建验证必需 |
| `deploy/k3s/`、`deploy/k3s-native-scheduled/` | 市场环境看板的 Dashboard-only k3s Kustomize base，以及受 Kubernetes 1.27+ 检查的 native scheduled overlay | 修改镜像、端口、探针、存储、资源、调度或入口时同步 `docs/architecture.md` 与 `docs/runbooks.md` |
| `deploy/helm/a-stock/` | k3s 部署的可参数化 Helm Chart；`component` 控制 database/service/schedule/all 资源集合 | 修改 values、模板、探针、存储或入口时同步 `README.md`、`docs/architecture.md` 与 `docs/runbooks.md` |
| `deploy/truenas/` | TrueNAS 1.20 与 VM 1.21 的发布参数、PostgreSQL Secret/Service 合同、旧 SQLite 迁移输入边界及 Helm 调度 overlay；通用 Helm 入口位于 `scripts/deploy-truenas-k3s.sh` | 不提交真实 SSH、存储路径或证书信息；参数变更同步 `docs/runbooks.md` 与 `docs/architecture.md` |
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
| `src/market_environment/bootstrap/` | 配置、composition container、FastAPI app factory、lifespan 和 CLI composition | 可引用 interfaces/application/infrastructure；是唯一具体装配位置 |
| `src/market_environment/interfaces/http/` | router、依赖获取、身份/时区上下文、DTO mapper 和 HTTP 错误映射 | application/domain；不得直接构造 provider、repository、executor |
| `src/market_environment/interfaces/cli/` | CLI 参数到 application command/query 的适配 | application/domain；具体实现由 bootstrap 注入 |
| `src/market_environment/application/ports/` | repository、unit-of-work、collector、executor 协议 | domain 与标准库，不依赖具体基础设施 |
| `src/market_environment/application/queries/` | provider-free 精确日期读取、状态和 next-session | 只读 ports、domain；不得导入 collector/provider |
| `src/market_environment/application/commands/` | collection run、刷新和 materialization command | 写 ports、collector registry、executor、domain |
| `src/market_environment/domain/` | 领域值、日期/质量/留存策略与纯分析 | 标准库/Pydantic 边界外的纯模块；不依赖 FastAPI、SQLAlchemy、requests |
| `src/market_environment/infrastructure/persistence/postgres/` | PostgreSQL repository、unit of work、lease/fencing 和 aggregate CAS | application ports/domain/SQLAlchemy |
| `src/market_environment/infrastructure/persistence/sqlite_import/` | 测试或停写迁移 SQLite 适配器 | application ports/domain；不得成为生产静默回退 |
| `src/market_environment/infrastructure/providers/` | vendor client 复用、五类 dataset collector 与降级链 | application collector port、domain、共享 transport |
| `src/market_environment/infrastructure/execution/` | 有界进程内 task executor | application executor port |

稳定兼容入口保留 `src/market_environment/api.py` 与 `src/market_environment/cli.py`；它们只转发到 bootstrap/interfaces。迁移期 facade 只能委托，完成前应删除，不作为新增业务逻辑位置。

## 安全修改区

- `docs/**`：自由修改，保持链接有效。
- `scripts/**`、`.githooks/**`：改动后必须跑 `python scripts/check-docs-contract.py --mode=full` 验证。

## 不安全修改区（改前必须有 active plan）

- `AGENTS.md` 的硬规则块
- `scripts/check-docs-contract.py` 的 gate 逻辑
- `.githooks/*` 的转发目标

## 代码-文档映射

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
| `requirements.txt` / `pyproject.toml` | `docs/runbooks.md`, `README.md` | fail |

## 文档映射规则

- 新增顶层目录 → 更新本文件目录地图
- 交易系统原版或量化版增删、重命名 → 同步两个目录索引并检查一对一映射
- 新增 gate / 检查 → 更新 `AGENTS.md` 硬规则 + `docs/runbooks.md`
- 教训类内容 → `docs/lessons-learned.md`（发生 → 为何重要 → 仓库改了什么）
