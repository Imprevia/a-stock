## Why

`a-stock-active-industry-scan` 当前只回答「哪些行业最活跃」，不回答「这些行业在涨还是在跌」。四象限由成交额榜与换手率榜的命中数决定，方向信息虽然已从新浪接口采集（`changepercent` → `changePct`），却没有进入任何聚合、标签或排序。

2026-11-20 收盘实测说明这不是理论缺陷：

- 成交额榜 Top50 有 34 只下跌，换手率榜 Top50 有 30 只下跌；
- 半导体板块 -6.85%（上榜 15 只中 13 只下跌）与银行板块 +0.22%（上榜 4 只全涨）在现有输出里同为「真实活跃」；
- 换手率榜被标为「小盘情绪」的个股包括 -16.65% 与 -17.26%。

高成交额与高换手只说明资金规模与筹码交换强度，不说明方向。缺少方向层时，用户会把「放量下跌」误读为「资金进场」，而这两个结论在交易含义上相反。当天同时发现 `symbol list` 返回的 5584 只股票 `list_date` 全部为 `null`，导致两只榜的候选池被全部剔除、进程以退出码 2 结束，新股过滤的降级路径需要一并修正。

## What Changes

- 新增**方向层**，与活跃度四象限正交：方向只做描述与分组，不参与排序、不筛选 handoff 候选、不评分。
- 个股新增 `direction`（`up` / `down` / `flat` / `suspended`）与 `relativeToMarketPct`（相对全市场中位涨跌幅，百分点）。
- 行业新增三类方向证据：板块指数涨跌幅（`boardChangePct`）、上榜股涨跌家数（`hitUpCount` / `hitDownCount`）、全成分股宽度（`memberUpCount` / `memberDownCount` / `memberFlatCount` / `memberCoverage` / `memberMedianChangePct`）。
- 新增行业复合标签 `tag`（如 `真实活跃·下跌`），`quadrant` 字段语义与四象限判定规则保持不变，避免破坏既有要求与下游读取。
- 新增市场基准块 `direction.market`：全市场有效样本数、停牌数、中位涨跌幅、上涨/下跌/平盘家数，作为相对方向的分母。
- 新增 `directionSummary`：两张榜各自的涨/跌/平家数与上涨股成交额占比。
- 新增数据源与降级：`hithink-finance index snapshot` 提供板块指数涨跌（一次调用覆盖 90 个一级或 230 个二级板块）；`hithink-finance market snapshot` 提供全市场逐股涨跌幅（6 页并发约 0.4–0.7 秒）。
- 修订新股过滤降级：当 `symbol list` 返回非空但全部缺少 `list_date` 时，降级为「不过滤 + 告警」并保持榜单可用，不再产出空结果与退出码 2。
- `schemaVersion` 1.0 → 1.1（纯新增字段）；`ruleVersion` → `active-industry-scan-v2`（新增方向口径与阈值）。
- 同步 `SKILL.md`、`references/metric-definitions.md`、`references/data-contract.md`，补方向层口径、失败路径与平盘/停牌定义。
- 新增离线测试：方向判定（涨/跌/平/停牌）、宽度聚合与覆盖率门槛、相对基准、板块指数与全市场快照的降级路径、`tag` 组合，以及 `list_date` 全缺失的 fail-open 行为。

非目标：不计算行业评分或相对强度分位、不做涨停/跌停归因（属 `a-stock-qts04-theme-layer`）、不改变四象限阈值与排序键、不新增历史回溯或数据库写入、不改动后端 API 与前端。

## Capabilities

### New Capabilities

无。方向层是既有扫描能力的扩展，不引入新的 capability 路径。

### Modified Capabilities

- `active-industry-scan-skill`: 新增方向层要求（方向与活跃度正交、绝对与相对双基准、停牌剔除与覆盖率门槛、方向分组输出、方向数据源降级），并修订新股过滤在上市日期整体缺失时的降级行为。

## Impact

- 修改 `.agents/skills/a-stock-active-industry-scan/scripts/scan_pipeline.py`（编排、方向块、市场基准、降级）、`sina_client.py`（停牌识别所需的成交量为 0 判定）、`report.py`（方向列与方向分组段）、`contract.py`（schema/rule 版本）、`fuyao_client.py`（新增 `index snapshot` 与 `market snapshot` 调用、`list_date` 缺失的 fail-open）。
- 新增 `.agents/skills/a-stock-active-industry-scan/scripts/direction.py`（纯函数：方向判定、宽度聚合、相对基准、复合标签）。
- 修改 `.agents/skills/a-stock-active-industry-scan/SKILL.md` 与 `references/` 两份口径文档。
- 修改 `tests/test_a_stock_active_industry_scan_skill.py` 与 `tests/fixtures/active_industry_scan/`（补正负涨跌幅、停牌、板块指数、全市场快照 fixture）。
- 更新 `docs/exec-plans/active/active-industry-scan-direction-plan.md`（新建）与 `docs/exec-plans/active/_index.md`（登记）。
- 依赖既有外部命令 `hithink-finance`（fuyao 凭据链）与新浪行情接口；不新增 Python 运行时依赖，不写入数据库，不涉及 `src/`、`apps/`、`deploy/`、`trading-rules/`。
- 全部方向结论保持 `needs-backtest` 状态，不产生买入、卖出、仓位、目标价或个股推荐语义。
