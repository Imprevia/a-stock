## Why

`src/market_environment` 已完成主要分层，但根目录仍保留 30 个 Python 文件和约 12,000 行代码，混合了稳定入口、兼容 shim、领域计算、provider 适配、迁移工具和应用编排。若后续继续把新功能直接放入根目录，目录检索、职责判断和调用方迁移都会越来越困难；现在需要建立可执行的根目录收敛规则，并把仍可安全归类的实现迁入既有子包。

## What Changes

- 建立 `src/market_environment` 根目录 Python 文件白名单，根目录原则上只保留稳定入口、公共兼容 shim 和包入口。
- 为现有根目录模块建立逐文件状态清单：运行时主路径、运行时支撑/过渡、纯领域/共享算法、显式维护/迁移、兼容 shim。
- 将仍处于根目录且职责明确的实现按现有分层迁入 `domain`、`application`、`interfaces` 或 `infrastructure` 的合适子包；迁移顺序以低风险、可回滚和不改变行为为前提。
- 对必须保留的旧导入路径提供薄兼容 shim，禁止在 shim 中继续增加业务逻辑，并为每个 shim 记录删除前置条件。
- 为新模块规定放置路径和命名边界：查询、命令、领域计算、provider、持久化、API DTO 和迁移工具不得继续新增为根目录“大杂烩”文件。
- 增强架构/布局门禁，使未经登记的新根目录模块被检测出来，同时保留既有依赖方向、provider-free 查询和 PostgreSQL 运行时约束。
- 同步 `src/market_environment/AGENTS.md`、`docs/architecture.md`、`docs/repository-guide.md`、`docs/runbooks.md` 和 active plan 中的目录事实与迁移状态。
- 不改变 API 路径、响应字段、指标公式、provider 优先级、数据质量语义、数据库表结构、CLI 稳定入口或生产部署边界。

## Capabilities

### New Capabilities

无。本变更是目录治理、兼容迁移和架构门禁调整，不引入新的产品行为。

### Modified Capabilities

无。本变更不改变现有 OpenSpec capability 的需求语义；`skip_specs: true` 表示本次只记录实现结构和治理约束。

## Impact

- 主要影响 `src/market_environment/` 的文件位置、稳定导入 shim、内部 import 路径、架构检查脚本和对应测试。
- 需要更新目录导航、架构映射、运行手册和执行计划；需要保留并验证旧 API/CLI/测试导入合同。
- 需要运行架构门禁、受影响的 market-environment focused tests、全量离线 pytest 和 docs-contract gate；不访问真实 provider、生产数据库或 Kubernetes/Helm 写入口。
- 迁移期间允许根目录继续存在少量兼容文件；只有调用方迁移、验证证据和文档状态齐备后，才可删除或合并旧模块。
