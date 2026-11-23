# STEP 2.5 数据契约

本 Skill 的输入只有公开接口与上游 JSON；所有输出字段都是机器可读的稳定接口。

## 一、数据源

| 来源 | CLI 命令 | 用途 | v1 状态 |
|---|---|---|---|
| 异动解读 | `news anomaly-analysis --begin-date --end-date` | 主力证据；带 `thsHqCode` 与关键词 | 必选 |
| 涨停池 | `market limit-up-pool` | 涨停原因补证据；同时提供股票名 | 可选 |
| 个股新闻 | `news stock-timeline-list --thscode --offset --size` | 探测可用才启用；补个股覆盖 | 探测 |
| 交易日历 | `market calendar` | 判断交易日与时效衰减 | 必选（失败降级） |
| 成分股 | `index constituents` | STEP 1 板块成员 | 仅 `--step1` |
| 公告详情 | 不接入 | 需 opaque `seq`，无法枚举 | 不可用 |

主源策略：`primarySourceAvailable=false`。厂商提供的是 AI 摘要与关键词，不是公告原文；无法证明“已证实”，可信度最高 `partial`。

### 异动解读字段映射

| 上游字段 | 本 Skill 字段 | 说明 |
|---|---|---|
| `link_url` 中的 `thsHqCode` | `thscode` | 唯一归属依据；缺失则 `unattributed` |
| `tag_code` / `tag_name` | `sourceTag` | 只做展示，不参与打分 |
| `key_word_list` | `keyWords` | 先做词表路由，事件类直接计分 |
| `analysis_content` | `content` | 正文匹配；同时做去重键 |
| `link_url` 中的 `date=` | `date` | 缺失时回退 `asOf` 并置 `dateInferred=true` |

### 个股新闻字段映射

| 上游字段 | 本 Skill 字段 | 说明 |
|---|---|---|
| `content` / `summary` / `digest` | `content` | 取第一个非空值 |
| `title` | `title` | 仅保留在原始行 `raw` |
| `publish_time` / `publishTime` / `time` / `date` | `publishedAt` | 只取 `YYYY-MM-DD` 前缀 |
| `seq` / `notice_seq` / `id` | `seq` | 不用于 v1 取详情 |
| `url` / `link_url` | `url` | 去重兜底 |
| 其他字段 | `raw` | 原样保留，避免上游加字段时丢证据 |

## 二、上游 JSON

`--step1` / `--step2` 都必须满足：

- `schemaVersion` 必须为 `1.0`，否则整体 `insufficient` 并写明版本；
- STEP 1 读取 `directions[].thscode`、`directions[].name`、`directions[].pool`；
- STEP 2 读取 `themes[].themeId`、`themes[].name`、`themes[].tier`、`themes[].concept.thscode`、`themes[].members.codes`；
- `reportId` 只写入 `input.step1ReportId` / `input.step2ReportId`，不参与本层身份计算。

## 三、缓存布局

```
.cache/qts04/news/{asOf}/
├── anomaly-{start}_{end}.json    # 区间异动解读
├── limit-up.json                 # 当日涨停池
├── calendar.json                 # 交易日历
├── constituents/{thscode}.json   # 板块成分股（仅 --step1）
└── timeline/{thscode}.json       # 个股新闻（探测成功才写）
```

- 默认开启读缓存；`--refresh` 强制重取。
- 缓存不进入 Git；`.cache/` 已在忽略列表。
- 空结果同样写缓存；`--refresh` 强制重取，避免一次瞬时空响应在当天反复请求。

## 四、状态矩阵

| 条件 | 整体 `status` |
|---|---|
| 异动与涨停都不可用 | `insufficient` |
| 没有单元也没有股票 | `insufficient` |
| 个股新闻 `unavailable` | `degraded` |
| 任一单元极性 `unknown`（覆盖率闸门） | `degraded` |
| 其余 | `ok` |

单源状态：

| 字段 | 取值 |
|---|---|
| `quality.sources.anomalyAnalysis.status` | `ok` / `empty` / `unavailable` |
| `quality.sources.limitUpReason.status` | `ok` / `empty` / `unavailable` |
| `quality.sources.stockTimeline.status` | `ok` / `empty` / `unavailable` / `disabled` |
| `quality.coverage.calendar` | `ok` / `unavailable` |

错误码：

| 码 | 处理 |
|---|---|
| `FUYAO_5003` / `FUYAO_1002` | 个股新闻源不可用 → `FuyaoInsufficient`，整体 `degraded` |
| 限流 `4001` / `429` | 客户端有界重试；耗尽后 `degraded` |
| 其他非零 | `degraded` 并记录 `quality.warnings` |

## 五、输出字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schemaVersion` | string | 固定 `1.0` |
| `step` | string | 固定 `STEP 2.5` |
| `ruleVersion` | string | 固定 `QTS-04-09` |
| `reportId` | string | 16 位 SHA-256 前缀 |
| `asOf` | string | 目标交易日 |
| `config` | object | 冻结阈值、窗口、词表版本与哈希 |
| `input` | object | 上游 reportId、代码、条数、回看天数 |
| `status` | string | `ok` / `degraded` / `insufficient` |
| `quality` | object | 来源状态、覆盖、告警、时点标记 |
| `primarySourceAvailable` | bool | 固定 `false` |
| `primarySourceReason` | string | 主源不可枚举的原因 |
| `units[]` | array | 板块/题材单元极性 |
| `stocks[]` | array | 个股风险与极性 |
| `evidence[]` | array | 去重后的证据清单（正文截断 300 字） |
| `lexicon` | object | 词表版本、SHA-256、规则计数 |
| `unmatchedKeywords` | array | 未命中词频 Top 50 |
| `disclaimer` | string | 免责声明 |
| `calibration` | string | 固定 `needs-backtest` |

`reportId` 覆盖字段：

```
schemaVersion, step, ruleVersion, asOf, config, input, units, stocks, lexicon
```

不覆盖 `generatedAt`（本层不生成）、`quality`、`evidence`：同一输入与词表重跑必须稳定；词表哈希在 `config` 与 `lexicon` 中，词表变化必然换号。

## 六、单元与个股字段

`units[]`：

| 字段 | 说明 |
|---|---|
| `unitId` | `theme:{themeId}` 或 `sector:{thscode}` |
| `unitType` | `theme` / `sector` |
| `name` / `thscode` / `tier` | 来自上游 |
| `members.count` / `members.pointInTime` | 成员数与是否可历史还原 |
| `evidenceCount` / `coveredMembers` | 窗口内证据条数与覆盖成员数 |
| `polarity` | 五档标签、分数、占比、置信度、缺口语义 |
| `events` | 去重后的事件摘要（最多 20 条） |
| `evidenceRefs` | 证据 ID（最多 20 条） |
| `missingReason` | `unknown` 时的原因 |

`stocks[]`：

| 字段 | 说明 |
|---|---|
| `thscode` / `name` | 代码与名称（名称可能为空） |
| `riskLevel` | `block` / `downgrade` / `watch` / `none` / `uncovered` |
| `coverage` | `covered` / `uncovered` |
| `evidenceCount` / `polarity` / `events` | 同上 |
| `flags` | 负向事件摘要（最多 20 条） |
| `missingReason` | `uncovered` 时的原因 |

## 七、离线 fixture

fixture 是一个 JSON 对象，字段全部可选：

```json
{
  "asOf": "2026-11-13",
  "tradingDays": ["2026-11-13"],
  "anomalies": [],
  "limitUps": [],
  "timelines": {"002115.SZ": []},
  "timelineError": "FUYAO_5003",
  "constituents": {"881101.TI": [{"thscode": "002115.SZ"}]},
  "step1": {"schemaVersion": "1.0", "directions": []},
  "step2": {"schemaVersion": "1.0", "themes": []}
}
```

fixture 模式下不创建 `FuyaoClient`，测试通过 monkeypatch `FuyaoClient.call` 断言零网络调用。
