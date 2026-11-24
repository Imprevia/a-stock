## 1. 契约与纯函数层

- [x] 1.1 在 `contract.py` 把 `schemaVersion` 升到 `1.1`、`ruleVersion` 升到 `active-industry-scan-v2`，运行 `pytest -k contract` 断言两个常量与 `build_contract` 输出一致
- [x] 1.2 新建 `direction.py` 实现 `classify_direction(chg)`（`up`/`down`/`flat`/`suspended`，`FLAT_EPSILON=0.005`），用参数化测试覆盖 -17.26、-0.004、0、+0.004、+10.0、`None`、成交量为 0
- [x] 1.3 在 `direction.py` 实现 `market_median(changes)` 与 `relative_to_market(value, median)`，验证空序列、全 `None`、单样本时返回 `None` 而不是 0
- [x] 1.4 在 `direction.py` 实现 `aggregate_breadth(members, change_map)` 返回上涨/下跌/平盘/停牌家数、覆盖率与中位涨跌幅；测试断言停牌被剔出分母且 `up+down+flat+insufficient == 有效样本`
- [x] 1.5 在 `direction.py` 实现 `composite_tag(quadrant, direction)`，验证四象限 × 三种有效方向拼装，以及平盘与停牌方向的分支
- [x] 1.6 在 `direction.py` 实现 `breadth_status(coverage)`，覆盖率 <0.70 返回 `insufficient` 且数值置 `None`；测试覆盖 0.699 / 0.70 / 0.95 三个边界

## 2. 取数层

- [x] 2.1 `fuyao_client.py` 新增 `index_snapshot(thscodes)`，解析 `price_change_ratio_pct`，空值保留 `None`；用注入 runner 的测试验证一次传入 90 与 230 个代码、字段缺失与整体失败三种情况
- [x] 2.2 `fuyao_client.py` 新增 `market_snapshot()`，以 `limit=1000` 并发分页并聚合为 `thscode -> 涨跌幅`；测试断言分页拼接、跨页去重、`None` 涨跌幅保留
- [x] 2.3 `fuyao_client.py` 新增 `market_change_map()`，主路径用 `market_snapshot`，失败时回退 `sina_client.fetch_full_snapshot`；测试断言两条路径互斥、`source` 标签正确、都失败时返回空映射而不是抛异常
- [x] 2.4 新股过滤 fail-open：`_symbol_lookup` / `_filtered_ranking` 在「返回非空但全部 `list_date` 为 `null`」时跳过过滤并记 `degraded` 与告警；测试复现 2026-11-20 场景，断言不再退出码 2、榜单非空、告警可见

## 3. 编排层

- [x] 3.1 `ScanInputs` 增加 `change_map`、`board_changes`、`market` 字段与 fixture 解析；单测验证 fixture 缺省时字段为 `None` 而非 0
- [x] 3.2 `_summarize_rows` 增加 `direction` 与 `relativeToMarketPct`；测试断言 `up` / `down` / `flat` / `suspended` 四类行与相对值计算
- [x] 3.3 `build_result` 增加 `direction.market` 与 `directionSummary.byAmount` / `byTurnover`（含 `upAmountShare`）；测试断言 `up+down+flat == valid` 且占比口径为上涨股成交额除以榜内总成交额
- [x] 3.4 行业段补 `boardChangePct` / `hitUpCount` / `hitDownCount` / `member*` / `relativeToMarketPct` / `tag`；测试用半导体与银行样例断言两者方向相反且 `quadrant` 保持 `真实活跃`
- [x] 3.5 交集段补 `direction` 与 `relativeToMarketPct`；测试断言 2 涨 2 跌样例的分组计数与 JSON 一致
- [x] 3.6 `handoff` 每项补方向字段但清单不变；测试断言同一 fixture 只改涨跌幅时 `candidateThscodes` 不变
- [x] 3.7 方向降级矩阵：板块指数失败→`boardChangePct` 为 `null` 且 `degraded`；全市场快照失败→相对字段为 `null` 且 `degraded`；两者都失败→方向字段全不可用但双榜与交集完整
- [x] 3.8 `preopen` 场景：方向标注为前一交易日收盘并输出 `direction.basisNote`；测试断言该时点不出现「当日方向」表述

## 4. 渲染层

- [x] 4.1 `report.py` 主表增加「板块涨跌 / 上榜涨跌 / 相对」三列，缺失值渲染 `—`；快照测试断言列数与缺失值渲染
- [x] 4.2 `report.py` 新增「方向分组」段（活跃上涨 / 活跃下跌，组内按相对超额降序，空组显式说明）；测试断言分组条目与 JSON 同源、两份产物数值一致
- [x] 4.3 更新免责声明与质量段：方向同属 `needs-backtest`、停牌剔除、宽度覆盖率不足说明；测试断言文案存在且不含买卖语义

## 5. 文档同步

- [x] 5.1 更新 `SKILL.md`（用途、输出结构、方向字段读法、三条新限制、方向降级表）；用 `python3 scripts/check-docs-contract.py --mode=full` 验证
- [x] 5.2 更新 `references/metric-definitions.md`（方向判定、平盘 epsilon、相对基准、覆盖率门槛）与 `references/data-contract.md`（`index snapshot` / `market snapshot` 取数、降级矩阵、`list_date` fail-open）
- [x] 5.3 更新 `docs/repository-guide.md` 的两处映射（Skill 说明行与 `scripts/`、`references/` 表格行）
- [x] 5.4 新建 `docs/exec-plans/active/active-industry-scan-direction-plan.md` 并在 `docs/exec-plans/active/_index.md` 登记

## 6. 验证与收口

- [x] 6.1 离线全量测试：`.venv/bin/python -m pytest tests/test_a_stock_active_industry_scan_skill.py -q` 全绿，断网环境重跑仍全绿
- [x] 6.2 fixture 覆盖矩阵：新增方向 fixture，验证涨/跌/平/停牌、覆盖率不足、两个方向数据源分别失败、交集为空、`--level both`
- [x] 6.3 真实数据端到端（盘后）：核对半导体（-6.85% / 上榜 13 跌）、银行（+0.22% / 上榜 4 涨）、交集 2 涨 2 跌与手算一致
- [x] 6.4 门禁：`python3 scripts/check-docs-contract.py --mode=full` 与 `python -m src.trading_system.cli docs sync-check` 均通过
- [x] 6.5 收口：更新 plan 的 `Status` / `Completion Evidence` / `Remaining Gaps` / `Next Step`，并运行 `openspec validate add-active-industry-scan-direction --strict`
