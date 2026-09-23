## Why

当前 `breadth`、`activeDirection` 依赖东方财富 `push2`/`push2delay`，当两个域同时断连时，盘后采集只能记录失败或保留旧快照。`a-stock-data` 提供按指定交易日获取通达信官网盘后全市场日线包的实现，可为这两个数据集增加独立于东方财富的盘后备用路径。

## What Changes

- 增加通达信盘后全市场日线包的受控读取和字段归一化，保留请求日期、源侧日期和抓取时间证据。
- 将该数据源接入 `breadth` 的备用链，使用完整有效市场样本计算上涨家数、下跌家数、平盘家数和涨跌幅中位数。
- 将该数据源接入 `activeDirection` 的备用链，按成交额降序校验至少 30 个有效样本，并生成现有 Top-30/Top-10 payload。
- 为盘后包增加日期、文件可用性、格式、证券身份、数值字段和样本完整性校验；任一关键证据缺失时保持 `insufficient` 或失败语义。
- 保留现有 Eastmoney 主源和延迟源顺序；只有 Eastmoney 链失败后才尝试通达信盘后包，且失败 warning 必须保留。
- 不改变 `sectors`、`limits`、`core` 的 provider 路由，不把 GitHub 仓库当作运行时数据 API 或静态快照源。
- 不允许使用当前日期包替代历史日期，不允许用其他日期、零值或代码字符串冒充缺失名称。

## Capabilities

### New Capabilities

<!-- No standalone capability is introduced; this is a provider extension to existing collection contracts. -->

### Modified Capabilities

- `market-data-collection-management`: 允许 `breadth` 和 `activeDirection` 在既有 Eastmoney 链失败后使用日期可证明的通达信盘后包，同时保持独立任务、精确日期、失败保留和 provider-free status 语义。
- `active-direction-data-collection-stability`: 将通达信盘后包加入 active-direction 的备用链，并要求它满足与 Eastmoney 相同的代码、名称、成交额、样本数和降序校验。

## Impact

- 后端：`src/market_environment/providers.py` 及新增的盘后包客户端/解析模块；`breadth` 和 `activeDirection` 的 provider 测试与 collection integration 测试。
- 文档：`docs/architecture.md`、`docs/runbooks.md`、相关 active plan 和本 change 的设计/任务文档。
- 运行时依赖：需要使用 `a-stock-data` 中 Apache-2.0 许可的实现思路或兼容提取代码；不得直接依赖 GitHub 在线内容作为生产运行时依赖。
- 数据质量：通达信盘后包不可用、尚未发布、日期不匹配、字段不足或名称无法可信解析时，数据仍显示为 `degraded`、`insufficient` 或失败，不写入伪成功快照。
- 不涉及数据库 schema、公开 API 字段、前端页面结构、`sectors`/`limits` 路由或生产部署写操作。
