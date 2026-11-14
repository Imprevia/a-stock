## Why

STEP 1 已能产出 1—3 个板块方向，但"资金在交易哪条逻辑"还没有答案，STEP 3—10 也没有可消费的上游。第 04 章的题材层长期停在文字描述，是因为它被当成"选词"问题：靠概念名、标签或新闻标题去匹配题材。2026-11-14 实测证明这条路走不通——当日 112 个涨停原因 token 中只有 9 个能精确匹配 390 个概念名，92 个无法映射（见 `docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md` 6.4）。

现在有第二条路可走：按**概念成员共现**统计共同催化，用 **lift 基准率校正**判定题材真伪，用**四级标签**限定催化证实程度。这三件事都能只用 fuyao 官方 CLI 的数据机械完成，因此可以把题材层做成和 STEP 1 同规格的 Skill：JSON 是唯一事实源，agent 只负责表达，回测只读 JSON。

## What Changes

- 新增 Skill `a-stock-qts04-theme-layer`：输入一个交易日，输出 0—5 条题材（含 `noCoreTheme` 空结果分支）。
- 题材单元改为**概念 × 成员共现**：先取概念成分股与当日涨停池的交集，再在交集内部统计共享 token；不再依赖概念名与涨停原因词表的匹配。
- 新增 **lift 硬闸门**：`lift = 涨停命中数 / (成员数 × 全市场涨停率)`，避免宽概念被误判为主线（实测新能源汽车 10 只涨停 lift 仅 1.33，短剧游戏 7 只 lift 达 9.95）。
- 新增**四级催化标签** `confirmed / partial / speculative / unknown`，并显式输出 `confirmed = unavailable`：公告与新闻主源不可枚举，只允许用厂商 AI 摘要支撑 `partial`。
- 新增 **point-in-time 声明**：JSON 带 `quality.pointInTime`、`membershipAsOf`、`backtestGrade`，把"成分股只有当前快照"这一回测硬约束写进数据。
- 抽取共享模块 `qts04-core`（`fuyao_client` / `cache` / `contract` / `predicate` / `check_report`），STEP 1 改为引用，行为不变；校验器新增**标签溯源**能力，未配置标签映射时保持原三类检查。
- JSON 合同：`schemaVersion` / `reportId` / `config` / `input.step1ReportId` / `status` / `quality` / `noCoreTheme` / `themes[]` / `disclaimer`；确认与失效沿用 STEP 1 的扁平谓词结构。
- 可独立运行（只给交易日），也可消费 STEP 1 JSON（用成员重叠 `overlapJaccard` 关联方向）。

## Capabilities

### New Capabilities

- `qts04-theme-layer-skill`: 按 QTS-04 第 04 章 STEP 2 从板块方向收缩到题材层——概念成员共现、lift 校正、共享 token、四级催化标签、空结果与 point-in-time 声明，输出可被下游 Skill 消费的 JSON 与人读报告。

### Modified Capabilities

（无。共享模块抽取不改变 STEP 1 的能力要求与行为：校验器在未配置标签映射时仍只做数字溯源、禁词与必备项三类检查。）

## Impact

- 新增代码：`.agents/skills/a-stock-qts04-theme-layer/`（`SKILL.md`、`scripts/`、`references/`）。
- 新增共享代码：`.agents/skills/qts04-core/`（从 STEP 1 迁移的五个模块）。
- 修改代码：`.agents/skills/a-stock-qts04-sector-direction/scripts/` 改为引用共享模块（行为不变，既有 57 个用例必须保持通过）。
- 新增测试：`tests/test_a_stock_qts04_theme_layer_skill.py`；`tests/test_a_stock_qts04_sector_direction_skill.py` 的导入路径可能随抽取调整。
- 新增 fixture：`tests/fixtures/a_stock_qts04_theme_layer/`（含强题材日、弱题材日、宽概念伪题材日、成分股缺失日）。
- 文档：更新 `docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md` 的阶段 1.5 证据与 `docs/repository-guide.md` 的代码-文档映射。
- 不涉及：`trading-rules/`、`src/`、`coverage.yaml`、数据库、生产集群、调度与部署。
- 依赖：fuyao 官方 CLI（`hithink-finance`）与凭据，解析顺序与 STEP 1 一致。
- 风险披露：`confirmed` 档不可达；涨停池与竞价数据只有约 1 年窗口；历史成分股版本缺失，题材归属回测存在事后偏差。
