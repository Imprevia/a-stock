## Why

当前扶摇已经作为 `limits` 的主源接入，但 `core`、`breadth`、`sectors` 和 `activeDirection` 仍依赖各自的多源/东方财富采集链路。扶摇公开能力覆盖指数行情、全市场快照、行业/指数目录和特色数据，但现有仓库尚未证明这些接口满足精确日期、字段完整性、分页/排序、历史窗口和降级契约，因此需要一个可审计的分阶段验证与迁移能力，避免一次性切换造成历史数据或质量状态失真。

## What Changes

- 新增扶摇数据源能力矩阵，逐数据集记录端点、字段映射、日期证据、历史覆盖、分页/排序、限流和权限结果。
- 为 `core`、`breadth`、`sectors`、`activeDirection` 设计并实现可独立启用的 Fuyao adapter；保留现有输出 payload、质量状态、精确日期和失败保留语义。
- 增加 provider capability probe 和 shadow 对账：扶摇结果与当前 provider 并行获取、按规范证券身份或指数代码比较，并输出差异、缺失字段和不可替换原因。
- 采用按数据集 opt-in 的迁移开关；默认继续使用当前 provider。只有通过字段、日期、完整性和对账验收的数据集才允许切换。
- 保留 `limits` 当前“扶摇主源 + 东方财富降级/交叉核对”实现，不重写或削弱已完成的 limits 事实契约。
- 失败、权限不足、限流、历史日期不可证明或对账不通过时，必须返回 `degraded` / `insufficient` / `failed-retained`，不得把 shadow 结果写成成功快照。

## Capabilities

### New Capabilities

- `fuyao-market-data-provider`: 提供扶摇 provider 能力发现、字段/日期契约验证、按数据集适配、shadow 对账和受控 opt-in 切换。

### Modified Capabilities

- `market-data-collection-management`: 采集任务需要报告实际 provider、shadow 对账状态和切换开关，同时保持五类任务独立、状态读取不调用 provider、失败保留和精确日期约束。

## Impact

- 后端：`src/market_environment/fuyao.py`、`src/market_environment/providers.py`、`src/market_environment/collection.py` 以及 provider/质量契约测试。
- 持久化与 API：保持既有五类快照主键和公开字段；新增 provider revision、能力验证和对账元数据时必须可选且不污染旧客户端。
- 配置与部署：新增独立扶摇 provider 配置/Secret 和按数据集开关；默认关闭新数据集切换，不能把 API key 写入 values、日志或响应。
- 文档：同步 `docs/architecture.md`、`docs/runbooks.md`、市场环境产品规格和相关 OpenSpec delta；真实 provider smoke 只能在盘后或显式本地命令、隔离数据库中运行。
- 验证：新增离线 fixture、契约测试、shadow 差异报告和隔离 PostgreSQL smoke；不把真实 provider 访问混入 PR 确定性门禁。
