## Why

QTS-04 的 STEP 2 已经能回答「这个题材有没有共同催化、催化有多可信」，但回答不了「这条催化是利好还是利空」：`theming.py` 把「公告/消息/利好/政策」当成停用词直接丢弃，四级催化标签只表示证实程度，不表示方向。与此同时，STEP 8 的「公告/减持/解禁/业绩预亏」风险过滤仍停在文档里，没有可机械复算的实现。结果是一条明确的退市风险提示和一条业绩预增，在现有 JSON 里都只是「共享 token 命中」。

现在可以做，是因为异动解读（`news anomaly-analysis`，≥2 年窗口）和涨停原因已经由现有 Skill 稳定消费，只是没有被用于方向判断；缺的是词表口径、证据归属规则和「未覆盖不等于无利空」的显式语义，而不是新数据源。

## What Changes

- 新增独立 Skill `a-stock-qts04-news-catalyst`：输入一个已收盘交易日，输出 `units[]`（板块/题材级极性）与 `stocks[]`（个股利空分级）两段结果；可独立运行，也可链式消费 STEP 1 或 STEP 2 的 JSON。
- 新增规则族 `QTS-04-09`（五条规则：证据归属、极性判定、时效与强度、个股硬否决、覆盖率闸门），并在量化版第 04 章新增 `09.消息面极性规则.md`；全部阈值状态 `needs-backtest`。
- 新增**版本化词表** `lexicon.v1.json`：每条规则带 `ruleId`、事件类型、极性、严重度、权重、否定行为（取消/降级/翻转）；否定词与不确定词（拟/预计/传闻/或将）就近作用域处理；词表哈希冻结进 `config`，词表变更即换 `reportId`。
- 极性输出限定为 `positive / negative / mixed / neutral / unknown` 五档，个股风险限定为 `block / downgrade / watch / none / uncovered` 五档；**`uncovered` 与 `none` 必须分开**，没检索到证据不得写成「无利空」。
- 证据来源分层：`news anomaly-analysis` 为主源，涨停原因为辅；`news stock-timeline-list` 作为「探测可用才启用」的扩展源（2026-11-13 实测返回 `FUYAO_5003`），不可用时写 `stockTimeline.status=unavailable` 并把个股覆盖降级，不伪造覆盖。
- 显式输出 `primarySourceAvailable=false`：公告/政策主源不可枚举（`notice-detail` 需 opaque `seq`），因此极性最高只能到 `partial`，不得出现「已证实」「确认利好」。
- JSON 合同：`schemaVersion` / `step` / `ruleVersion` / `reportId` / `asOf` / `config` / `input` / `status` / `quality` / `units[]` / `stocks[]` / `lexicon` / `disclaimer` / `calibration`；每个单元带 `polarity{label,score,positiveScore,negativeScore,confidence,evidenceCount,coveredMembers}`、`events[]`、`evidenceRefs[]`、`missingReason`。
- 新增机械校验：文章只能使用 JSON 中的极性与风险标签，未覆盖股票必须写「未覆盖」，禁止把 `unknown` 写成「中性」；禁词集合沿用 STEP 1/2 并增加「确认利好」「已证实」。
- 不修改 STEP 1/STEP 2 的输出合同，不改变既有 `reportId`；链式运行只读取上游 `reportId`，不参与重算。

## Capabilities

### New Capabilities

- `qts04-news-catalyst-skill`: 按 QTS-04 第 04 章的消息面层，把公告/新闻/异动解读与涨停原因归一到板块、题材、个股三个单元，输出可复算的利好/利空极性、个股风险分级、证据溯源与覆盖缺口声明。

### Modified Capabilities

（无。STEP 1 与 STEP 2 的既有 requirement 不变；新 Skill 只消费它们的 JSON 并记录上游 `reportId`。）

## Impact

- 新增代码：`.agents/skills/a-stock-qts04-news-catalyst/`（`SKILL.md`、`scripts/`、`references/lexicon.v1.json`、`references/data-contract.md`、`references/scoring-rules.md`）。
- 修改共享底座：`.agents/skills/qts04-core/scripts/qts04/client.py` 增加区间版 `anomaly_analysis` 与 `stock_timeline` 两个只读方法；既有单日方法改为委托，行为不变。`notice-detail` 因无列表枚举入口不进入 v1 调用路径，也不新增死代码。
- 新增测试与 fixture：`tests/test_a_stock_qts04_news_catalyst_skill.py`、`tests/fixtures/a_stock_qts04_news_catalyst/`（利好、硬利空、多空交织、否定翻转、未覆盖、空结果、`FUYAO_5003` 降级七类样本），全部离线。
- 文档：新增 `搭建交易系统-量化版/04-板块、题材与个股筛选/09.消息面极性规则.md` 并更新同章 `0-板块、题材与个股筛选.md` 索引；`trading-rules/coverage.yaml` 增加 5 条 `documented-only` 条目并把 `documentedRules` 从 330 改为 335；同步 `tests/test_trading_rule_platform.py` 的期望值；更新 `docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md`（STEP 2.5 与数据可得性台账）、`docs/repository-guide.md`、`docs/status.md` 和新增 active plan。
- 不涉及：`src/` 业务代码、`trading-rules/rule-sets/` evaluator、数据库、生产集群、调度与部署；不新增 provider 或凭据。
- 风险披露：极性是文本方向标签，不是收益预测；AI 摘要只能到 `partial`；`stock-timeline-list` 可能持续不可用，个股层覆盖只到异动池；词表准确率必须用人工标注样本校准，未校准前只能做排序与提示，不能单独触发排除或入选。