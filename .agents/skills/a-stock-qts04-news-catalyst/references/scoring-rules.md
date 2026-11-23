# STEP 2.5 打分规则

本文件是 `QTS-04-09` 的可执行口径。实现位于 `scripts/news.py`，词表位于 `references/lexicon.v1.json`。

## 一、词表 schema

```json
{
  "version": "1.0",
  "rules": [
    {
      "id": "neg.med.reduce",
      "ruleId": "QTS-04-09-02",
      "class": "event",
      "eventType": "股东减持",
      "polarity": "negative",
      "severity": "medium",
      "weight": 0.8,
      "patterns": ["减持", "减持计划"],
      "negation": "drop",
      "uncertaintySensitive": true
    }
  ]
}
```

| 字段 | 约束 |
|---|---|
| `id` | 全局唯一；按 `id` 排序后计算哈希 |
| `ruleId` | 必须是 `QTS-04-09-01` ~ `QTS-04-09-05` |
| `class` | `event` / `topic` / `context` |
| `eventType` | 展示名；同一规则的所有命中合并统计 |
| `polarity` | `positive` / `negative` / `ambiguous`（`topic`/`context` 用 `neutral`） |
| `severity` | `hard` / `medium` / `weak` |
| `weight` | 基础权重；`hard=1.0`，`medium=0.7—0.8`，`weak=0.4—0.5`，语境 `0` |
| `patterns` | 非空；中文按子串匹配，英文按大小写不敏感精确匹配 |
| `negation` | `drop`（默认）/ `downgrade` / `flip` |
| `uncertaintySensitive` | `false` 时不受“拟/预计”降级（硬风险通常为 `false`） |

哈希只覆盖规范化后的 `version` 与按 `id` 排序的规则字段；JSON 缩进、键顺序、额外说明字段不影响哈希。

## 二、三类关键词

| 类别 | 例子 | 是否计分 | 用途 |
|---|---|---|---|
| `event` | 业绩预亏、股东减持、退市风险 | 是 | 判定方向与风险 |
| `topic` | 存储芯片、商业航天、人形机器人 | 否 | 解释证据属于哪条题材线 |
| `context` | 板块回调、大盘下跌、美联储、获利回吐 | 否 | 解释“板块普跌”，不得算个股利空 |

同一关键词同时命中多个规则时，按 `id` 排序取第一个；正文匹配时同一位置优先更长模式，重叠区间只保留一个。

## 三、匹配与作用域

- 关键词：与词表 `patterns` 精确匹配（先 `strip`，英文不区分大小写）。
- 正文：子串匹配；正文截断 4000 字；每个模式最多取 3 次命中。
- 关键词与正文冲突：正文明确否定同一规则时，关键词命中也置为 `active=false`（例如关键词“减持”、正文“终止减持”）。
- 关键词与正文一致但正文带不确定措辞时，关键词命中继承降级后的 `severity` 与 `certainty`。

### 否定

| 项 | 口径 |
|---|---|
| 触发词 | 不存在、未实施、并未、没有、终止、取消、未能、不及预期、低于预期、不、未、无、否认、并非 |
| 回看窗口 | 命中位置左侧 8 个字符 |
| 失效条件 | 窗口内出现 `。` `；` `;` `！` `!` 任一字符 |
| 动作 | `drop` 取消；`downgrade` 降一级并标 `speculative`；`flip` 反转极性 |
| v1 | 事件规则默认 `drop`；不做“利空变利好”的自动翻转 |

例子：

| 文本 | 结果 |
|---|---|
| 终止减持计划 | 不产生负向事件 |
| 未实施减持 | 不产生负向事件 |
| 不存在退市风险 | 不产生硬否决 |
| 不存在退市风险。公司股东减持 | 第二句的减持照常计分（不跨句否定） |

### 不确定

| 项 | 口径 |
|---|---|
| 触发词 | 拟、计划、预计、有望、或将、传闻、媒体报道、据悉、可能存在 |
| 回看窗口 | 命中位置左侧 8 个字符；跨分句失效 |
| 动作 | `severity` 降一级（最低 `weak`），`certainty=speculative` |
| 例外 | `uncertaintySensitive=false` 的硬风险不降级 |

例子：`股东拟减持` → 股东减持从 `medium` 降为 `weak`，个股风险为 `watch`，不是 `block`。

## 四、单条证据得分

```
contribution = baseWeight × sourceFactor × recencyDecay × certaintyFactor
```

| 因子 | 取值 |
|---|---|
| `sourceFactor` | 关键词命中 `1.0`；正文命中 `0.8` |
| `recencyDecay` | `0.5 ** (daysAgo / 3)`，按交易日；日历缺失时退化为自然日 |
| `certaintyFactor` | `partial=1.0`；`speculative=0.6`；`unknown=0.3` |

时效示例：

| 距目标日 | 权重 |
|---|---|
| 0 个交易日 | 1.00 |
| 3 个交易日 | 0.50 |
| 6 个交易日 | 0.25 |

算例：目标日前 1 个交易日的关键词“业绩预增”

```
0.8 × 1.0 × 0.5 ** (1/3) × 1.0 ≈ 0.635
```

## 五、单元极性

1. 单元证据 = 成员集合内所有证据（含 0 事件的语境证据）。
2. `positiveScore` / `negativeScore` = 正向/负向事件 `contribution` 之和；`ambiguous` 不计。
3. 闸门：`evidenceCount ≥ 2` 且 `coveredMembers ≥ 2`，否则 `unknown`。
4. 占比：
   - `positiveShare = positiveScore / (positiveScore + negativeScore)`
   - `negativeShare = negativeScore / (positiveScore + negativeScore)`
5. 标签：

| 条件 | 标签 |
|---|---|
| 双方占比都 ≥ 0.30 | `mixed` |
| `positiveShare - negativeShare ≥ +0.25` | `positive` |
| `positiveShare - negativeShare ≤ −0.25` | `negative` |
| 其余且总分 > 0 | `neutral` |
| 没有证据 | `unknown` |

6. 置信度：

| 条件 | 置信度 |
|---|---|
| 证据 ≥ 3、覆盖 ≥ 2、主导占比 ≥ 0.70、无反向 hard/medium | `high` |
| 证据 ≥ 2 | `medium` |
| 其余 | `low` |
| 未过闸门 | `insufficient` |

## 六、个股风险

优先级从高到低，命中即停：

| 条件 | 风险 |
|---|---|
| 存在 `active` 的 `hard` 负向 | `block` |
| 存在 `active` 的 `medium` 负向 | `downgrade` |
| 存在 `active` 的 `weak` 负向 | `watch` |
| 有证据、无负向 | `none` |
| 无证据 | `uncovered` |

- 正向事件不能抵消硬否决：`block` 只看负向最高级别。
- `ambiguous` 不计入风险，只在证据里保留。
- `block` 是提示，不是自动排除；需回测校准后才能进入筛选否决。

个股极性使用同一套正负分与标签，但不套“2 条证据、2 只成员”闸门；1 条证据即可给出标签，置信度通常为 `low`。

## 七、算例

### 例 1：终止减持

```text
关键词：减持
正文：公司终止减持计划，未实施减持
```

正文对同一规则的两处命中均被否定 → 关键词命中也置 `active=false`。若这是唯一证据：单元 `neutral`（有证据、无事件），个股 `none`；不会出现 `negative`。

### 例 2：拟减持

```text
正文：股东拟减持不超过 2% 股份
```

`medium` 降为 `weak`，`certainty=speculative`；个股风险 `watch`。

### 例 3：利好 + 减持

```text
正文：公司业绩预增，股东减持
```

目标日当天：正向 0.8、负向 0.8 → 占比 50% / 50% → `mixed`；个股风险 `downgrade`。

### 例 4：硬否决 + 利好

```text
正文：公司收到退市风险警示，同时发布业绩预增公告
```

负向 `hard` 1.0、正向 0.8 → 单元可能是 `mixed`，但个股风险固定 `block`；正向不能抵消。

### 例 5：板块回调

```text
关键词：板块回调
正文：银行板块回调，公司经营正常
```

语境不计分；只有语境证据时单元 `neutral`，个股 `none`。不得写成“个股利空”。

## 八、校准与边界

- 全部规则 `needs-backtest`；阈值 `0.30` / `0.25` / 半衰期 `3` 是初始值，未经人工标注样本校准。
- 词表只覆盖常见事件，未命中词进入 `unmatchedKeywords`（Top 50），用于下一轮扩词。
- 不做公告全文核验；厂商摘要的“已证实”不可采信，`confirmed` 不可达。
- 板块成分股是当前快照，历史日期无法还原当时成员；`quality.coverage.pointInTime=false`、`backtestGrade=C`。
- 个股新闻源不可用时只降低覆盖，不改变已有证据的结论；整体 `degraded`。
