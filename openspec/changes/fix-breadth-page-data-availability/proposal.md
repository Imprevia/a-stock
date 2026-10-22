## Why

第 02 页当前会在当日市场广度摘要已经可用时，因为 V2 breadth history 的 PostgreSQL 首页查询返回 500 而放弃当日上涨家数、下跌家数和中位数，并整页回退到旧接口。与此同时，历史覆盖不足 60 个精确交易日是合法的证据不足状态，页面却没有把“当日事实可用”和“历史分位不足”清晰分开，导致用户把可用的当日数据误解为整体缺失。

## What Changes

- 修复 breadth/limits V2 历史首页与后续页的 PostgreSQL 可选日期和 cursor 查询，使无 cursor、无日期筛选的正常请求稳定返回有界结果而不是 500。
- 将第 02 页的当日 breadth 摘要与历史序列独立加载、独立保留；历史读取失败不得清空已成功读取的当日计数，也不得关闭整个 V2 读取通道。
- 统一 V2 breadth history 的展示语义：只展示最近 5 个已验证交易日，同时按真实的 60 个最低有效观测和 250 日窗口报告覆盖率，不把实际返回条数伪装成所需样本数。
- 保留少于 60 个精确日期快照时分位指标为 `null` / `insufficient` 的质量边界，不降低阈值、不补 0、不使用跨日期数据。
- 规划一个显式、有限、可审计的 breadth 历史补齐路径：只处理能由 TDX 盘后包证明精确日期的交易日；真实 provider 调用和生产写入仍需另行授权，失败不得覆盖既有同日成功快照。
- 补充真实 PostgreSQL adapter、HTTP 契约、前端局部失败容错和桌面/390px 页面回归测试，并同步架构、产品规格、runbook 与 active plan。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `market-breadth-page`: 区分当日摘要可用性与历史分位覆盖，规定历史失败时保留当日数据、最近 5 日展示和可审计的历史补齐边界。
- `ai-market-data-api`: 强化 breadth/limits 历史资源的 PostgreSQL 首页、筛选和 cursor 查询契约，以及单个子资源失败时的渐进迁移兼容行为。

## Impact

- 后端：`src/market_environment/infrastructure/persistence/postgres/v2_market_data.py`、V2 query/router 边界，以及受控历史采集/CLI 入口（若 capability probe 证明可行）。
- 前端：`apps/market-environment-dashboard/src/stores/market.ts`、第 02 页派生与历史展示。
- 测试：真实 PostgreSQL V2 read adapter/HTTP tests、前端 store/page tests、provider-free 与零写入护栏。
- 文档：`docs/architecture.md`、`docs/product-specs/market-environment-dashboard.md`、`docs/runbooks.md`、`docs/repository-guide.md` 和新的 active exec plan。
- 运行边界：普通 GET 继续只读本地精确日期证据；本 change 不授权生产回填、provider smoke、部署或数据库直接修改。
