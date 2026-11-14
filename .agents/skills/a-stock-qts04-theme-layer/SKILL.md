---
name: a-stock-qts04-theme-layer
description: 按 QTS-04 第 04 章 STEP 2 对 A 股做盘后题材层定向：用概念成分股 ∩ 当日涨停池建立题材单元，计算 lift、共享 token、成员宽度与涨停梯队，输出核心/扩散/事件/伪题材四级和四级催化标签，并给出次日确认/失效条件。用于用户要求“今天/某日哪些题材是真的”“题材真伪”“核心题材”“涨停归因”“题材扩散”时；不用于盘中预测、个股推荐、自动交易或收益回测。
---

# QTS-04 STEP 2 题材层

## 这个 Skill 做什么

把“今天什么题材是真的”拆成可机械复算的步骤：

1. 取概念目录、概念成分股、当日涨停池、涨停统计、异动解读、概念日线与基准日线。
2. 只在 **概念当前成分股 ∩ 当日涨停池** 的交集内部统计共享 token。
3. 用 `lift = 命中数 / (成员数 × 全市场涨停率)` 做硬闸门，而不是按涨停家数排序。
4. 输出四级题材（核心/扩散/事件/伪题材）和四级催化（`confirmed/partial/speculative/unknown`）。
5. 当日没有合格核心题材时输出 `noCoreTheme=true` 与原因，不编造。

JSON 是唯一事实源；Markdown 只是 agent 撰文的底稿与校验失败时的兜底。

## 前置条件

- Python 3.11+；仓库虚拟环境 `.venv`。
- 官方 CLI `hithink-finance` 在 `PATH`（Node.js 22.12+）。
- 凭据解析顺序与 STEP 1 一致：`FUYAO_API_KEY` → `MARKET_ENVIRONMENT_FUYAO_API_KEY` → `deploy/truenas/deploy.env` 的 `FUYAO_API_KEY`。
- 目标日必须是已收盘交易日；未来日期、当日 15:10 前、非交易日一律拒绝。

## 工作流

```bash
# 1) 独立运行：生成 JSON + 事实骨架
.venv/bin/python .agents/skills/a-stock-qts04-theme-layer/scripts/theme_pipeline.py \
  --as-of 2026-11-13 \
  --output .cache/qts04/theme-layer-2026-11-13.json \
  --report .cache/qts04/theme-layer-2026-11-13.md

# 2) 链式运行：消费 STEP 1 的 JSON（可选）
.venv/bin/python .agents/skills/a-stock-qts04-theme-layer/scripts/theme_pipeline.py \
  --as-of 2026-11-13 --step1 /path/to/sector-direction.json \
  --output .cache/qts04/theme-layer-2026-11-13.json

# 3) agent 依据 JSON 写文章（不要照抄骨架）

# 4) 机械校验：PASS 才能呈现
.venv/bin/python .agents/skills/a-stock-qts04-theme-layer/scripts/theme_check_report.py \
  --result .cache/qts04/theme-layer-2026-11-13.json \
  --article /path/to/article.md

# 5) FAIL 时回退事实骨架
.venv/bin/python .agents/skills/a-stock-qts04-theme-layer/scripts/theme_pipeline.py \
  --as-of 2026-11-13 --format markdown
```

离线 fixture（不发起网络）：

```bash
.venv/bin/python .agents/skills/a-stock-qts04-theme-layer/scripts/theme_pipeline.py \
  --as-of 2026-11-13 \
  --fixture tests/fixtures/a_stock_qts04_theme_layer/strong.json
```

## 三种产物

| 产物 | 用途 | 是否对外 |
|---|---|---|
| JSON | 唯一事实源；供下一步/回测/校验消费 | 否 |
| Markdown 事实骨架 | agent 撰文底稿；校验失败时直接呈现 | 仅在回退时 |
| agent 文章 | 人读报告；必须通过 `theme_check_report.py` | 是 |

JSON 顶层字段：`schemaVersion`、`step`、`reportId`、`asOf`、`config`、`input`、`status`、`quality`、`catalystPolicy`、`noCoreTheme`、`noCoreReasons`、`themes`、`unmappedTokens`、`disclaimer`、`calibration`。

## 输出约束

- 只写观察与剧本，不写买入/加仓/仓位/必涨/目标价；结尾必须有免责声明与 `needs-backtest`。
- 文章里的每个数字都必须能在 JSON 中找到出处；比赛、日期、股票代码、reportId 由校验器自动屏蔽。
- 分级只能使用 JSON 中的值：核心题材 / 扩散题材 / 事件题材 / 伪题材。
- 催化只能使用 JSON 中的值：部分证实 / 市场推测 / 原因不明；`confirmed` 在 v1 不可达，文章不得写“已证实”。
- `noCoreTheme=true` 时，文章必须写“今日没有核心题材”及原因，不得改写成核心题材。
- 成员数、涨停成员数、lift、共享 token 必须与 JSON 一致；缺失值写 `—`，不得补 0。

## 呈现流程

1. 运行 `theme_pipeline.py` 生成 JSON；记录 `reportId`、`status`、`noCoreTheme`。
2. agent 依据 JSON 写文章。
3. 运行 `theme_check_report.py`；只有 `PASS` 才能呈现文章。
4. `FAIL` 时呈现 `render_fallback` 的事实骨架 + 未通过项，不解释为成功。
5. 把 `reportId`、`status`、`noCoreTheme`、校验结果记入 active plan。

## 不变量

- 题材单元必须是“概念当前成分股 ∩ 当日涨停池”，不能只用概念涨幅或涨停原因词。
- 共享 token 只在交集内部统计，`count ≥ 2` 才计入；单股 token 永远不算共同催化。
- lift 是硬闸门：核心 ≥3.0、扩散 ≥1.5；低于 1.5 只能判伪题材。
- `confirmed` 永久不可达：公开接口只有涨停原因与 AI 汇总异动解读，主源不可枚举。
- 成分股只有当前快照，历史日期无法还原当时成员；`quality.pointInTime=false`、`backtestGrade=D`。
- 任何数据缺失输出 `insufficient` 或 `degraded`，不借相邻日期、不伪造成功。

## 与 STEP 1 的关系

- 独立运行：`--step1` 省略，`themes[].direction=null`。
- 链式运行：读取 STEP 1 JSON，校验 `schemaVersion` 与 `reportId`，按成员交集计算 `direction.overlapJaccard`；该值只记录，不参与分级。
- STEP 1 的 `reportId` 写入 `input.step1.reportId`；本 Skill 的 `reportId` 不依赖 STEP 1，保证可独立复算。

## 退出码

- `0`：`status=ok` 或 `degraded`，JSON 已写出。
- `1`：`status=insufficient`，仍写出结构化 JSON 与原因。
- `2`：输入文件缺失/非法；`theme_check_report.py` 的 `ERROR` 也走 2。
