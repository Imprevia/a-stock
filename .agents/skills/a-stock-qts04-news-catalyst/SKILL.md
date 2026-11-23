---
name: a-stock-qts04-news-catalyst
description: 按 QTS-04 第 04 章 STEP 2.5 做盘后消息面利好利空分析：把异动解读、涨停原因与可选的个股新闻按 thscode 归属到板块/题材/个股，用冻结词表判定 five 档极性（利好/利空/多空交织/中性/无法判定）与 five 档个股风险（硬否决/降级/观察/未见利空/未覆盖），输出可复算 JSON 与经机械校验的人读报告。用于用户问“今天/某日这些板块或题材是利好还是利空”“消息面怎么样”“有没有减持/解禁/退市风险”“个股利空筛查”“消息面极性”时；不用于盘中预测、买卖点、目标价、收益回测或公告全文核验。
---

# QTS-04 STEP 2.5 消息面极性

## 这个 Skill 做什么

把“这条消息是利好还是利空”拆成可机械复算的五步：

1. **取数**：区间异动解读（必选）、当日涨停原因（可选）、个股新闻时间线（探测可用才启用）。
2. **归属**：只按 `thscode` 挂到具体单元；文本去重；没有代码的资讯计入 `unattributed`，不硬塞给板块。
3. **识别**：冻结词表把关键词分成**事件 / 题材 / 语境**三类；只有事件参与打分，语境只解释“为什么全板块都在跌”。
4. **打分**：`baseWeight × sourceFactor × recencyDecay × certaintyFactor`；否定与不确定词按作用域降级或取消；单元要过“≥2 条证据、≥2 只成员”的覆盖率闸门。
5. **分级**：单元五档极性 + 个股五档风险；`unknown` 与 `neutral` 分开，`uncovered` 与 `none` 分开。

JSON 是唯一事实源；Markdown 只是 agent 撰文的底稿与校验失败时的兜底。

## 前置条件

- Python 3.11+；仓库虚拟环境 `.venv`。
- 官方 CLI `hithink-finance` 在 `PATH`（Node.js 22.12+）。
- 凭据解析顺序与 STEP 1 一致：`FUYAO_API_KEY` → `MARKET_ENVIRONMENT_FUYAO_API_KEY` → `deploy/truenas/deploy.env`。
- 目标日必须是已收盘交易日；未来日期、当日 15:10 前、非交易日一律拒绝。
- 公告/政策主源不可枚举，因此 `primarySourceAvailable=false`，厂商 AI 摘要最高只能支撑 `partial`。

## 工作流

```bash
# 1) 题材料（STEP 2 JSON）→ 单元极性 + 个股风险
.venv/bin/python .agents/skills/a-stock-qts04-news-catalyst/scripts/news_pipeline.py \
  --as-of 2026-11-13 --step2 .cache/qts04/theme-layer-2026-11-13.json \
  --output .cache/qts04/news-2026-11-13.json

# 2) 板块层（STEP 1 JSON）→ 板块极性（成分股为当前快照）
.venv/bin/python .agents/skills/a-stock-qts04-news-catalyst/scripts/news_pipeline.py \
  --as-of 2026-11-13 --step1 .cache/qts04/sector-direction-2026-11-13.json \
  --output .cache/qts04/news-sector-2026-11-13.json

# 3) 只筛指定个股
.venv/bin/python .agents/skills/a-stock-qts04-news-catalyst/scripts/news_pipeline.py \
  --as-of 2026-11-13 --codes 002115.SZ,300001.SZ \
  --output .cache/qts04/news-codes-2026-11-13.json

# 4) agent 依据 JSON 写报告（不要照抄骨架）

# 5) 机械校验：PASS 才能呈现
.venv/bin/python .agents/skills/a-stock-qts04-news-catalyst/scripts/news_check_report.py \
  --result .cache/qts04/news-2026-11-13.json \
  --article /path/to/article.md

# 6) FAIL 时回退事实骨架
.venv/bin/python .agents/skills/a-stock-qts04-news-catalyst/scripts/news_pipeline.py \
  --as-of 2026-11-13 --step2 .cache/qts04/theme-layer-2026-11-13.json \
  --format markdown
```

离线 fixture（不发起网络）：

```bash
.venv/bin/python .agents/skills/a-stock-qts04-news-catalyst/scripts/news_pipeline.py \
  --as-of 2026-11-13 \
  --fixture tests/fixtures/a_stock_qts04_news_catalyst/news-mixed.json
```

## 三种产物

| 产物 | 用途 | 是否对外 |
|---|---|---|
| JSON | 唯一事实源；供下游/回测/校验消费 | 否 |
| Markdown 事实骨架 | agent 撰文底稿；校验失败时直接呈现 | 仅在回退时 |
| agent 报告 | 人读结论；必须通过 `news_check_report.py` | 是 |

JSON 顶层字段：`schemaVersion`、`step`、`ruleVersion`、`reportId`、`asOf`、`config`、`input`、`status`、`quality`、`primarySourceAvailable`、`primarySourceReason`、`units`、`stocks`、`evidence`、`lexicon`、`unmatchedKeywords`、`disclaimer`、`calibration`。

## 分级口径

单元极性（五档）：

| 标签 | 判定 |
|---|---|
| `positive` 利好 | 正负净分 ≥ +0.25，且空方占比 < 30% |
| `negative` 利空 | 正负净分 ≤ −0.25，且多方占比 < 30% |
| `mixed` 多空交织 | 正、负占比都 ≥ 30% |
| `neutral` 中性 | 有证据、但净分落在 ±0.25 之间且未达 mixed |
| `unknown` 无法判定 | 没证据，或未过“≥2 条证据、≥2 只成员”闸门 |

个股风险（五档）：

| 标签 | 判定 |
|---|---|
| `block` 硬否决 | 存在 `hard` 级负向事件（退市、立案、造假、资金占用、债务违约等） |
| `downgrade` 降级 | 最高负向为 `medium`（预亏、减持、解禁、诉讼、订单取消等） |
| `watch` 观察 | 只有 `weak` 负向（问询函、风险提示等），或不确定措辞把 medium 降成 weak |
| `none` 未见利空 | 有证据，但没有负向事件 |
| `uncovered` 未覆盖 | 窗口内没有归属证据，或个股新闻源不可用 |

`block` 只是提示，不自动排除；`uncovered` 不等于“无利空”，`unknown` 不等于“中性”。

## 输出约束

- 只写观察与解释，不写买入/加仓/仓位/必涨/目标价；结尾必须有免责声明与 `needs-backtest`。
- 文章里的每个数字都必须能在 JSON 中找到出处；日期、股票代码、规则 ID、`reportId` 由校验器自动屏蔽。
- 极性只能使用 JSON 中的值：利好 / 利空 / 多空交织 / 中性 / 无法判定。证据不足的单元必须写“无法判定”，不得写成“中性”。
- 个股风险只能使用 JSON 中的值：硬否决 / 降级 / 观察 / 未见利空 / 未覆盖。未覆盖个股必须写“未覆盖”，不得写“无利空”。
- `primarySourceAvailable=false` 时不得写“已证实”“确认利好”“确认利空”；可信度最高只能是 `partial`（部分证实）。
- 成员数、证据数、覆盖率必须与 JSON 一致；缺失值写 `—`，不得补 0。
- 语境类关键词（板块回调、大盘下跌、美联储等）只能解释板块普跌，不得当成个股利空。

## 呈现流程

1. 运行 `news_pipeline.py` 生成 JSON；记录 `reportId`、`status`、`primarySourceAvailable`。
2. agent 依据 JSON 写报告：先写数据状态与覆盖缺口，再写单元极性，最后写个股风险与边界。
3. 运行 `news_check_report.py`；只有 `PASS` 才能呈现报告。
4. `FAIL` 时呈现 `render_fallback` 的事实骨架 + 未通过项，不解释为成功。
5. 把 `reportId`、`status`、`units`/`stocks` 数量、校验结果记入 active plan。

## 不变量

- 归属只看 `thscode`；没有代码的资讯只能进 `unattributed`，不能按板块名硬猜。
- 关键词与正文冲突时以正文为准：`终止减持` 不产生负向，`拟减持` 最多到 `watch`。
- 否定作用域只回看 8 个字符，遇到 `。；;！!` 立即失效；不得跨句否定。
- 语境类命中不计分；同一段文本里“板块回调 + 个股减持”必须拆开。
- 个股新闻源 `stock-timeline-list` 可能返回 `FUYAO_5003`；此时标记 `unavailable`、整体 `degraded`，继续用异动解读出结论。
- 板块成分股只有当前快照，`quality.coverage.pointInTime=false`、`backtestGrade=C`；不做历史成员还原。
- 主源不可枚举，`confirmed` 不可达；不得用“公告全文已确认”替代证据。
- 任何数据缺失输出 `insufficient` 或 `degraded`，不借相邻日期、不伪造成功。

## 退出码

- `0`：`status=ok` 或 `degraded`，JSON 已写出。
- `1`：`status=insufficient`，仍写出结构化 JSON 与原因。
- `2`：输入文件缺失/非法；`news_check_report.py` 的输入错误也走 2。

## 参考

- `references/data-contract.md`：上游字段、缓存布局、状态矩阵、错误码。
- `references/scoring-rules.md`：词表 schema、匹配与否定、打分公式、阈值与算例。
