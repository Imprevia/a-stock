# 完整涨跌停生态看板对齐计划

## Stage（阶段）

Stage 1 — 契约、事实存储、采集聚合、前端看板和离线验证；真实 provider smoke 仅在单独授权的盘后窗口执行。

## Status（状态）

`completed-with-insufficient-provider-evidence` · 离线实现、门禁、release-readiness NO-GO review、真实 provider smoke 和 promotionQuality 判定已完成；provider 字段不足，生产发布保持禁止。

## Scope（范围）

- 第 01 章第 03 页 `涨停、跌停、炸板和连板晋级` 的完整文档对齐。
- 保留旧五字段 limits API，新增严格晋级、证券事实、梯队、制度/板块分层、历史序列和质量字段。
- 不修改 `QTS-01-03-01` 至 `QTS-01-03-05` 的 ID、权重、覆盖清单或 `needs-backtest` 状态。
- 当前工作树已有 TrueNAS 调度相关 dirty changes，实施时只增量修改本变更范围，不整体 cherry-pick `agent/backend/gyt-21-refresh-stale`。

## Acceptance（验收）

- 页面展示交易日、来源、observations、抓取时间、cache/provider quality、warning、五项当日事实、晋级分子/分母、梯队、制度/板块分层和历史覆盖状态。
- 普通历史 GET provider 调用数为 0；缺失、失败、降级和分母不可计算均保持 `null` / `insufficient` / `degraded` 语义。
- SQLite 加法迁移、精确交易日、证券事实、checksum、lease/CAS、失败保留和旧五字段兼容验证通过。
- 第 03 页完整、空、部分、刷新失败状态在桌面和 390px 移动端可读，页面无横向溢出。
- 固定离线测试、前端构建、OpenSpec strict、docs-contract full 和 `git diff --check` 通过。
- 未经新授权不执行真实 provider smoke、生产 SQLite/PVC 访问或部署。

## Completion Evidence（完成证据）

- OpenSpec `spec-driven` 变更已通过 `openspec validate complete-limit-ecosystem-dashboard-parity --strict`。
- limits 契约、事实规范化、SQLite 加法迁移、精确交易日、checksum、lease/CAS、失败保留和 provider-free GET 已由固定离线测试覆盖。
- Python limits/API/collection/service/store 测试通过；最近一次全量离线测试为 `554 passed, 3 failed`：2 个失败来自工作区既有 TrueNAS CronJob 时区/调度清单差异，另 1 个性能边界失败已单独重跑通过，均不属于本变更代码路径。
- 前端 Vitest `25 passed`，Vite production build 通过；390px 局部表格滚动、空/部分/失败/保留旧证据状态由组件测试和静态溢出规则覆盖。
- `docs-contract --mode=full` 通过（代码 12 / 文档 8 / plan 1），`git diff --check` 通过。
- 规则 `QTS-01-03-01` 至 `QTS-01-03-05` 的 ID、权重、250 日窗口和 `needs-backtest` 语义未改变。
- 2026-09-11 release-readiness 离线 NO-GO review 已完成：`MARKET_ENVIRONMENT_LIMITS_V1_ENABLED` 未设置时解析为 `false`；对现有本地 SQLite 使用 `sqlite3.Connection.backup()` 生成临时副本，副本 `PRAGMA quick_check=ok`、schema version `4`、保留 `snapshot_entries` 与 `trading_sessions`/`limit_security_datasets`/`limit_security_facts`，并在独立旧五字段 fixture 恢复副本上验证旧 payload 可读。回滚顺序固定为先关闭 limits V1，再恢复应用版本，保留 PVC、旧快照和新增事实表；当前文档和工作区均无生产 provider/PVC/部署执行授权。
- 2026-09-11 19:00（上海时区）已按授权执行真实 provider smoke：`MARKET_ENVIRONMENT_LIMITS_V1_ENABLED=1`、`MARKET_ENVIRONMENT_SNAPSHOT_PATH=/home/gyt/a-stock/.artifacts/market-environment/limits-smoke.sqlite3`、`--as-of 2026-09-11 --dataset limits --force`。隔离库 checksum 为 `1e27faba206da19d5d5d9c93a9cf114b8bf0dfa8662d1be7ceb3492ba6f83830`，run `1ddecba9dce44d6db6bfb9a6851c6f3a` / task `d4dfec337b004691bdcdc641d4606fa6` 终态为 `failed` / `failed-missing`，耗时约 `440ms`、observations `0`、source `none`；严格路径在 `limit_up` 第一逻辑池请求因 provider 缺少顶层交易日字段而停止，未继续请求其他池。隔离库未写入 session、manifest、fact 或 snapshot，未访问生产 SQLite/PVC。
- 对授权范围内候选前一真实交易日 `2026-09-10` 另行执行一次严格 limits provider 请求，结果同为 `failed`（`limit_up pool failed: provider response missing top-level session date`），`actualAsOf=null` 且 `persisted=false`；未增加隔离库写入或超出 limits 请求边界。
- smoke 后 provider-free 聚合返回 `promotionQuality=insufficient`、reason=`missing-session-evidence`，`promotionRatio=null`，当前日 `2026-09-11` 的前一真实交易日无法由 provider/本地 session 证据证明，未猜测为自然日前一天；因此不生成晋级率或规则结论。

## Remaining Gaps（剩余缺口）

- 真实 provider smoke 已执行但在 `limit_up` 首次响应缺少顶层交易日字段而 `failed-missing`；实际/前一交易日、交易所、制度、ST/上市窗口、板块和收盘状态仍未获得可用证明，系统继续保持 `promotionQuality=insufficient`。
- 250 日历史窗口、次日反馈和规则校准仍受数据覆盖限制，不能提前标记为 validated。
- 若要重新验证，需 provider 修复/更换为能返回顶层和逐行实际日期的严格数据源，并重新使用新的隔离 SQLite；不得复用本次失败库作为成功证据。
- release-readiness 已仅完成离线 NO-GO 审查；生产 PVC 的现场 UID/容量、实际备份目标和恢复演练仍不能在无生产访问授权时宣称完成。
- 全量测试仍受工作区既有 `deploy/k3s-native-scheduled/market-data-collection-cronjob.yaml` dirty 差异影响（期望 `30 16` + `Asia/Shanghai`，当前清单为 `30 8` 且省略 `timeZone`）；该文件未为本变更回滚或改写。

## Next Step（下一步）

本次授权 smoke 已完成并判定 `promotionQuality=insufficient`。后续只有在 provider 能证明顶层/逐行日期及制度、身份、收盘状态后，才重新运行隔离两日 smoke；在此之前不启动生产发布，不写生产 SQLite/PVC，不修改交易规则状态。
