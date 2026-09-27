## Why

2026-09-24 生产的 `breadth` 走 TDX 备用路径后，把盘后包中所有有价格的证券都计入了市场广度：上涨 1,976、下跌 8,221、平盘 41,694，共 51,891 行。结果内部三类计数虽然相加一致，但统计对象已经从约 5,000 只普通 A 股股票扩大成了包含基金、债券、指数等证券的全证券集合，导致下跌家数、上涨占比、中位数和后续市场研判均失真。

当前 TDX 解析器没有提供证券类型字段，`breadth` 直接消费 `package.rows`；而东方财富路径仍按股票 universe 过滤。需要在 TDX fallback 中建立可审计的普通 A 股股票筛选边界，并在无法证明筛选结果完整时保持降级或不足状态，避免再次把全证券包当作全 A 股票快照。

## What Changes

- 为 TDX 盘后包增加按市场和证券代码规则识别普通 A 股股票的筛选阶段，明确排除基金、债券、指数、权证及其他非普通股证券。
- 让 `breadth` 和 TDX 派生的 `activeDirection` 只使用筛选后的普通 A 股集合；`breadth` 的上涨、下跌、平盘、有效样本数和涨跌幅中位数，以及 `activeDirection` 的成交额 Top-N，均不得混入非股票证券；保留现有公开字段与前端展示契约。
- 在质量元数据和 warning 中记录过滤前行数、保留行数、排除行数及分类边界；无法证明三地市场覆盖或筛选后样本完整时，不输出伪造的 `ok`/成功统计。
- 为 TDX 行规范化、市场分类、混合证券包、边界代码、缺失/异常身份和过滤后样本不足补充离线 fixture 与回归测试。
- 为已有错误的精确日期快照定义受控重采集/保留策略：不直接改数据库，不跨日期回填；修正后的采集必须重新通过 exact-date、checksum、质量状态和聚合验证。
- 同步市场广度、快照缓存、架构、运行手册、状态记录和 active exec plan，明确 TDX fallback 的证券宇宙口径。

## Capabilities

### New Capabilities

<!-- No new standalone capability; this is a correction to existing market-data behavior. -->

### Modified Capabilities

- `market-breadth-page`: 明确市场广度的统计 universe 必须是可证明的普通 A 股股票集合；TDX fallback 不能把全证券盘后包直接作为 breadth 样本。
- `active-direction-data-collection-stability`: TDX 派生容量方向必须复用同一版本化普通 A 股 universe，避免成交额 Top-N 被基金、债券或其他证券污染。
- `market-data-snapshot-cache`: 增加 fallback 过滤质量、样本完整性和错误快照重采集的可审计要求，失败时继续保持 `failed-missing` / `failed-retained` / `insufficient` 语义。

## Impact

- 代码：`src/market_environment/tdx_daily.py`、`src/market_environment/providers.py`，以及 TDX fixture、provider、collection、快照和 API 契约测试。
- 文档：`docs/architecture.md`、`docs/runbooks.md`、`docs/status.md`、相关 `docs/exec-plans/active/*.md`。
- API：不删除或重命名现有 `breadth` 字段；质量对象增加可选审计字段或 warning。
- 数据：需要对 2026-09-23、2026-09-24 等已使用错误证券 universe 的 TDX `breadth` 和 `activeDirection` 快照执行受控重采集；不得把旧错误值继续作为无警告的有效股票证据。
- 部署：本 change 不直接执行生产发布、CronJob 激活、数据库写入或 PVC 操作；这些动作需在 apply 完成后按 runbook 单独授权。
