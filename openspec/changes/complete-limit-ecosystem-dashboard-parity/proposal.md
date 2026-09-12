## Why

第 01 章第 03 篇文档要求用涨停、跌停、炸板和连板晋级共同判断短线热度、封板质量、接力成功率和风险扩散，但当前页面只有五项当日事实卡，晋级率还是未被后端契约支持的前端字段。当前主分支也没有可用的 limits 快照或证券级跨日事实，因此页面无法审计分母、梯队、制度分层、历史变化和数据不足原因。

需要把原版文档、量化版规则和页面实现收敛为一个可追溯的完整看板契约：可用证据直接展示，数据不足明确标注，未完成回测的规则不能伪装成确定性评分；同时保留旧五字段 API、精确日期快照、失败保留和 provider-free GET 约束。

## What Changes

- 新增第 01 章第 03 页的完整涨停、跌停、炸板和晋级生态看板，覆盖当日事实、公式分子/分母、质量元数据、缺失原因和局部刷新状态。
- 增加严格的跨交易日晋级证据：昨日合资格收盘涨停样本、今日晋级数、晋级率、样本日期、证券身份、交易所/板块、ST/新股窗口、适用涨跌幅制度和收盘涨停状态。
- 增加首板、二板、三板、四板以上连板梯队，以及涨跌停/炸板按制度、板块和风险位阶的可追溯分层；无法验证的样本排除并记录原因。
- 增加近 5 日变化、250 日分位、有效观测数、覆盖率、置信度、规则输入、热度与质量背离、连续跌停风险和确认/失效条件；规则仍保持 `needs-backtest`，不把经验阈值升级为 `validated`。
- 改进第 03 页的 loading、missing、partial、fallback、failed、degraded、insufficient 和 `null` 展示，刷新失败时保留同日期旧证据并显示 warning，不用零值填补。
- 将后端数据采集、SQLite 迁移、精确交易日解析、逐股事实、聚合和 API 校验接入现有 collection/refresh/lease/materialized aggregate 边界；普通 GET 不启动 provider，不跨日期回填。
- 以历史 `agent/backend/gyt-21-refresh-stale` 的 V1 晋级实现和离线 fixtures 作为迁移参考，采用函数级整合，禁止整体 cherry-pick 其旧的调度、部署和 refresh 基线。
- 在离线固定快照验证通过后，另行安排获授权的盘后真实 provider smoke；真实 provider 无法证明日期、制度或收盘状态时必须返回 `failed` / `insufficient`，不得猜测或伪造数据。

## Capabilities

### New Capabilities

- `limit-ecosystem-dashboard-parity`: 为第 01 章第 03 页提供涨停、跌停、炸板、晋级和连板生态的完整证据看板、跨日数据契约、质量状态、缺失语义、采集与验证边界。

### Modified Capabilities

无。现有市场数据快照、采集管理和响应兼容性要求继续作为本 capability 的基础约束；本变更在新 capability 中定义 limits 细节和页面扩展，避免改写其他数据集的既有契约。

## Impact

- 后端：`src/market_environment/schemas.py`、`providers.py`、`collection.py`、`service.py`、`snapshot_store.py`、`refresh.py`、`cli.py`，以及逐股事实、交易日和晋级聚合模块。
- 前端：`apps/market-environment-dashboard/src/App.vue`、`types.ts`、`styles.css`，以及第 03 页专用测试和响应式检查。
- 数据与存储：SQLite 加法迁移、`trading_sessions`、`limit_security_facts`、数据集/行校验和、相邻交易日索引和 materialized aggregate 重建。
- 文档与运行：市场环境产品规格、架构、runbook、active plan、状态和证据索引需要同步更新；不改变交易规则 ID、权重、覆盖清单或 `needs-backtest` 状态。
- 验证：新增固定离线 fixtures、API/provider/service/collection/store/前端测试、provider-free 历史 GET 检查、迁移回滚检查和独立盘后 smoke 门禁；不在本 change 中执行生产部署或未经授权的真实数据采集。
