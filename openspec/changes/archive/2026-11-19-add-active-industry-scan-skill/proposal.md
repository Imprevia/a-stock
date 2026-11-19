## Why

盘中判断「资金正在进入哪些行业」目前没有可复算的入口：`a-stock-qts04-sector-direction` 是盘后 Skill，需要完整交易日数据才能算 5 日/20 日相对强度与成交额增量，盘中问它会得到 `insufficient` 或延迟到收盘后。

实测证明盘中横截面排名本身是可靠的：2026-11-19 用 10:30 累计量重建的换手率榜与收盘榜 Spearman 相关系数 0.982，Top50 重合 43/50；成交额榜 36/50。因此「盘中拿不到结论」并非数据质量限制，而是缺少一个只依赖横截面、不依赖历史窗口的采集口径。

同时，单看换手率榜会误导行业判断：2026-11-19 换手率 Top50 散落在 31 个一级行业，成交额 Top50 集中在 24 个且半导体独占 14 只，两榜交集仅 5 只。只用一个榜无法区分「资金规模」与「筹码交换」，需要双榜并行并交叉。

## What Changes

- 新增 Agent Skill `a-stock-active-industry-scan`，位于 `.agents/skills/a-stock-active-industry-scan/`。
- 新增双榜采集口径：成交额榜与换手率榜并行，各取 400 只候选池后过滤上市不足 250 日的新股，再取前 50。
- 新增行业聚合：用 fuyao 同花顺一级与二级板块成分股把双榜股票映射为行业，输出每个行业的两榜命中数与四象限归属。
- 新增双榜交集输出：同时进入两个 Top50 的股票及各自排名。
- 新增时点状态机：`preopen` / `intraday` / `lunch` / `settling` / `closed`，随任意时点运行都返回明确的数据截止时刻与已过 bar 数。
- 新增交接接口：输出候选行业 thscode 列表，交由 `a-stock-qts04-sector-direction` 按 `QTS-04-01-01` 至 `-05` 正式打分，本 Skill MUST NOT 自行评分。
- 明确不新增数据集、不写入 `snapshot_entries`、不修改后端 API 与前端。

## Capabilities

### New Capabilities

- `active-industry-scan-skill`: 盘中可用的双榜行业活跃度扫描能力，包含双榜采集与降级、新股过滤、行业聚合与四象限、双榜交集、时点状态机、交接契约与离线可验证性。

### Modified Capabilities

无。本变更不改动现有 capability 的需求：`qts04-sector-direction-skill` 与 `qts04-theme-layer-skill` 的行为不变，本 Skill 只向其输出候选行业列表；`market-data-collection-management` 与数据集集合不受影响。

## Impact

- 新增目录 `.agents/skills/a-stock-active-industry-scan/`（SKILL.md、scripts/、references/、.gitignore）。
- 新增运行时缓存目录 `.cache/active-industry-scan/`，不提交 git，不写入数据库。
- 需在 `docs/repository-guide.md` 的 Skill 映射表中登记该 Skill。
- 需新建 `docs/exec-plans/active/` 下的实施计划，满足 AGENTS.md 硬规则 2/3。
- 依赖外部命令 `hithink-finance`（fuyao 凭据链）与新浪行情接口；不新增 Python 运行时依赖。
- 不涉及 `src/`、`apps/`、`deploy/`、`trading-rules/` 的改动。
- 全部输出规则状态保持 `needs-backtest`，不产生买入、卖出、仓位或个股推荐语义。