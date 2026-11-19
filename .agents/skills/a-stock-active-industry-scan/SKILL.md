---
name: a-stock-active-industry-scan
description: 盘中随时扫描 A 股双榜（成交额榜与换手率榜），按同花顺行业聚合出最活跃的行业、每个行业有多少只股票、双榜交集股票与四象限归属，并把候选行业代码清单移交下游 Skill 打分。用于用户要求“最活跃的行业”“哪些行业资金在进”“多个行业”“每个行业有多少只股票”“双榜交集”“换手率榜”“成交额榜”“盘中扫描”“扫描一下行业”时；不用于行业评分、个股推荐、题材归因或买卖信号。
---

# A 股盘中活跃行业扫描

## 这个 Skill 做什么

用两个榜单交叉回答「资金正在进入哪些行业」，并且只做**发现层**，不做评分：

```
成交额榜  ->  资金容量与注意力去哪了
换手率榜  ->  筹码交换强度，谁在剧烈分歧
两者交集  ->  同时具备规模与交换的标的
```

输出四段：双榜明细、行业命中数（一级与二级）、四象限归属、双榜交集股票。候选行业以代码清单移交 `a-stock-qts04-sector-direction` 按 `QTS-04-01-01` 至 `-05` 正式打分。

## 什么时候用

| 用 | 不用 |
|---|---|
| 盘中任意时点问「现在哪些行业最活跃」 | 要行业评分或板块定向 → `a-stock-qts04-sector-direction` |
| 想知道每个行业有多少只股票上榜 | 要题材真伪或涨停归因 → `a-stock-qts04-theme-layer` |
| 想知道哪些股票同时在成交额榜和换手率榜 | 要个股买卖建议 → 本 Skill 不提供 |
| 想按行业筛出候选池，再自己看个股 | 要历史某一天的回放 → 本 Skill 只反映当前时点 |

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
| `--fixture PATH` | 无 | 离线 fixture 模式，不发起任何网络请求 |
| `--no-bars` / `--no-history` | 关闭 | 跳过分时 / 历史日线，用于快速运行 |

## 输出结构

```json
{
  "schemaVersion": "1.0",
  "ruleVersion": "active-industry-scan-v1",
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
  "rankings": {
    "byAmount": [ { "rank": 1, "code": "300308.SZ", "name": "...", "amountYi": 166.08,
                    "turnoverPct": 3.7529, "floatMvYi": 4532.98, "changePct": 3.05 } ],
    "byTurnover": [ { "rank": 1, "code": "002685.SZ", "name": "...", "amountYi": 30.95,
                      "turnoverPct": 51.3336, "floatMvYi": 48.21, "changePct": 9.98 } ]
  },
  "industries": [
    { "code": "881121.TI", "name": "半导体", "level": 1,
      "amountTopCount": 19, "turnoverTopCount": 3,
      "memberCount": 190, "hitRateAmount": 0.1, "hitRateTurnover": 0.0158,
      "quadrant": "真实活跃" }
  ],
  "intersection": [
    { "code": "600410.SH", "name": "...", "amountRank": 16, "turnoverRank": 10,
      "industries": ["IT服务"] }
  ],
  "percentile": {
    "status": "deferred",
    "reason": "当日累计量与历史全天分布不可比",
    "availableAfter": "15:10"
  },
  "handoff": {
    "target": "a-stock-qts04-sector-direction",
    "candidateThscodes": ["881121.TI"],
    "note": "本 Skill 只做发现层，不评分；候选行业需由下游按 QTS-04-01-01 至 -05 打分"
  },
  "quality": { "status": "ok", "degradations": [], "warnings": [] },
  "disclaimer": "四象限描述资金分布，不是买卖信号；全部规则状态 needs-backtest。",
  "excluded": {
    "byTurnover": [ { "code": "920309.BJ", "name": "...", "listDate": "2026-11-17",
                      "listingDays": 2, "rankIfUnfiltered": 3 } ],
    "byAmount": [],
    "missingListDate": []
  },
  "industryMembershipDate": "2026-11-19"
}
```

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

```

## 四象限

用双榜命中数判定，**不使用 lift**（小行业分母小会把 lift 抬高）：

|  | 换手榜命中多 | 换手榜命中少 |
|---|---|---|
| **成交额榜命中多** | 真实活跃 | 权重拉升 |
| **成交额榜命中少** | 小盘情绪 | 冷门 |

命中率只作参考输出，不参与象限判定，也不作为唯一排序键。

## 两条必须知道的口径限制

**盘中不给历史分位。** 当日累计成交量与历史全天成交量不可比：个股 10:30 累计量占全天比例在 37.9%–63.7% 之间，相差 1.7 倍。用历史占比外推全天量的误差中位 30.0%、最大 82.5%。因此分位字段在盘中返回不可用，收盘结算后（默认 15:10）才补算。**任何时候都不按固定比例缩放估算分位。**

**早盘交集可能大于收盘。** 2026-11-19 实测 10:30 有 9 只交集、收盘 5 只，收盘的 5 只全部包含在 10:30 的 9 只内。这是单日样本，不是规律；早盘交集可能包含最终会退出的标的。

## 时点状态

| 时段 | `sessionState` | 分位 |
|---|---|---|
| 09:30 前 | `preopen` | 不可用 |
| 09:30–11:30 | `intraday` | 不可用 |
| 11:30–13:00 | `lunch` | 不可用 |
| 13:00–15:00 | `intraday` | 不可用 |
| 15:00–15:10 | `settling` | 不可用 |
| 15:10 后 | `closed` | 可用 |

`elapsedBars ≤ 3` 时输出带早期快照提示：首根 bar 含集合竞价，占全天成交量中位 15.9%、最高 47.3%，此时榜单波动剧烈。

## 边界

- **不评分**：不计算相对强度、成交额增量、持续性，也不给方向数量。
- **不推荐**：全部规则状态 `needs-backtest`，四象限是资金分布描述，不是买卖信号。
- **不查历史**：新浪排序接口与 fuyao 成分股都只有当前快照，无 `--as-of`。
- **不写数据库**：只落 `.cache/active-industry-scan/`，可随时删除重建。

## 参考

- `references/data-contract.md`：双榜口径、降级顺序、缓存策略、时点状态机。
- `references/metric-definitions.md`：换手率口径、分位等价性、四象限阈值。