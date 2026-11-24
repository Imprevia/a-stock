---
name: a-stock-active-industry-scan
description: 盘中随时扫描 A 股双榜（成交额榜与换手率榜），按同花顺行业聚合出最活跃的行业、每个行业有多少只股票、双榜交集股票与四象限归属，并区分上涨与下跌的行业和股票，把候选行业代码清单移交下游 Skill 打分。用于用户要求“最活跃的行业”“哪些行业资金在进”“哪些行业在涨”“哪些行业在跌”“多个行业”“每个行业有多少只股票”“双榜交集”“换手率榜”“成交额榜”“盘中扫描”“扫描一下行业”时；不用于行业评分、个股推荐、题材归因或买卖信号。
---

# A 股盘中活跃行业扫描

## 这个 Skill 做什么

用两个榜单交叉回答「资金正在进入哪些行业」，再用方向层回答「这些行业在涨还是在跌」，只做**发现层**，不做评分：

```
成交额榜  ->  资金容量与注意力去哪了
换手率榜  ->  筹码交换强度，谁在剧烈分歧
两者交集  ->  同时具备规模与交换的标的
方向层    ->  活跃的钱在买涨还是卖跌
```

**高成交额或高换手本身不含方向。** 2026-11-20 收盘实测：成交额榜 Top50 有 34 只下跌、换手率榜 Top50 有 30 只下跌；半导体板块 -6.85%（上榜 15 只中 13 跌）与银行板块 +0.22%（上榜 4 只全涨）在活跃度上都属「真实活跃」。没有方向层时，放量杀跌会被读成资金进场。

输出五段：行业活跃度与方向、方向分组、双榜交集、双榜明细、数据质量。候选行业以代码清单移交 `a-stock-qts04-sector-direction` 按 `QTS-04-01-01` 至 `-05` 正式打分。

## 什么时候用

| 用 | 不用 |
|---|---|
| 盘中任意时点问「现在哪些行业最活跃」 | 要行业评分或板块定向 → `a-stock-qts04-sector-direction` |
| 想知道活跃行业里哪些在涨、哪些在跌 | 要题材真伪或涨停归因 → `a-stock-qts04-theme-layer` |
| 想知道每个行业有多少只股票上榜 | 要个股买卖建议 → 本 Skill 不提供 |
| 想知道哪些股票同时在成交额榜和换手率榜 | 要历史某一天的回放 → 本 Skill 只反映当前时点 |
| 想按行业筛出候选池，再自己看个股 | — |

## 怎么用

```bash
# 盘中默认运行（一级行业、双榜各 400 只候选池、过滤上市不足 250 日）
python3 scripts/scan_pipeline.py --output /tmp/scan.json

# 连带二级行业
python3 scripts/scan_pipeline.py --level both --output /tmp/scan.json

# 离线 fixture 模式（无网络）
python3 scripts/scan_pipeline.py --fixture tests/fixtures/active_industry_scan/scan.json --output /tmp/scan.json
```

常用参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--top N` | 50 | 每榜输出条数 |
| `--candidate-pool N` | 400 | 每榜候选池大小，必须大于 `--top` |
| `--min-listing-days N` | 250 | 上市不足 N 个自然日的新股剔除 |
| `--level 1\|2\|both` | 1 | 行业层级 |
| `--top-sectors N` | 10 | 行业段输出条数 |
| `--output PATH` | stdout | JSON 结果写入路径 |
| `--markdown PATH` | 不生成 | 由 JSON 纯渲染的 Markdown 报告 |
| `--answer PATH` | 不生成 | 由 JSON 纯渲染的**会话回复**，回复须逐字复制该文件 |
| `--history-dir PATH` | 实时运行写 Skill 缓存 | 扫描轨迹记录目录；fixture 模式默认不写 |
| `--no-history-store` | 关闭 | 本次不读写扫描轨迹 |
| `--import-history PATH...` | 无 | 把既有 JSON 结果补录进轨迹（按 `reportId` 去重，不重算） |
| `--fixture PATH` | 无 | 离线 fixture 模式，不发起任何网络请求 |
| `--no-bars` / `--no-history` | 关闭 | 跳过分时 / 历史日线，用于快速运行 |

## 回复格式（硬要求）

**每一次回答必须等于 `--answer` 文件的输出，逐字复制，不得重新排版。**

```bash
python3 scripts/scan_pipeline.py --output /tmp/scan.json --markdown /tmp/scan.md --answer /tmp/answer.md
cat /tmp/answer.md        # ← 把这个文件的内容原样作为回复
```

固定不变的部分：

| 位置 | 固定内容 |
|---|---|
| 标题 | `# 最活跃的行业`（不写日期、不加前缀） |
| 结论块 | 恰好 5 行 bullet：时点 / 全市场 / 最活跃行业 Top3 / 方向分组计数 / 双榜交集 |
| 正文 | 六段：`## 一、行业活跃度与方向`、`## 二、方向分组`、`## 三、双榜交集`、`## 四、扫描变化轨迹`、`## 五、双榜明细`、`## 六、数据质量`（有剔除时插入 `## 六、被剔除的股票`，数据质量顺延为 `## 七`） |
| 表格列 | 与渲染器完全一致，不得增删列、改列名或调整列序 |
| 涨跌数字 | 带符号：`+1.23%` / `-1.23%`；换手率等比率不带符号；缺失为 `—` |

允许的唯一自由空间：在文末追加 `## 备注`，最多 5 行，用来说明你的判断。**不得**新增其他章节、不得自己拼对比表、不得把固定段落合并或改写。

### 变化轨迹是固定段，不是可选段

`## 四、扫描变化轨迹` 由本地历史记录渲染，**每次都出现**：

- 当日首次记录 → 打印「本次为当日首次记录：暂无对比基线」，不留空段。
- 有历史 → 表格每行一次扫描（时刻到秒、bar、全市场中位、涨跌、Top3 命中、首位行业板块、换手榜涨跌、交集、候选），其后两组关键变化：「相对上一次扫描」与「相对当日首次」。
- 关键变化只在超过阈值时列出：中位 ±0.50pp、上涨家数 ±5%、行业成交额榜命中 ±2、换手榜下跌家数 ±2、交集增删、候选增删；都不触发时明确写「未触发任何阈值」。
- 轨迹来自 `.cache/active-industry-scan/history/{date}.jsonl` 当日记录（最多 12 次），**不是历史行情回放**；首次使用该 Skill 的会话会因此少一段历史，这是正确行为。
- 想补录本次之前已经跑过的结果，用 `--import-history /path/a.json /path/b.json`，补录只写投影、不重算指标。

为什么是硬要求：盘中数据每次运行都会变，这不是问题；但标题、列序、符号写法每会话不同，会让同一 Skill 看起来像两个工具。格式由渲染器决定，会话只负责复制。


## 输出结构

```json
{
  "schemaVersion": "1.1",
  "ruleVersion": "active-industry-scan-v2",
  "reportId": "ais-20261119T103000-517d6a51",
  "generatedAt": "2026-11-19T10:30:12+08:00",
  "asOf": "2026-11-19T10:30:12+08:00",
  "sessionState": "intraday",
  "elapsedBars": 12,
  "dataCutoff": "2026-11-19T10:30:00+08:00",
  "earlySnapshot": false,
  "settled": false,
  "turnoverBasis": "float-share",
  "filter": { "minListingDays": 250, "candidatePool": 400, "top": 50 },
  "direction": {
    "basis": "changePct-vs-prev-close",
    "relativeBasis": "equal-weight-vs-market-median",
    "flatEpsilon": 0.005,
    "minBreadthCoverage": 0.7,
    "basisNote": "已收盘：方向为当日收盘涨跌幅",
    "market": { "status": "ok", "source": "fuyao-market-snapshot",
                "universe": 5584, "validCount": 5572, "suspendedCount": 12,
                "upCount": 313, "downCount": 5236, "flatCount": 23,
                "medianChangePct": -5.08, "coverage": 0.9978 }
  },
  "directionSummary": {
    "byAmount": { "up": 16, "down": 34, "flat": 0, "suspended": 0,
                  "total": 50, "upAmountShare": 0.2836 },
    "byTurnover": { "up": 20, "down": 30, "flat": 0, "suspended": 0,
                    "total": 50, "upAmountShare": 0.3712 }
  },
  "rankings": {
    "byAmount": [ { "rank": 1, "code": "300308.SZ", "name": "...", "amountYi": 166.08,
                    "turnoverPct": 3.7529, "floatMvYi": 4532.98, "changePct": 3.05,
                    "direction": "up", "relativeToMarketPct": 8.13 } ],
    "byTurnover": [ { "rank": 1, "code": "002685.SZ", "name": "...", "amountYi": 30.95,
                      "turnoverPct": 51.3336, "floatMvYi": 48.21, "changePct": 9.98,
                      "direction": "up", "relativeToMarketPct": 15.06 } ]
  },
  "industries": [
    { "code": "881121.TI", "name": "半导体", "level": 1,
      "amountTopCount": 19, "turnoverTopCount": 3,
      "memberCount": 190, "hitRateAmount": 0.1, "hitRateTurnover": 0.0158,
      "quadrant": "真实活跃",
      "direction": "down", "directionBasis": "member-median",
      "tag": "真实活跃·下跌", "boardChangePct": -6.8475, "boardDirection": "down",
      "hitUpCount": 2, "hitDownCount": 13, "hitFlatCount": 0,
      "hitSuspendedCount": 0, "hitUnknownCount": 0, "hitCount": 15,
      "memberUpCount": 7, "memberDownCount": 182, "memberFlatCount": 1,
      "memberSuspendedCount": 0, "memberUnknownCount": 0,
      "memberMedianChangePct": -6.21, "memberCoverage": 1.0,
      "memberBreadthStatus": "ok",
      "relativeToMarketPct": -1.13, "boardRelativeToMarketPct": -1.77 }
  ],
  "intersection": [
    { "code": "600410.SH", "name": "...", "amountRank": 16, "turnoverRank": 10,
      "industries": ["IT服务"], "changePct": 3.71,
      "direction": "up", "relativeToMarketPct": 8.79 }
  ],
  "percentile": {
    "status": "deferred",
    "reason": "当日累计量与历史全天分布不可比",
    "availableAfter": "15:10"
  },
  "handoff": {
    "target": "a-stock-qts04-sector-direction",
    "candidateThscodes": ["881121.TI"],
    "candidates": [ { "thscode": "881121.TI", "name": "半导体",
                      "tag": "真实活跃·下跌", "direction": "down" } ],
    "note": "本 Skill 只做发现层，不评分；候选行业需由下游按 QTS-04-01-01 至 -05 打分。方向仅作标注，不参与候选筛选。"
  },
  "quality": { "status": "ok", "degradations": [], "warnings": [] },
  "disclaimer": "四象限描述资金分布、方向描述涨跌，两者都不是买卖信号；全部规则状态 needs-backtest。",
  "excluded": {
    "byTurnover": [ { "code": "920309.BJ", "name": "...", "listDate": "2026-11-17",
                      "listingDays": 2, "rankIfUnfiltered": 3 } ],
    "byAmount": [],
    "missingListDate": []
  },
  "industryMembershipDate": "2026-11-19"
}
```

### 方向字段怎么读

| 字段 | 含义 |
|---|---|
| `direction.basis` | 绝对方向基准：`changePct` 相对**前一收盘价** |
| `direction.relativeBasis` | 相对方向基准：等权成员中位涨跌幅 − 全市场中位涨跌幅 |
| `direction.market` | 全市场基准本身（`medianChangePct` 即相对计算的减数），可复核 |
| `direction.basisNote` | 说明这批方向描述的是哪个时点（开盘前是**前一交易日**） |
| `industries[].direction` | 行业方向：优先等权成员中位，缺失时退板块指数，再退上榜多数 |
| `industries[].directionBasis` | 实际生效的证据：`member-median` / `board-index` / `hit-majority` / `unavailable` |
| `industries[].tag` | 四象限 × 方向复合标签，如 `真实活跃·下跌` |
| `industries[].boardChangePct` | 板块指数涨跌幅（市值加权），与等权宽度可能背离 |
| `industries[].hitUpCount` / `hitDownCount` | 上榜个股的涨跌家数 |
| `industries[].memberUpCount` / `memberDownCount` | 全部成分股的涨跌家数 |
| `industries[].relativeToMarketPct` | 等权中位相对全市场中位的超额；宽度不足时为 `null` |
| `rankings[].direction` / `relativeToMarketPct` | 个股方向与相对超额 |
| `directionSummary` | 逐榜涨跌家数与上涨股成交额占比；`upAmountShare` 与涨跌家数独立 |

**方向是标注层，不改变任何既有排序与筛选。** `candidateThscodes` 仍只由双榜命中数决定；下跌行业照样进候选清单，只是带着 `direction: "down"` 交给下游。

### 方向的三类证据为什么不合并成一个数

同一时点三种口径会给出不同答案，混成一个标签就不可解释了。2026-11-20 实测：

- **元件**：板块指数 -0.82%，成分股等权中位 -2.40%。指数被权重股托住，多数个股在跌。
- **上证 -1.23% 作基准时**：仅有 4 个行业强于大盘、86 个弱于大盘；改用全市场**等权中位 -5.08%** 后是 53 强 / 37 弱。指数基准会把「小盘普跌但指数抗跌」的日子读成全市场皆弱。

因此本 Skill 同时输出指数（加权）与宽度（等权）两套证据，相对方向固定用等权中位，避免与基准口径错配。

`percentile` 在 `closed` 后变为：

```json
{
  "status": "computed",
  "byCode": {
    "002685.SZ": { "status": "ok", "windowBars": 243,
                   "baselineVolumeShares": 33783285.45,
                   "amplification": 15.3103, "percentile": 1.0 }
  }
}
```

`baselineVolumeShares` 是 20 日均**成交量（股）**，不是换手率百分比：历史序列只有成交量，分位与放大倍数不受单位影响，但字段名不假装它是百分比。`windowBars < 60` 的个股该块为 `insufficient` 且数值为 `null`。

## 四象限

用双榜命中数判定，**不使用 lift**（小行业分母小会把 lift 抬高）：

|  | 换手榜命中多 | 换手榜命中少 |
|---|---|---|
| **成交额榜命中多** | 真实活跃 | 权重拉升 |
| **成交额榜命中少** | 小盘情绪 | 冷门 |

命中率只作参考输出，不参与象限判定，也不作为唯一排序键。

**四象限与方向相互独立。** 象限判定只用命中数（成交额≥2 且换手≥2 为「真实活跃」），完全不看涨跌；方向来自等权成员中位、板块指数与上榜涨跌。两者交叉出 8 种组合，其中以下几组最容易误读：

| 组合 | 含义 |
|---|---|
| 真实活跃·上涨 | 规模与交换俱在，且价格向上 |
| 真实活跃·下跌 | 规模与交换俱在，价格向下——放量派发或恐慌换手 |
| 权重拉升·上涨 | 只有成交额命中且上涨，需分辨是权重股独走还是行业普涨 |
| 小盘情绪·下跌 | 只有换手率命中且下跌，多为小盘股高位换手 |

## 三条必须知道的口径限制

**盘中不给历史分位。** 当日累计成交量与历史全天成交量不可比：个股 10:30 累计量占全天比例在 37.9%–63.7% 之间，相差 1.7 倍。用历史占比外推全天量的误差中位 30.0%、最大 82.5%。因此分位字段在盘中返回不可用，收盘结算后（默认 15:10）才补算。**任何时候都不按固定比例缩放估算分位。**

**早盘交集可能大于收盘。** 2026-11-19 实测 10:30 有 9 只交集、收盘 5 只，收盘的 5 只全部包含在 10:30 的 9 只内。这是单日样本，不是规律；早盘交集可能包含最终会退出的标的。

**开盘前的方向不是当日方向。** `preopen` 时当日尚无成交，`changePct` 只能是前一交易日收盘相对前一日的变化。此时 `direction.basisNote` 会明确标注「前一交易日」，不要把它当作当日的涨跌结论。

## 方向层的降级行为

方向数据失败不会让整份报告失败，也不会把缺失值填成 0：

| 失败点 | 影响 | 质量状态 |
|---|---|---|
| 板块指数快照失败 | `boardChangePct` / `boardDirection` 为 `null`，行业方向改由成员中位决定；上榜与宽度证据仍在 | `degraded` |
| 全市场快照失败 | 自动改用新浪全量快照兜底（同一时点的个股涨跌，约 2.7s），相对方向照常可用 | `degraded` |
| 两者同时失败 | 相对方向与宽度为 `null`，绝对方向仍由个股 `changePct` 给出；双榜与交集完整 | `degraded` 或 `insufficient` |

宽度覆盖率低于 70% 时，`memberMedianChangePct` 与 `relativeToMarketPct` 一律为 `null`（`memberBreadthStatus: "insufficient"`），此时 `directionBasis` 会指向仍在生效的证据，而不是给一个不可靠的中位数。

**停牌与「无数据」分开计。** `suspended` 表示该股当日无成交（`volume` 为 0 或无涨跌幅），`unknown` 表示本次根本没有拿到这只股票的行情。两者都不计入涨跌家数，也不计入平盘。

## 时点状态

| 时段 | `sessionState` | 分位 | 方向 |
|---|---|---|---|
| 09:30 前 | `preopen` | 不可用 | 反映前一交易日 |
| 09:30–11:30 | `intraday` | 不可用 | 当前时点 |
| 11:30–13:00 | `lunch` | 不可用 | 上午收盘时点 |
| 13:00–15:00 | `intraday` | 不可用 | 当前时点 |
| 15:00–15:10 | `settling` | 不可用 | 当日收盘 |
| 15:10 后 | `closed` | 可用 | 当日收盘 |

`elapsedBars ≤ 3` 时输出带早期快照提示：首根 bar 含集合竞价，占全天成交量中位 15.9%、最高 47.3%，此时榜单波动剧烈。

## 边界

- **不评分**：不计算相对强度评分、成交额增量、持续性，也不给方向打分。方向只做标注与分组。
- **不因方向筛选**：`candidateThscodes` 只由双榜命中数决定；不上调上涨行业权重，也不剔除下跌行业。
- **不分时段的涨跌归因**：方向只说涨跌，不解释为什么涨跌；题材真伪走 `a-stock-qts04-theme-layer`。
- **不推荐**：全部规则状态 `needs-backtest`，四象限与方向都是描述层，不是买卖信号。
- **不查历史**：新浪排序接口与 fuyao 成分股都只有当前快照，无 `--as-of`。
- **不写数据库**：只落 `.cache/active-industry-scan/`，可随时删除重建。

## 参考

- `references/data-contract.md`：双榜口径、方向取数、降级顺序、缓存策略、时点状态机。
- `references/metric-definitions.md`：换手率口径、分位等价性、四象限阈值、方向与宽度定义。