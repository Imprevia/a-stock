# 市场环境根目录模块收敛与归类

## Stage

Stage 6/6 — 完成

## Status

completed（OpenSpec `consolidate-market-environment-module-layout`；未改变 API、数据源、数据库或部署契约）

## Acceptance

- 根目录 Python 文件逐一登记状态、目标归属、调用方和删除前置条件。
- 根目录白名单和新模块落位规则可由本地架构门禁检查。
- 必要兼容 shim 保持薄转发，不新增业务逻辑；稳定 API/CLI/测试导入继续可用。
- 纯领域、DTO、迁移辅助和可安全迁移的 provider/application 实现按批次收敛到既有子包。
- 普通 GET、状态查询和 next-session 仍 provider-free；PostgreSQL、精确日期、质量、失败留存、checksum、lease/fencing 和事务边界不变。
- focused/full pytest、架构门禁、docs-contract full 和 `git diff --check` 通过；不执行真实 provider、生产数据库或 Kubernetes/Helm 写操作。

## Completion Evidence

- 2026-10-07：OpenSpec proposal/design/tasks 已生成并通过 strict validation；specs 按纯重构/治理范围显式跳过。
- 2026-10-07：已确认当前根目录 30 个命名实现模块（另有包入口 `__init__.py`）、约 12,000 行，以及 `src/market_environment/AGENTS.md` 中的逐文件运行时状态和兼容边界。
- 2026-10-07：架构门禁已增加根目录白名单、shim 纯转发、未登记模块和 production 子包重新依赖已迁移根实现的检查；架构测试 `6 passed`。
- 2026-10-07：计算/limits/日期/next-session、API DTO、迁移与 CLI 维护验证 `163 passed, 3 skipped`；跳过项均为未配置的显式 PostgreSQL 集成环境。
- 2026-10-07：Fuyao/TDX 实现已迁入 `infrastructure/providers/fuyao|tdx`，collection/refresh 已迁入 `infrastructure/collection`；provider/collection focused 验证 `148 passed`，command/bootstrap/provider-free query 验证 `40 passed`。
- 2026-10-07：根级 shim 退役矩阵已记录目标路径、剩余调用方和删除前置条件；本次没有在仍有兼容调用或 runtime seam 时强制删除 shim。
- 2026-10-07：市场环境完整兼容矩阵 `515 passed, 6 skipped`；最终 focused 架构/bootstrap/query/collection/provider 验证 `79 passed`。
- 2026-10-07：全量离线测试 `768 passed, 106 skipped`；跳过项为未配置的外部/集成环境。Windows 首轮有 3 个 TrueNAS 守卫因系统 `python3.exe` 为 Microsoft Store 占位程序失败，使用临时 `BASH_ENV` 将 `python3` 映射到已有 Python 后重跑通过，临时文件已删除，未修改部署代码。
- 2026-10-07：`scripts/check-docs-contract.py --mode=full` 通过（代码 69 / 文档 5 / plan 1），OpenSpec strict validation 通过，`git diff --check` 通过。
- 2026-10-07：验证期间未执行真实 provider、生产 PostgreSQL、Kubernetes、Helm、CronJob 或调度写操作。

## Remaining Gaps

- 本变更范围内无剩余实现缺口。
- 生产 provider、真实 PostgreSQL、Kubernetes/Helm 和调度验证按安全边界未执行，且不属于本次目录重构的验收要求。

## Next Step

归档 OpenSpec change；后续若要删除根级 shim，按 `src/market_environment/AGENTS.md` 的退役矩阵另建变更，不在本次完成项中追加破坏性清理。
