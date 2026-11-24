## Context

`.agents/skills/a-stock-active-industry-scan/` 是一个离线可验证的 Agent Skill：`scan_pipeline.py` 负责编排与 I/O，`sina_client.py` / `fuyao_client.py` 负责取数，`quadrant.py` / `industry_map.py` / `percentile.py` 是纯函数，`report.py` 只做 JSON → Markdown 渲染。本次改动只扩展方向层，不改动四象限判定与排序键。

现状约束：

- 方向原始值已经存在：新浪 `getHQNodeData` 的 `changepercent` 已解析为 `RankRow.change_pct`，但只作为 `rankings[].changePct` 展示列，不参与任何聚合。
- 行业段只统计两榜命中数（`industry_map.count_hits`），没有方向证据。
- 行业成分股按日缓存，一级 90 个板块覆盖 5580 只且无重复归属，是干净的全集划分；二级 230 个板块同样可枚举。
- `hithink-finance` 提供 `index snapshot`（板块指数实时快照，一次可传 90/230 个代码，实测全部返回）与 `market snapshot`（全市场逐股快照，`limit=1000` 分 6 页，串行 2.0 秒、并发约 0.4–0.7 秒，`total=5584`）。
- 盘中分位仍受「累计量与全天分布不可比」限制；方向不受该限制，因为涨跌幅是同一时点横截面量，但 `preopen` 的方向反映前一交易日收盘。
- 2026-11-20 实测 `symbol list` 的 5584 条记录 `list_date` 全部为 `null`，现有过滤把候选池清空并让进程以退出码 2 结束，这是必须一起修的降级缺陷。

## Goals / Non-Goals

**Goals:**

- 在不改变四象限语义、不引入评分的前提下，把方向作为独立描述层加到个股、行业与交集上。
- 把「绝对方向」与「相对市场方向」的取数与计算分离为纯函数，可在无网络下用 fixture 验证。
- 方向层任一数据源失败时保留其余证据并诚实降级，不产出「看着完整」的方向结论。
- 保持 JSON 向后兼容：只新增字段，`quadrant`、`rankKey`、`handoff.candidateThscodes` 的语义与顺序不变。

**Non-Goals:**

- 不计算行业评分、相对强度分位、成交额增量或持续性（属 `a-stock-qts04-sector-direction`）。
- 不做涨停/跌停归因、题材层或个股推荐（涨停池归 `a-stock-qts04-theme-layer`）。
- 不新增历史回溯：方向只描述本次调用时点的截面。
- 不把方向用于筛选或排序，不新增方向数量限制。

## Decisions

### D1 方向作为独立纯函数模块 `direction.py`，四象限代码零改动

`quadrant.py` 的 `classify` / `rank_key` 保持原样，方向判定、宽度聚合、相对基准与复合标签全部放进新的 `direction.py`（无 I/O、无时钟）。编排层在 `industry_map.aggregate` 之后补方向字段，`tag` 由 `quadrant + direction` 拼装。

替代方案：把方向塞进 `quadrant.QuadrantInput` 并扩成 8 象限。被否决——会破坏规格中「四象限分类只依赖横截面计数」的既有要求，也会让下游读取 `quadrant` 的地方改变含义。

### D2 绝对方向与相对方向双输出，相对基准用全市场等权中位

- 绝对：个股 `changePct`（vs 昨收）；板块指数 `price_change_ratio_pct`。
- 相对：`changePct − market.medianChangePct`（个股）；`memberMedianChangePct − market.medianChangePct`（行业），单位百分点。
- 市场基准固定为全市场逐股涨跌幅中位数，输出 `direction.market` 让相对值可复算。

实测依据：2026-11-20 全市场中位 -5.08%，上证指数 -1.23%。若用指数做基准，86/90 个一级行业被判为「跑输」；若只做绝对方向，88/90 个行业是「下跌」；用等权中位则得到 53 强 / 37 弱的可用区分度。

替代方案：用 `000001.SH` 或某个全 A 加权指数当基准。被否决——指数是市值加权，与个股涨跌幅不是同一口径，当天偏差达 3.85pp，且指数目录中没有等权全 A 指数可直接替代。

### D3 行业方向给三类证据，主表只展示三项

- `boardChangePct`：板块指数涨跌（权威口径，与同花顺板块列表一致）。
- `hitUpCount` / `hitDownCount`：上榜股方向（免费，已有数据，回答「上榜的钱在买涨还是买跌」）。
- `memberUpCount` / `memberDownCount` / `memberFlatCount` / `memberMedianChangePct` / `memberCoverage`：全成分股宽度（等权，回答「行业内部是扩散还是少数权重拖着」）。

三者独立输出、不做加权合成，因为合成就等于评分。实测三者多数同向（半导体 -6.85 / -7.18 / 7 涨 182 跌；银行 +0.22 / +0.19 / 23 涨 19 跌），分歧最大的是元件（指数 -0.82 vs 成分中位 -2.40），说明只看一类证据会漏掉「权重股护盘、多数成分下跌」的情形。

Markdown 主表只加「板块涨跌 / 上榜涨跌 / 相对」三列，宽度明细留在 JSON：现有表已有 7 列，全量展开会变成 12 列不可读。

### D4 取数：板块指数一次调用，全市场快照六页并发，新浪全量快照做兜底

- `index snapshot`：一次传全部一级（90）或二级（230）板块代码，实测均返回完整且无空值。
- `market snapshot`：`limit=1000` 分 6 页并发，约 0.4–0.7 秒，覆盖 5584 只（含北交所）。
- 兜底：`market snapshot` 失败时复用已实现的 `sina_client.fetch_full_snapshot()`（2.7 秒，同一时点、同一涨跌幅口径），结果标 `source: "sina-full-snapshot"` 并降级；两条路径都失败时相对字段为 `null`。

替代方案：只用板块指数，不做全市场快照。被否决——无法计算相对基准与宽度，且无法给出「上涨/下跌家数」这个用户直接要的答案；成本只有 0.4–0.7 秒，不值得省。

替代方案：直接复用新浪全量快照作为主路径。被否决——2.7 秒且字段口径（`changepercent`）与 fuyao 的 `price_change_ratio_pct` 需要额外一致性校验；作为兜底更合适。

### D5 停牌与平盘口径

- 停牌/无昨收：`volume == 0` 或涨跌幅为 `null`（全市场快照实测 12 只），剔除出分母，单列 `suspended` 计数。
- 平盘：`|涨跌幅| ≤ 0.005`，与两位小数展示一致；MUST NOT 把停牌算作平盘。
- 覆盖率：`有效成员 / 成分股总数`，低于 70% 记 `insufficient` 且数值为 `null`（沿用 QTS-04-01-04 的覆盖率门槛，保持两个 Skill 口径一致）。

### D6 新股过滤整体缺失时 fail-open

`list_date` 单只缺失仍按原逻辑排除并计入 `excluded.missingListDate`；但当接口返回非空列表且全部 `list_date` 为 `null` 时，判定为「过滤能力不可用」，跳过过滤、继续产出双榜与行业段，记 `degraded` 并告警。

替代方案：继续把全部股票当缺失排除。被否决——2026-11-20 实测直接导致退出码 2，Skill 不可用。替代方案：静默放行不告警。被否决——会让次新股污染榜单却无迹可寻。

### D7 版本与渲染

- `schemaVersion` 1.0 → 1.1（纯新增字段，`quadrant` 与 `handoff` 结构不变）。
- `ruleVersion` → `active-industry-scan-v2`（新增方向阈值：平盘 epsilon、覆盖率门槛）。
- `reportId` 仍只由运行时刻与 nonce 生成，不把方向配置纳入哈希（与 QTS-04 不同，此处记录为已知限制，不为此改动编号规则）。
- Markdown 新增「方向分组」段：活跃上涨与活跃下跌两组，组内按相对超额降序；主表排序不变。

## Risks / Trade-offs

- [方向阈值全部 `needs-backtest`] → 平盘 epsilon、70% 覆盖率、方向分组条数都在文档标 `needs-backtest`，不声称已验证。
- [早期快照方向易翻转] → 沿用现有 `earlySnapshot` 与 `elapsedBars` 提示，方向字段随快照一起标注不稳定。
- [相对基准是中位，与板块指数加权口径不同] → 行业同时输出 `boardChangePct`（加权）与 `memberMedianChangePct`（等权），并在 `relativeBasis` 写明用哪个。
- [list_date fail-open 可能让次新股进榜] → 降级告警必须出现在 JSON 与 Markdown，且 `quality.status=degraded`。
- [新增一次全市场快照，盘中运行变慢 0.4–0.7 秒] → 与新浪全量快照兜底路径互斥，只在主路径失败时才走 2.7 秒路径。
- [板块指数可能比个股成交晚一个刷新周期] → 输出 `dataCutoff` 与快照 `timestamp`，不把不同时点拼成一个结论。

## Migration Plan

1. 先落 `direction.py` 纯函数与离线测试，再接取数，最后改渲染；任一阶段失败可只回退该阶段。
2. 字段纯新增，下游 `a-stock-qts04-sector-direction` 只读 `handoff.candidateThscodes`，无需同步改动。
3. 回滚：把 `contract.py` 的版本常量与编排层方向块一起回退即可恢复 v1 输出；缓存格式（行业成分股按日 JSON）不变，无需清理。
4. 盘后验证：用当日收盘数据跑一次真实端到端，核对半导体/银行/交集的方向分组与手算值一致。

## Open Questions

- 方向分组每组默认条数（5 条或沿用 `--top-sectors`）可在实现时用常量决定，不影响规格与任务拆分。
- `--level both` 时两级同时输出的篇幅需要真实数据实测后再决定是否截断，不阻塞本次实现。
