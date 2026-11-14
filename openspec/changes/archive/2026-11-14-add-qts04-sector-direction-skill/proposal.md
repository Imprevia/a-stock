## Why

`docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md` 已固化第 04 章从板块到个股的选股流水线，但 `QTS-04` 共 45 条规则在 `trading-rules/coverage.yaml` 中全部是 `documented-only`，没有任何一条能真正执行。第 04 章 STEP 1（板块层定方向）是整条流水线的第一个决策点，其五条规则 `QTS-04-01-01` ~ `-05` 的数据底座最完整，且不需要等待题材催化证据或竞价数据。同时，仓库自身 v2 接口的 `sectors/rankings`、`sectors/turnover`、`sectors/breadth` 在 k3s 生产环境返回 500（`AmbiguousParameter`），无法作为 Skill 的数据通道；fuyao 官方 API 已提供完整且可直接调用的板块目录、成分股与历史 K 线能力。

## What Changes

- 新增仓库级 `a-stock-qts04-sector-direction` Skill，响应“板块定向”“今天/某日的强势板块”“板块四象限”等请求，输出 1—3 个候选方向及其次日确认与失效条件。
- Skill 直接调用 fuyao 官方 CLI `hithink-finance` 取数，不经过仓库自身 HTTP 接口；凭据取自 `FUYAO_API_KEY` 环境变量，或已被 git 忽略的 `deploy/truenas/deploy.env` 中的 `FUYAO_API_KEY`。
- 实现 `QTS-04-01-01` ~ `-05` 五指标的确定性计算：5 日相对强度、20 日相对强度、成交额增量、板块宽度（`close > MA20` 成分股比例）、持续与恢复。
- 实现 250 交易日滚动分位打分（五档 0/25/50/75/100），并实现分位观测不足时的分级降级：60—249 观测为 `reduced-confidence`，不足 60 观测为 `insufficient` 且得分为 `null`。
- 实现行业成分股覆盖率闸门：有效覆盖率低于 70% 的行业不参与排名，输出 `insufficient`。
- 实现四象限判定（真实流入 / 短线脉冲 / 权重拉升 / 资金撤退），该判定只依赖覆盖率与资金强度的原始值，不依赖分位是否可用。
- 宽度指标按 `--breadth-universe N` 只对综合分前 N 个行业计算，默认 30，避免全市场枚举。
- 首次运行拉取 250 交易日板块日线并落本地可重建缓存；缓存不入库、不入 git。
- 增加离线 fixture 与 pytest 覆盖，测试不发起任何网络请求。
- 一次运行同时产出 JSON 与人工可读的 Markdown 报告（`scripts/report.py`），报告由 JSON 纯渲染，数值不可能与 JSON 分歧。
- 保持所有规则状态为 `needs-backtest`，不输出 `validated`、买卖点、仓位或个股推荐。

## Capabilities

### New Capabilities

- `qts04-sector-direction-skill`: 为 Agent 提供基于 fuyao 直连数据的板块层定向能力，覆盖五指标计算、滚动分位打分、覆盖率闸门、四象限分类与次日确认/失效条件输出。

### Modified Capabilities

- 无。现有 `daily-tier-market-environment-review`、`market-data-snapshot-cache`、`ai-market-data-api` 与交易规则平台行为均不变；本 Skill 是独立的只读消费者，不修改 `trading-rules/`、`coverage.yaml` 或 `src/`。

## Impact

- 新增 `.agents/skills/a-stock-qts04-sector-direction/` 下的 Skill 指令、确定性脚本与按需参考资料。
- 新增 `tests/test_a_stock_qts04_sector_direction_skill.py` 与小型合成 fixture。
- 新增 active plan `docs/exec-plans/active/add-qts04-sector-direction-skill.md`，并更新 `docs/exec-plans/active/_index.md` 与 `docs/repository-guide.md` 的 Skill 映射。
- 新增强制外部依赖：Node.js 22.12+ 与全局命令 `hithink-finance`（`@hithink-tech/hithink-finance-cli`）。缺少该命令时 Skill 必须输出 `insufficient` 并说明原因，不得伪造数据。
- 不修改 FastAPI 路由、数据库 schema、交易规则 YAML、生产配置、调度、凭据或远端市场数据写入。