# 第 05 页申万一级行业主线持续性指标

## 目标

把第 05 页从“当日行业排名观察”扩展为可追溯、可降级、可离线重放的申万一级行业持续性分析：保留现有 provider observation，同时规划独立的时点行业事实、五项指标、最多三个候选、唯一下一交易日验证项、显式历史回填和交易规则 snapshot v2 桥接。

## 范围

包含：OpenSpec `add-sector-continuity-metrics` 的产品、架构、代码归属、运维与验证事实；后续领域模型、PostgreSQL additive migration、provider/capability gate、纯分析、显式 backfill、API、前端和交易规则桥接。

排除：概念/题材板块、自动下单、按名称猜测 provider 行业与申万行业等价、自动赋予“龙头/中军/补涨”角色，以及未经单独授权的真实 provider probe、生产数据库迁移、非 fixture 回填、部署或调度激活。

## Stage（阶段）

- 当前阶段：**Stage 11.1 — 已授权真实 capability probe，执行前置条件阻塞**
- 阶段序列：事实文档 → 数据源能力与离线证据 → 时点领域模型与持久化 → 精确日期聚合 → 连续性分析 → 显式 backfill → API/前端 → snapshot bridge → 全量离线验证
- 本轮边界：OpenSpec tasks 1.1–10.5 的实现与离线验证完成；用户已授权 task 11.1，但真实 probe 仍受上海盘后时间门禁和 source-specific provider-neutral adapter 前置条件约束。tasks 11.2–11.4 未获授权，不执行数据库回填、部署或调度激活。

## Status（状态）

`in-progress` · task 11.1 已获授权并完成零网络 dry-run 预检；当前时间未到上海 15:30，且仓库未配置真实 probe adapter，因此真实 probe 未运行、11.1 未完成。生产 migration/backfill、部署和调度操作未获授权且未执行。

## 事实源

- `openspec/changes/add-sector-continuity-metrics/`
- `docs/product-specs/market-environment-dashboard.md`
- `docs/architecture.md`
- `docs/repository-guide.md`
- `docs/runbooks.md`
- `docs/status.md`

## 阶段任务

- [x] 创建 active plan，并登记 `_index.md` 与 `docs/status.md`
- [x] 更新产品规格，冻结申万一级范围、五项指标、候选和唯一验证项语义
- [x] 更新架构与仓库指南，冻结时点数据流、repository/UoW、显式 backfill、API 和 snapshot bridge 边界
- [x] 更新 runbook，冻结离线验证、能力报告、迁移、回填、恢复、回滚和授权边界
- [x] 同步第 05 章原版/量化版、YAML、coverage 和证据引用（OpenSpec task 1.5）
- [x] 实现并验证 OpenSpec tasks 2.1–10.4
- [ ] 真实 taxonomy/membership/adjusted-price/benchmark capability probe（OpenSpec task 11.1；已授权，受盘后窗口和缺少真实 adapter 阻塞）
- [ ] 生产 migration/backfill、部署或调度激活（OpenSpec tasks 11.2–11.4，未授权）

## Acceptance（验收）

- 产品规格明确仅覆盖申万一级行业，并区分 provider observation 与 canonical analysis。
- 五项指标、最多三个候选、唯一验证项、无候选语义、阶段与失败/降级状态和 delta specs 一致。
- 架构明确 taxonomy/membership/行情/benchmark/聚合/分析/backfill 的数据流、PostgreSQL repository/UoW、provider-free query 和显式 backfill 边界。
- `SectorEvidence.analysis` 为可选扩展；snapshot v2 新增 closed `metricProvenance`，冻结 v1 仍可 replay。
- runbook 明确 fixture、capability、数据权利、additive migration、显式回填、resume、恢复与回滚；普通 GET、启动、五数据集“全部采集”和默认调度均不会触发 backfill。
- `python scripts/check-docs-contract.py --mode=fast`、`python scripts/check_market_environment_architecture.py`、OpenSpec strict validation 与 `git diff --check` 通过，或将环境阻塞如实记录。

## Completion Evidence（完成证据）

- 2026-10-10：已创建本计划并完成 tasks 1.1–1.4 所需事实文档更新；随后完成第 05 章、规则、架构、runbook 与实现同步。
- `.venv/bin/python -m pytest tests/test_market_environment_industry_capabilities.py tests/test_market_environment_point_in_time_industry.py tests/test_market_environment_postgres_sector_continuity.py tests/test_market_environment_sector_backfill.py tests/test_market_environment_sector_continuity.py tests/test_market_environment_sector_continuity_models.py tests/test_market_environment_sector_materialization.py tests/test_market_environment_alembic.py tests/test_market_environment_postgres_uow.py tests/test_market_environment_limit_contract.py -q`：`105 passed, 1 skipped`。
- 一次性本机 PostgreSQL 16.4 隔离库完成 Alembic `upgrade head → downgrade 0003_provider_capability_reports → upgrade head`；升级后版本为 `0004_sector_continuity`，9 张 sector 表在非破坏性回退后保留，再次升级成功。隔离库 database/UoW/lease 集成为 `22 passed`，完成后容器已停止并自动删除。
- `MARKET_ENVIRONMENT_TEST_DATABASE_URL=<isolated-local-postgres> .venv/bin/python -m pytest tests -q`：`1335 passed`；仅有 Starlette/anyio 的第三方弃用警告。
- `.venv/bin/python -m pytest tests/test_trading_rule_v2_golden_replay.py tests/test_trading_rule_platform.py -q`：`33 passed`；完整 v2、部分 sector metrics、observation-only 三类 fixture 均双次 replay，结果字节、snapshot/result hash、traces 和 evidence bundle 逐文件确定。
- `.venv/bin/python scripts/check_market_environment_architecture.py`：通过（`market-environment architecture: OK`）。
- `.venv/bin/python -m src.trading_system.cli rules validate`：`1` 个规则集、`49` 条规则；`rules coverage` 与 `docs sync-check`：`330` 条文档规则、`49` 条可执行规则，一致通过。
- `openspec validate add-sector-continuity-metrics --type change --strict --no-interactive`：通过。
- `.venv/bin/python scripts/check-docs-contract.py --mode=full`：通过（代码 67 / 文档 9 / plan 3）。
- `.venv/bin/python -m compileall -q src/market_environment src/trading_system` 与 `git diff --check`：通过。
- 2026-10-11：前端 OpenSpec tasks 8.1–8.5 已完成；`apps/market-environment-dashboard/` 执行 `npm run test` 通过（20 files / 134 tests），`npm run build` 成功（Vite 仅提示 chunk >500KB 优化建议）。
- 最终审计确认 `SUPPORTED_COLLECTION_DATASETS` 仍严格为 `core`、`breadth`、`limits`、`sectors`、`activeDirection`，sector backfill 未成为第六数据集；Helm 默认仍为 `scheduledCollection.enabled=false`、`suspend=true`。本变更 fixture 均为小型合成数据，敏感信息扫描无命中，忽略目录中的测试缓存未进入 Git diff。
- 未执行任何真实 provider、生产 PostgreSQL、Kubernetes、Helm、PVC、Secret 或调度写操作；一次性隔离 PostgreSQL 不包含生产数据且已删除。
- 2026-10-12：用户明确授权 task 11.1。上海时间 `10:57` 的执行前检查未通过 `15:30` 盘后门禁；同时 `industry-capability-probe` CLI 未注入 source-specific `probe` adapter，真实模式即使盘后也会以 `no provider-neutral probe adapter is configured` fail closed。已在 `/tmp/a-stock-industry-probes-20261012.KdADDn/` 为 `shenwan-taxonomy`、`shenwan-point-in-time-membership`、`stock-adjusted-price`、`benchmark-history` 生成四份脱敏 dry-run 报告，全部为 `status=dry-run`、`networkCalls=0`、`formalWrites=0`；未生成 checksum/覆盖/数据条款的真实证据，未打开任何 provider 开关。

## Remaining Gaps（剩余缺口）

- OpenSpec task 11.1 已获用户授权，但真实 taxonomy/membership/adjusted-price/benchmark capability probe 尚未运行：当前执行时点早于上海 15:30，且仓库没有真实 source adapter。候选数据源继续为 `unverified`，task 11.1 保持未勾选。
- OpenSpec tasks 11.2–11.4 仍需用户另行明确授权。
- 未对任何非测试 PostgreSQL 执行 migration 或 backfill，未部署本变更，未激活历史分析调度；默认调度边界保持 `enabled=false`、`suspend=true`。
- 尚无真实历史数据覆盖、金额对账、60/250 日滚动质量或 272 交易日预热证据。
- 所有经验阈值继续保持 `needs-backtest`，没有规则晋级为 `validated`。
- 工作树同时包含其他 active changes 和用户修改；本计划只认领 `add-sector-continuity-metrics` 相关文件，不清理或覆盖无关变更。

## Next Step（下一步）

保持本地实现和所有真实来源开关为 fail-closed。task 11.1 的下一步是先补齐并审阅 source-specific taxonomy/membership/adjusted-price/benchmark probe adapters，再于上海工作日 15:30 后使用全新隔离输出路径运行真实 probe；只有四类脱敏报告、revision/checksum、沪深北覆盖和数据权利均审阅完成后才可勾选 11.1。指定数据库 migration/backfill、生产部署与调度激活继续分开授权。
