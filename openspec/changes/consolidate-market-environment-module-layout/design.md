## Context

See `proposal.md` for the motivation. 当前 `src/market_environment` 已有 `bootstrap`、`interfaces`、`application`、`domain` 和 `infrastructure` 五层，但根目录仍保留稳定入口、兼容面、共享算法、provider 适配和迁移工具。`src/market_environment/AGENTS.md` 已记录这些文件的运行时状态和删除前置条件；部分旧导入仍被测试、CLI、collector runtime 或 PostgreSQL 兼容适配器间接使用。

本设计必须保持以下边界：API/CLI 入口路径不变；普通 GET、状态查询和 next-session 继续 provider-free；PostgreSQL 仍是正式运行时存储；SQLite 只允许显式迁移/测试；provider 优先级、精确日期、质量状态、失败留存、checksum、lease/fencing 和事务边界不变。

## Goals / Non-Goals

**Goals:**

- 把根目录收敛为稳定入口和明确登记的兼容面，防止新增业务逻辑继续堆积在根目录。
- 为每个根目录模块建立唯一状态、目标归属、直接调用方和可删除条件。
- 优先复用既有五层架构，不引入第二套按 MVC 或 vendor 重新组织的目录体系。
- 通过薄 shim 保留必要的历史导入，并用测试和 AST/布局门禁证明迁移没有改变行为。
- 让后续新增查询、命令、领域计算、provider、持久化、DTO 和迁移工具都有稳定落点。

**Non-Goals:**

- 不重写指标、质量策略、provider fallback、数据库 schema、API 响应或部署拓扑。
- 不在同一变更中删除所有 `legacy` 实现；只有调用方迁移和证据满足时才逐项删除。
- 不引入新的依赖注入框架、微服务、异步队列或新的外部数据源。
- 不把所有文件机械地拆成更深的目录；目录必须对应稳定职责或边界。

## Decisions

### 1. 采用“根目录白名单 + 子包职责”的治理方式

根目录允许保留 `__init__.py`、`api.py`、`cli.py` 以及经清单登记的兼容 shim（当前包括 `service.py`、`providers.py`、`snapshot_store.py`，必要时保留其他稳定公共契约）。任何新增根目录 `.py` 必须在清单中说明其稳定导入、运行时用途和迁移计划；默认新增实现必须进入现有子包。

选择白名单而不是“根目录必须为空”，是因为 `api.py`、CLI 和历史公共导入路径是已发布的兼容接口，直接删除会产生无关的破坏性变化。

### 2. 先建立逐文件清单，再按能力批量迁移

清单以 `src/market_environment/AGENTS.md` 为目录级导航，补充目标路径、迁移阶段、直接/间接调用方、兼容 shim 责任和删除条件。迁移顺序按风险从低到高：纯领域/共享算法、DTO/边界模块、显式迁移工具、provider 支撑，最后才处理仍承载 runtime seam 的 collection/store/transport 实现。

选择逐文件清单而不是一次性目录重排，是因为“文件名带 legacy”不能证明没有调用者；当前 `infrastructure/legacy/providers.py` 和 `snapshot_store.py` 仍可能通过 runtime adapter 被使用。

### 3. 兼容 shim 只做转发和别名

根级 shim 可以重新导出类型、异常、常量或调用新实现，但不得新增 SQL、provider 请求、业务分支或资源装配。每个 shim 必须有对应的调用方迁移测试和删除前置条件；没有证据时保持 shim，不做清理性删除。

选择薄 shim 而不是批量替换所有 import，是为了保留 CLI、测试、交易系统适配和外部脚本的稳定入口，同时让新代码使用目标子包。

### 4. 扩展现有架构门禁，而不是引入新的 lint 依赖

在 `scripts/check_market_environment_architecture.py` 现有 AST/import 检查上增加根目录布局检查：扫描根目录 `.py`、校验白名单、识别 shim 是否包含非转发实现，并对新增模块给出可定位错误。测试覆盖允许文件、未登记文件和含业务逻辑的 shim 三类情况。

选择仓库原生检查而不是第三方 import-linter，是为了保持离线、确定性和当前 CI/本地 docs-contract 工作流的一致性。

### 5. 迁移采用“新路径先行、旧路径后移除”的兼容步骤

每个迁移批次先在目标子包建立实现和显式导出，再切换生产装配和测试导入，运行 focused 回归后把旧根模块缩减为 shim，最后在单独批次删除已无调用者的 shim。任何批次失败只回退该批次的 import/wiring，不改写数据库或生产数据。

## Risks / Trade-offs

- **[兼容导入遗漏]** → 迁移前扫描 `src/`、`tests/`、`scripts/` 和 CLI 的直接/间接导入；保留 shim 并运行 API、CLI、provider、snapshot、collection 兼容矩阵。
- **[误删仍被 runtime 间接使用的 legacy 模块]** → 以运行时调用图和测试证据为准，不以目录名或文件大小判断；删除前要求明确的调用方迁移记录。
- **[目录过度细分导致导航反而困难]** → 只有跨层边界、独立职责或稳定数据集能力才建立子包；小型共享常量继续放在已有相关模块。
- **[布局门禁阻塞合理的稳定入口]** → 白名单显式登记入口和兼容 shim，并在错误消息中给出允许路径、目标归属和登记位置。
- **[迁移改变 import 初始化行为]** → 保持无 I/O 导入测试，禁止在 shim、domain、application 或接口模块中新增数据库连接、schema 创建、provider 请求和线程提交。

## Migration Plan

1. 从当前根目录 30 个文件开始建立逐文件清单，确认 `AGENTS.md`、架构文档和仓库指南中的状态一致。
2. 定义根目录白名单、目标子包映射和 shim 约束，先实现只读布局检查和失败样例测试。
3. 迁移无副作用的领域算法、DTO/响应边界和显式迁移辅助模块；每批次保留旧导入 shim，运行 focused 测试。
4. 迁移 provider 支撑和应用过渡模块，确认 collector runtime、PostgreSQL runtime 和 CLI 维护命令仍沿用原调用链。
5. 对已无调用者的 shim 单独提交删除批次；仍有间接依赖的模块继续保持兼容并记录下一步。
6. 更新架构、仓库指南、runbook、目录级 AGENTS 和 active plan，运行架构检查、market-environment focused tests、全量 pytest 与 docs-contract full。

回滚策略是按批次恢复旧 import/wiring 和 shim；不执行数据库回滚、生产部署、provider smoke、CronJob 激活或 Kubernetes/Helm 写操作。

## Open Questions

无。根目录白名单的具体最终文件集合可在第一阶段清单审计中细化，但不会改变本设计的依赖方向、兼容策略或验证方式。
