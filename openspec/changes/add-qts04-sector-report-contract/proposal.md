## Why

STEP 1 板块层定向已经能产出方向，但产物是"自己看"的：JSON 缺少稳定接口标识和机器可判定的条件，人工报告只能由脚本按死板模板渲染，两边都接不住下一步。要让 STEP 2 题材层直接消费第一步的 JSON，要让报告能被机械校验、被事后回测，必须先把报告契约固定下来。

## What Changes

- JSON 增加 `schemaVersion`、`reportId`、`config` 冻结块，使其可作为跨 Skill 接口。
- **BREAKING** `confirmation` / `invalidation` 由中文散文字符串改为结构化谓词对象（`{text, horizonDays, all:[{field, op, value, basis}]}`），散文降级为 `text` 字段。
- 新增 `scripts/check_report.py`：对 agent 撰写的文章做数字溯源、禁词与必备项校验，校验自身确定性且可测试。
- `scripts/report.py` 降级为"事实骨架"生成器，不再是对外主报告；`--format markdown` 保留为无模型兜底。
- SKILL.md 的输出段落由固定模板改写为约束（必备字段、必备警告、禁止措辞），允许 agent 按当日情况压缩或展开。
- 报告不再声称"人读产物与 JSON 逐字一致"；改为声明文章是 JSON 的视图、回测只读 JSON。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `qts04-sector-direction-skill`: 报告契约变化——新增接口标识与冻结配置、条件结构化、人工报告改为"agent 撰写 + 机械校验"并要求 SKILL.md 输出约束化。

## Impact

- 受影响代码：`.agents/skills/a-stock-qts04-sector-direction/scripts/sector_pipeline.py`、`scripts/report.py`、新增 `scripts/check_report.py`、`SKILL.md`、`references/data-contract.md`。
- 受影响测试：`tests/test_a_stock_qts04_sector_direction_skill.py`（现有 57 个用例中 12 个覆盖 `report.py`，需随角色降级调整）。
- 下游消费者：STEP 2 题材层将依赖 `schemaVersion: 1.0` 与 `reportId`。
- 不涉及：`trading-rules/`、`src/`、`coverage.yaml`、数据库、生产集群与部署。
- 前置依赖：本变更修改的能力由尚未归档的 `add-qts04-sector-direction-skill` 引入，需先归档该变更，主 specs 中才会存在该能力。