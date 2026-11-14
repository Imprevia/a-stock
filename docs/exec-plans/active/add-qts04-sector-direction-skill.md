# QTS-04 选股流水线 Skill — 阶段 1：板块层定向（STEP 1）

> 上游方案：`docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md` 的十步流程 STEP 1 与分期路线阶段 1 的第一组规则（`QTS-04-01-01` ~ `-05`）。
> 本 plan 只覆盖 **STEP 1 板块层**；STEP 2 及之后的题材、资金、角色、模式、基本面、冲突仲裁、剧本输出不在本轮范围。

---

## Stage（阶段）

- 当前阶段：**Stage 1 — STEP 1 板块层定向 Skill（数据接入 + 五指标 + 四象限）**
- 阶段序列：STEP 1 板块层（本轮）→ STEP 2 题材层 → STEP 3 资金层 → STEP 4/5 角色与龙头 → STEP 6/7 候选与模式 → STEP 8/9/10 风险、仲裁、剧本
- 本轮边界：只做板块层。不实现题材、个股候选、角色分类、模式分组、基本面、冲突仲裁和次日剧本。

## Status（状态）

`complete` — 42/42 任务完成；Skill 包、确定性脚本、人工可读报告、参考资料与离线测试均已落地，四道门禁通过，并以 fuyao 真实数据完成只读验证。OpenSpec 变更已于 2026-11-14 归档为 `2026-11-14-add-qts04-sector-direction-skill`，主规格落在 `openspec/specs/qts04-sector-direction-skill/`（13 条要求 / 31 个 scenario）。后续契约演进由 `add-qts04-sector-report-contract` 承接。

## 背景与决策

上游 plan 记录第 04 章 45 条规则全部 `documented-only`，且本地 API 的 sector 三个列表端点在生产环境返回 500（`AmbiguousParameter`，root runbook 已记录同类缺陷）。

主控确认的四项决策：

| 决策项 | 结论 |
|---|---|
| 交付形态 | 纯 Skill；不改 `trading-rules/`、`src/`、`coverage.yaml` |
| 数据源 | 直接取 fuyao（`https://fuyao.aicubes.cn`），**不经过仓库自身 HTTP 接口** |
| 凭据 | `FUYAO_API_KEY` 环境变量或 `deploy/truenas/deploy.env`（git 忽略） |
| 调用方式 | 调用官方 CLI `hithink-finance`（`@hithink-tech/hithink-finance-cli`） |
| 宽度范围 | `--breadth-universe N` 可配置，默认 30 |
| 历史缓存 | 首次拉 250 交易日板块日线，落本地缓存 |
| 基准指数 | 上证综指 `000001.SH` |
| 板块 tag | 只做 `industry` |

## Acceptance（验收）

- [x] `.agents/skills/a-stock-qts04-sector-direction/SKILL.md` 存在，frontmatter 的 name/description 可判别触发场景，且不宣称任何买入信号或已回测结论。
- [x] 脚本可在离线 fixture 模式下输出结构化 JSON，五指标均有 `value` / `status` / `score` / `percentile` / `weight` 字段。
- [x] 覆盖率闸门生效：成分股有效覆盖率 <70% 的行业不参与排名，输出为 `insufficient` 而非 0 分。
- [x] 分位观测不足时降级：<60 观测输出 `insufficient`，60—249 输出 `reduced-confidence`；不填 0。
- [x] 四象限分类（真实流入 / 短线脉冲 / 权重拉升 / 资金撤退）可由原始值直接判定，不依赖分位是否可用。
- [x] 输出包含 1—3 个方向，每个方向带次日确认条件与失效条件的具体数值。
- [x] 所有规则状态标记为 `needs-backtest`，不出现 `validated`、买卖点、仓位或个股推荐。
- [x] 离线 pytest 全绿；测试不发起网络请求。
- [x] `python scripts/check-docs-contract.py --mode=full` 通过。
- [x] 一次运行同时产出 JSON 与人工可读 Markdown 报告；报告由 JSON 纯渲染，缺分渲染 `—` 而非 0，权重列合计不超过 100%。

## Completion Evidence（完成证据）

规划阶段：

- `openspec new change "add-qts04-sector-direction-skill"` 创建成功，schema 为 `spec-driven`。
- `openspec validate add-qts04-sector-direction-skill --strict` 返回 `Change 'add-qts04-sector-direction-skill' is valid`。
- `openspec status --change add-qts04-sector-direction-skill --json` 显示四个 artifact 均为 `done`，`planningComplete: true`。

实现阶段（2026-11-14）：

- 交付文件：
  - `.agents/skills/a-stock-qts04-sector-direction/SKILL.md`
  - `.agents/skills/a-stock-qts04-sector-direction/scripts/{scoring,cache,fuyao_client,sector_pipeline}.py`
  - `.agents/skills/a-stock-qts04-sector-direction/references/{data-contract,scoring-rules}.md`
  - `.agents/skills/a-stock-qts04-sector-direction/.gitignore`（忽略 `.cache/`）
  - `tests/test_a_stock_qts04_sector_direction_skill.py`（37 个用例）
  - `tests/fixtures/a_stock_qts04_sector_direction/{e2e,short-history,missing-benchmark,empty}.json`
- 门禁结果：
  - `.venv/bin/python -m pytest tests/test_a_stock_qts04_sector_direction_skill.py -q` → `37 passed`
  - `openspec validate add-qts04-sector-direction-skill --strict` → `valid`
  - `.venv/bin/python scripts/check-docs-contract.py --mode=full` → 通过（代码 5 / 文档 3 / plan 1）
  - `.venv/bin/python -m pytest tests -q` → `1739 passed, 101 skipped`（全量无回归）
  - `.venv/bin/python -m src.trading_system.cli rules coverage` → `documentedRules: 330, executableRules: 49`（未变）
  - `git diff --check` → 通过
  - `git status --porcelain` 不含 `trading-rules/`、`src/`、`coverage.yaml`
- 真实数据只读验证（fuyao 直连，未写库、未触发采集、未改部署）：
  - `index catalog --tag industry` → 320 个行业指数
  - `--as-of 2026-11-13 --breadth-universe 1` → `status=ok`，方向 `881274.TI 影视院线`，总分 100，五指标全 `ok`，四象限「真实流入」
  - `--as-of 2026-11-13 --breadth-universe 5` → `status=ok`，3 个方向（881274 影视院线 / 884275 生猪养殖 / 884006 水产养殖），44 次 provider 调用，缓存 `warm`
- 规则 ID 与 `trading-rules/coverage.yaml` 的 5 条 `QTS-04-01-*` 路径逐条核对一致，未改动该文件。
- 凭据来源调整（2026-11-14，用户指定）：改为读取 `deploy/truenas/deploy.env` 的 `FUYAO_API_KEY`，解析顺序 `FUYAO_API_KEY` 环境变量 → `MARKET_ENVIRONMENT_FUYAO_API_KEY` → 该文件 → `--env-file`；新增 `credentialSource` 输出字段（不含 key）。
  - `env -u FUYAO_API_KEY -u MARKET_ENVIRONMENT_FUYAO_API_KEY` 下运行 → `status=ok`、`credentialSource=file:FUYAO_API_KEY@deploy.env`、3 个方向、36 次调用。
  - 输出全文扫描不含 key 片段；该文件已被 `.gitignore` 覆盖。
  - 新增 8 个凭据解析用例（dotenv 语法、引号、行尾注释、优先级、缺失、git 忽略、不泄露同文件其他机密）。
- 人工可读报告（2026-11-14，用户追加要求）：新增 `scripts/report.py`，`render_markdown(result)` 由 JSON 纯渲染。
  - `--report PATH` 指定报告路径；给了 `--output` 未给 `--report` 时自动写同名 `.md`。
  - `--format {json,markdown,both}` 控制 stdout，默认 `json` 保持机器契约不变。
  - 修掉三处渲染缺陷：缺分渲染 `—` 而非 0、未计分指标权重渲染 `—`（否则权重列合计 120%）、短历史提示聚合为一句。
  - `insufficient` 时分节改为「结论 / 数据质量 / 口径」，不渲染空方向小节。
  - 测试 45 → 57 个用例。

## Remaining Gaps（剩余缺口）

- **STEP 2 之后未实现**：STEP 2 题材层（共同催化证据无来源）、STEP 3 资金层、STEP 4/5 角色与龙头、STEP 6/7 候选与模式、STEP 8 基本面（无财务数据源）、STEP 9 冲突仲裁、STEP 10 剧本输出。
- **生产 sector 500 未修**：`sectors/rankings`、`sectors/turnover`、`sectors/breadth` 在 k3s 仍返回 `AmbiguousParameter` 500。本 Skill 走 fuyao 直连绕过，但仓库自身板块页面与 v2 读取仍受影响，需另建修复项。
- **分位缓存依赖**：250 日滚动分位依赖本地缓存累积与 fuyao 历史窗口。实测 `--as-of 2026-11-13` 可得 ≥250 观测并输出 `ok`，但若缓存窗口不足会降级为 `reduced-confidence` 或 `insufficient`。
- 覆盖率闸门基于「当前成分股」，fuyao 不提供历史成分版本；回溯宽度会用到今天的成分造成轻微前视偏差，未量化。
- 四象限阈值（成交额增量 1.20、上涨覆盖 0.50）与确认/失效系数（+0.5%、-3%、量能 0.8）为显式经验默认值，`needs-backtest`。
- 未做样本外回测，任何分数都不能升级为 `validated`。

## Next Step（下一步）

1. 归档本 change：运行 `/openspec-archive-change add-qts04-sector-direction-skill`。
2. 用真实交易日复跑并观察：`--breadth-universe 30` 的完整宽度范围，确认请求量与耗时符合预期。
3. 评估 STEP 2 题材层的数据来源；共同催化证据目前没有结构化来源，需先定口径。
4. 另建修复项处理生产 `sectors/*` 500 缺陷，使仓库自身板块页面恢复可用。