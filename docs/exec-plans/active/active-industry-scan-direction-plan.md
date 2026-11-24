# A 股活跃行业扫描：方向层

> 上游方案：`openspec/changes/add-active-industry-scan-direction/`（proposal / design / spec delta / tasks 四件套）。
> 本 plan 只覆盖既有 `a-stock-active-industry-scan` Skill 的方向层扩展与 `list_date` 降级修复；行业打分仍由 `a-stock-qts04-sector-direction` 承担。

---

## Stage（阶段）

- 当前阶段：**Stage 4 — 验证收口**（已完成）
- 阶段序列：Stage 1 纯函数 + 取数（任务 1–2）→ Stage 2 编排（任务 3）→ Stage 3 渲染与文档（任务 4–5）→ Stage 4 验证收口（任务 6）
- 本轮边界：只扩展方向描述层。不做行业评分、不做涨停归因、不算相对强度分位、不新增历史回溯、不改四象限阈值与排序键、不改后端 API 与前端。

## Status（状态）

`done` — 30/30 任务完成。方向层已落地并通过离线全量测试、真实盘后端到端与两道文档门禁。

## 背景与决策

现状：方向原始值（新浪 `changepercent` → `RankRow.change_pct`）已经采集，但只作为 `rankings[].changePct` 展示列存在；`industry_map.count_hits` 只数家数，`quadrant.classify` 只看两个命中数。因此「放量下跌」与「放量上涨」在现有输出里是同一个标签。

2026-11-20 收盘实测（本次探索取得，作为验收基线）：

| 观测 | 数值 |
|---|---|
| 成交额榜 Top50 涨/跌 | 16 / 34 |
| 换手率榜 Top50 涨/跌 | 20 / 30 |
| 双榜交集 | 4 只：+3.71% / -7.21% / -5.32% / +10.03% |
| 半导体 | 板块 -6.85%；成交额榜命中 15 只中 13 跌，双榜并集命中 20 只中 16 跌，成分 7 涨 / 182 跌 |
| 银行 | 板块 +0.22%；成交额榜命中 4 只全涨（双榜并集同），成分 23 涨 / 19 跌 |
| 全市场 | 中位 -5.08%，313 涨 / 5236 跌 / 23 平 / 12 停牌 |
| 一级行业 | 绝对 2 涨 / 88 跌；相对上证 4 强 / 86 弱；相对市场中位 **53 强 / 37 弱** |

最后一行是本轮的关键依据：绝对方向与指数相对在单边行情下都没有区分度，等权中位相对才有。

主控确认的决策：

| 决策项 | 结论 |
|---|---|
| 方向基准 | 绝对（vs 昨收）+ 相对全市场中位，双输出 |
| 方向角色 | 只做标注与分组；不改排序、不筛 handoff、不评分 |
| 相对基准 | 全市场逐股涨跌幅**中位**（等权），不用指数 |
| 行业证据 | 板块指数 + 上榜股涨跌 + 全成分宽度，三类独立输出不合成 |
| 停牌 | `volume==0` 或涨跌幅 `null` 剔出分母，单列计数 |
| 平盘 | `|涨跌幅| ≤ 0.005` |
| 覆盖率门槛 | <70% → 宽度 `insufficient` 且 `null`（沿用 QTS-04-01-04） |
| 复合标签 | `quadrant` 语义不变，新增 `tag`（如 `真实活跃·下跌`） |
| 版本 | `schemaVersion` 1.1；`ruleVersion` `active-industry-scan-v2` |
| list_date 全缺失 | fail-open：跳过过滤 + `degraded` + 告警，不退出 2 |

## Acceptance（验收）

- [x] 双榜每行、交集每项、行业每项都带方向字段；`quadrant`、排序顺序与 `handoff.candidateThscodes` 与改前完全一致。
- [x] 行业同时给出板块指数涨跌、上榜股涨跌家数、全成分宽度与相对超额；三类证据同源于一次运行的同一时点。
- [x] 相对基准为全市场中位并显式输出，使相对值可复算；基准不可用时相对字段为 `null`，不得回退到指数或其他日期。
- [x] 停牌与无昨收样本剔出所有方向分母，`up + down + flat == valid`，停牌数单列。
- [x] 覆盖率 <70% 的行业宽度为 `null` 且标 `insufficient`，板块指数与上榜股方向仍输出。
- [x] Markdown 主表只加「板块涨跌 / 上榜涨跌 / 相对」三列，并新增活跃上涨 / 活跃下跌两个分组；空组显式说明，不放宽阈值。
- [x] JSON 与 Markdown 方向数值完全一致（Markdown 由 JSON 纯渲染）。
- [x] `list_date` 整体缺失时双榜非空、进程退出码 0、`quality.status=degraded` 且告警在 JSON 与 Markdown 均可见。
- [x] 方向两个数据源分别失败、同时失败三条路径都降级且其余段完整。
- [x] `preopen` 时方向标注为前一交易日收盘，不出现「当日方向」表述。
- [x] 离线 pytest 全绿且断网可重跑；不发起真实网络请求、不依赖真实凭据。
- [x] 全部方向结论 `needs-backtest`，不出现买入、卖出、仓位、目标价或个股推荐语义。

## Completion Evidence（完成证据）

规划阶段：

- `openspec new change "add-active-industry-scan-direction"` 创建成功（schema `spec-driven`）。
- 产物：`proposal.md`（Why / What Changes / Modified Capabilities / Impact）、`specs/active-industry-scan-skill/spec.md`（6 条 ADDED + 1 条 MODIFIED，共 16 个 scenario）、`design.md`（D1–D7 决策 + 风险 + 迁移 + 开放问题）、`tasks.md`（6 组 / 30 项任务，每项带验证方式）。
- 方向口径的全部依据来自 2026-11-20 收盘真实取数（见上表），非估算。

实现阶段（30/30 任务，`openspec/changes/add-active-industry-scan-direction/tasks.md` 全部勾选）：

- 新增 `scripts/direction.py`：`classify_direction` / `market_median` / `relative_to_market` / `aggregate_breadth` / `count_directions` / `breadth_status` / `composite_tag` / `summarize_direction` / `group_by_direction`，全部纯函数。
- `fuyao_client.py` 新增 `index_snapshot`（一次覆盖两级全部板块）与 `market_snapshot`（6 页并发）与 `market_change_map`（失败回退新浪全量快照）。
- `scan_pipeline.py`：`ScanInputs` 增加 `market` / `board_changes`；`_decorate_industries` 追加三类证据；`build_result` 增加 `direction` 与 `directionSummary`；`handoff.candidates` 带方向但 `candidateThscodes` 不变。
- `report.py`：主表加「板块涨跌 / 上榜涨跌 / 相对 / 方向标签」四列，新增「方向分组」段（组内按相对超额降序），页脚声明阈值与 `needs-backtest`。
- `_symbol_lookup` 增加 `list_date` 整体缺失 fail-open。

验证证据：

- 离线全量测试：`.venv/bin/python -m pytest tests/test_a_stock_active_industry_scan_skill.py -q` → **191 passed**，全程无网络。
- fixture 覆盖矩阵：新增 `tests/fixtures/active_industry_scan/direction.json`，覆盖涨/跌/平/停牌四类、覆盖率不足（62.5% → `insufficient`）、`--level both` 二级板块、交集为空，以及板块指数与全市场快照分别失败/同时失败。
- 真实盘后端到端（2026-11-20 收盘，`scan_pipeline.py` 无参数实跑，退出码 0）：
  - 全市场基准：中位 **-5.0763%**，313 涨 / 5236 跌 / 23 平 / 12 停牌，有效 5572 / 5584。
  - 成交额榜 16 涨 / 34 跌，上涨股成交额占比 30.2%；换手率榜 20 涨 / 30 跌，占比 52.0%。
  - 半导体：板块 -6.8475%，双榜并集命中 **4 涨 / 16 跌**（20 个命中；成交额榜单榜为 2 涨 / 13 跌），成分 7 涨 / 182 跌，方向 `down`/`member-median`，相对 -2.10%。
  - 银行：板块 +0.2151%，上榜 4 涨 / 0 跌，方向 `up`/`member-median`，相对 +5.26%。
  - 交集 4 只：华胜天成 +3.71%（up）、九阳股份 -7.21%（down）、宏景科技 -5.32%（down）、冰山冷热 +10.03%（up）。
- 上位核对：用当日缓存成分股独立重算半导体命中集合，得 20 个命中、4 涨 / 16 跌，与管线输出一致；全部行业满足 `hit*` 与 `member*` 两组分量各自求和等于总数。
- 门禁：`python3 scripts/check-docs-contract.py --mode=full` → 通过（代码 6 / 文档 4 / plan 2）；`.venv/bin/python -m src.trading_system.cli docs sync-check` → 通过；`openspec validate add-active-industry-scan-direction --strict` → valid。

实现中修正的两处口径缺陷（由实际数据暴露，已补测试）：

1. 方向分组原设 5 条上限，真实数据下会把半导体（相对超额排第 9、当日最显著的下跌行业）静默截掉。改为**不设第二重上限**：分组是已由 `--top-sectors` 截断后的行业表的完整划分。
2. 停牌股在榜单行里 `changepercent` 返回 0，原实现记成「平盘」。改为用该行自身 `amount` 作停牌提示，零成交记 `suspended`。

## Remaining Gaps（剩余缺口）

- **方向阈值全部 `needs-backtest`**：平盘 epsilon 0.005、覆盖率 70% 均为经验值，未做收益验证。
- **方向分组序**：组内按相对超额降序，是阅读顺序而非信号排序；未验证该顺序对未来收益有区分度。
- **`--now` 仍不是历史回溯开关**：方向层同样无法还原「10:30 那一刻的方向」，只能描述调用时点。
- **等权中位基准与板块指数不同源**：行业同时给加权（`boardChangePct`）与等权（`memberMedianChangePct`），两者口径差异需在文档持续说明，避免被当成同一指标。
- **`reportId` 不纳入方向配置哈希**：与 QTS-04 的 `config` 参与编号不同，此处不改编号规则，属已知限制。
- **二级行业篇幅**：230 个板块的指数快照已验证可单次返回（0.58s），但 `--level both` 下行业表达 320 行、方向分组按 320 行划分，可读性未评估；当前仅建议默认 `--level 1`。
- **`list_date` 数据源健康度未知**：11-19 有值、11-20 全为 null，属上游回归；fail-open 只保证 Skill 可用，不修复数据源。
- **仓库全量 `pytest tests` 存在与本变更无关的收集期冲突**：`a-stock-active-industry-scan` 与 `a-stock-qts04-sector-direction` 各自都有一个名为 `fuyao_client.py` 的模块，两个测试文件都把它插入 `sys.path[0]`。当两个文件在同一进程内收集时，后者导入到前者的模块并因缺少 `FuyaoDegraded` 而失败（已用 `git worktree` 在基线提交 `8d5d144` 上复现，属既有缺陷）。分别运行两者均通过（本 Skill 191 passed、qts04 90 passed）；`pytest tests --ignore=tests/test_a_stock_qts04_sector_direction_skill.py` → 1952 passed / 101 skipped。修复需给其中一个模块改名或改用包内相对导入，超出本变更边界。

## Next Step（下一步）

本 change 的 30 项任务与验收项已全部完成，已于 2026-11-24 归档到 `openspec/changes/archive/2026-11-24-add-active-industry-scan-direction/`，spec delta 已同步进主规格 `openspec/specs/active-industry-scan-skill/spec.md`。

后续若要继续推进，候选顺序：

1. **方向层的收益验证**：把 `needs-backtest` 降级为可验证规则，需要多日「方向 × 象限」面板与次日收益对齐；这是唯一能解除当前全部阈值不确定性的路径。
2. **`list_date` 上游回归跟踪**：11-19 正常、11-20 全 null，fail-open 只保证可用性；需另开 change 排查数据源或用替代口径（如上市公告日）补位。
3. **`--level both` 输出瘦身**：若实测两级同时输出不可读，再决定是分组只列一级，还是分组独立于行业表另设上限。
