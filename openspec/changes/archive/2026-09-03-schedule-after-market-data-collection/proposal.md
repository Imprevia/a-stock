## Why

市场环境看板已经具备五类数据的独立采集、失败隔离和本地快照读取，但当前只能通过数据管理页或 CLI 手工触发。盘后复盘依赖人工操作会导致当天 SQLite 快照缺失，用户首次打开页面时只能看到旧数据或缺失状态；现有交易规则 GitHub Actions 又不会写入看板的持久卷，不能解决该问题。

## What Changes

- 新增可配置的盘后自动采集任务，在上海时区的工作日结算后采集 `core`、`breadth`、`limits`、`sectors` 和 `activeDirection`。
- 自动任务复用现有 collection coordinator、SQLite task/run、lease、精确日期校验和 materialized aggregate，不建立第二套采集或存储逻辑。
- 保持五类数据独立完成和独立落盘；单项失败时继续其他任务，并以 `partial` 或 `failed` 结果留痕，允许后续在 `/data-collection` 单项补采。
- 为 k3s Kustomize 与 Helm 部署增加可关闭、可配置时区和 cron 表达式的 `CronJob`，挂载与看板相同的持久卷并禁止并发重叠。
- 保留跨平台 CLI 作为开发和故障恢复入口；本次不增加本机常驻调度器，也不让 GitHub Actions 远程写入部署实例。
- 增加调度日期解析、周末不触发、节假日不写入跨日期数据、重复运行去重、超时/退出码、日志和部署清单验证要求。

## Capabilities

### New Capabilities

- `after-market-data-collection-scheduling`: 定义五类市场环境数据的盘后自动触发、失败隔离、日期边界、重复运行保护、部署配置和可观测结果。

### Modified Capabilities

无。

## Impact

- 后端：`src/market_environment/cli.py`、collection coordinator 的调度调用边界，以及必要的交易日/结算日期解析辅助逻辑。
- 部署：`deploy/k3s/` 新增 CronJob 资源；`deploy/helm/a-stock/` 新增可配置的 CronJob 模板和值。
- 持久化：继续使用 `MARKET_ENVIRONMENT_SNAPSHOT_PATH` 指向的 SQLite 与现有 PVC，不新增数据库或消息队列。
- 文档：更新市场环境产品规格、架构、runbook、仓库状态和新的 active exec plan。
- 验证：增加 CLI/调度日期、部分失败、并发策略、Kustomize 和 Helm 渲染测试；不改变现有读取 API 契约。
