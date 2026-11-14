# QTS-04 STEP 1 报告契约化（add-qts04-sector-report-contract）

> OpenSpec 变更：`openspec/changes/add-qts04-sector-report-contract/`（proposal / design / spec delta / tasks）。
> 上游：`docs/exec-plans/active/add-qts04-sector-direction-skill.md`（已完成并归档）。
> 范围：只改 `.agents/skills/a-stock-qts04-sector-direction/` 与其测试；不动 `trading-rules/`、`src/`、`coverage.yaml`、数据库、生产集群。

---

## Stage（阶段）

- 当前阶段：**完成（Stage 5 / 5）** — JSON 接口化、条件谓词化、确定性校验器、输出约束与降级、文档与门禁全部落地。
- 阶段序列：选股流水线 STEP 1 板块层（已完成）→ **本轮 STEP 1 报告契约** → STEP 2 题材层（未启动）。

## Status（状态）

`complete` — 26/26 任务完成；OpenSpec `validate --strict` 通过，离线测试与真实 fuyao 数据链路均通过，剩余项均为设计层面的 Non-Goals。

## 背景与决策

STEP 1 已能产出方向，但 JSON 缺稳定接口标识与可机器求值的条件，人读报告只能由脚本按死模板渲染，STEP 2 无法直接消费。本轮把报告契约固定下来：

| 决策 | 结论 | 依据 |
|---|---|---|
| 接口标识 | 顶层新增 `schemaVersion`（`1.0`）、`reportId`、`config` | OpenSpec 要求「报告可标识且配置被冻结」 |
| 条件形态 | `confirmation` / `invalidation` 改为 `{text, horizonDays, all:[{field, op, value, basis}]}` | 可机器求值，散文由同一组数值渲染 |
| 身份计算 | 对 `{schemaVersion, asOf, benchmark, config, directions}` 的规范化 JSON 取 SHA-256 前 16 位 | 排除 `generatedAt` / `providerCalls` / `cacheState` / `credentialSource` |
| 人工报告 | agent 按 SKILL.md 约束撰写，`check_report.py` PASS 后才呈现 | 模板化报告用户会停止阅读；纯脚本报告无法解释 |
| 兜底 | `report.py` 降级为事实骨架；`render_fallback()` 生成带标注的降级文本 | 宁可给干巴巴但正确的骨架，也不因措辞不给结论 |
| 不实现 | `verify` / `ledger` / `stats` 回测闭环、回测主口径 | design Non-Goals；谓词带 `horizonDays` 已足够支持两种口径 |

## Acceptance（验收）

- [x] 0.1 前置变更 `add-qts04-sector-direction-skill` 已归档，`openspec/specs/qts04-sector-direction-skill/spec.md` 存在。
- [x] 1.1 JSON 顶层含 `schemaVersion` / `reportId` / `config`，fixture 运行三字段齐全。
- [x] 1.2 `config` 冻结权重、分位五档边界、最少观测、覆盖率门槛、`breadthUniverse`、确认/失效系数；`--breadth-universe` 变化时 `config.breadthUniverse` 跟随。
- [x] 1.3 `reportId` 对固定子集取 SHA-256 前 16 位；同一 fixture 连跑两次相同。
- [x] 1.4 配置或阈值变化改变 `reportId`；`cacheState` 冷热变化不改变 `reportId`（fixture 单测 + 真实数据 warm 复跑双重验证）。
- [x] 2.1 `predicate.py` 提供 `build_confirmation()` / `build_invalidation()`，结构符合设计 D2 扁平约定。
- [x] 2.2 `text` 与谓词数值同源生成，管线不再手工拼接中文串。
- [x] 2.3 `evaluate(predicate, bars)` 纯函数返回 `met` / `unmet` / `unknown`。
- [x] 2.4 目标交易日缺行情时 `evaluate` 返回 `unknown` 且不抛异常。
- [x] 2.5 `report.py` 与 SKILL.md 中按字符串引用条件的位置全部更新，全量测试通过。
- [x] 3.1 `check_report.py` 抽取 `%` / `×` / `亿` / `万` / `总分 N` 数字 token，按展示精度与 1% 相对容差溯源。
- [x] 3.2 小整数白名单生效：「3 个方向」不误报。
- [x] 3.3 六个禁词逐个拦截并给出行列位置。
- [x] 3.4 必备项（免责声明 / `needs-backtest` / 数据状态 / 每方向置信度）缺失即失败并指明缺失项。
- [x] 3.5 `insufficient` 时不要求方向小节，但要求说明未产出原因。
- [x] 3.6 同一 JSON 与文章重复校验结论一致，全程无网络（socket 打桩验证）。
- [x] 4.1 SKILL.md 输出段落改为四类约束，不再规定固定小标题顺序。
- [x] 4.2 SKILL.md 明确「生成文章 → 运行校验 → PASS 才呈现」且要求贴出校验结果。
- [x] 4.3 校验失败降级路径可触发：`report.render_fallback()` 首行输出「文章未通过校验，以下为事实骨架」并附失败项。
- [x] 4.4 `report.py` 对外定位改为事实骨架，`--format markdown` / `--report` 帮助文本同步。
- [x] 5.1 `references/data-contract.md` 更新接口字段、谓词结构与产物分工。
- [x] 5.2 `references/scoring-rules.md` 记录确认/失效系数属于冻结配置。
- [x] 5.3 既有 `report.py` 用例改为事实骨架定位，并补谓词与校验器用例；skill 测试全绿。
- [x] 5.4 `openspec validate --strict`、`check-docs-contract.py --mode=full`、`git diff --check` 通过并记入 Completion Evidence。
- [x] 5.5 `git status --porcelain` 不含 `trading-rules/`、`src/`、`coverage.yaml`、生产集群与数据库变更。
- [x] 5.6 用真实 fuyao 数据跑通「生成 JSON → 写文章 → 校验 → 呈现」，记录 `reportId` 与校验结果。

## Completion Evidence（完成证据）

### 交付文件（2026-11-14）

- 新增：`.agents/skills/a-stock-qts04-sector-direction/scripts/contract.py`（`SCHEMA_VERSION` / `build_config` / `compute_report_id` / `attach_interface` / `require_schema_version`）。
- 新增：`.agents/skills/a-stock-qts04-sector-direction/scripts/predicate.py`（`build_confirmation` / `build_invalidation` / `normalize_bars` / `evaluate`，含 1.005、0.97、0.8 系数常量）。
- 新增：`.agents/skills/a-stock-qts04-sector-direction/scripts/check_report.py`（数字溯源 / 禁用措辞 / 必备项；退出码 0/1/2）。
- 修改：`sector_pipeline.py`（接口字段、谓词接线、`pool_state`、骨架帮助文本）、`report.py`（事实骨架定位、`render_fallback`、谓词文本渲染）、`scoring.py`（池位/置信度/窗口常量）。
- 修改：`SKILL.md`（三种产物、四类输出约束、呈现流程、JSON 合同、不变量）、`references/data-contract.md`、`references/scoring-rules.md`。
- 修改：`docs/repository-guide.md`、`docs/status.md`、`openspec/.../{proposal,design,tasks}.md`（谓词结构 `horizonDays` + `basis` 对齐）。
- 测试：`tests/test_a_stock_qts04_sector_direction_skill.py` 由 57 增至 90 个用例（既有 report 用例改为骨架定位，新增 contract / predicate / checker / fallback 用例）。

### 门禁结果

- `.venv/bin/python -m pytest tests/test_a_stock_qts04_sector_direction_skill.py -q` → `90 passed`。
- `.venv/bin/python -m pytest tests -q` → `1791 passed, 101 skipped, 1 warning in 310.02s`（无回归）。
- `openspec validate add-qts04-sector-report-contract --strict` → `Change 'add-qts04-sector-report-contract' is valid`；`status --json` 显示 `isComplete: true`。
- `.venv/bin/python scripts/check-docs-contract.py --mode=full` → `docs-contract: 通过（代码 13 / 文档 7 / plan 3）`。
- `git diff --check` → 通过。
- `git status --porcelain` → 仅 `.agents/skills/...`、`tests/...`、`docs/repository-guide.md`、`docs/status.md`、active plan 与 OpenSpec 产物；不含 `trading-rules/`、`src/`、`coverage.yaml`。
- 无 lint 工具接入本仓库 Python Skill；以 `python -m py_compile` 覆盖六个脚本，编译通过。

### 真实数据链路（fuyao 直连，只读，未写库/未触发采集/未改部署）

命令：

```bash
.venv/bin/python .agents/skills/a-stock-qts04-sector-direction/scripts/sector_pipeline.py \
  --as-of 2026-11-13 --breadth-universe 5 --output /tmp/qts04-real-20261113.json
```

- 首次运行上游超时（`UPSTREAM_NETWORK_FAILURE`，exit=4），管线按不变量输出 `insufficient` 并保留原因，未用他日数据顶替。重试成功。
- 成功结果：`status=ok`、`source=fuyao`、`cacheState=warm`、`providerCalls=46`、`credentialSource=file:FUYAO_API_KEY@deploy.env`、`industries=320/320`、`warnings=[]`。
- `reportId = c037ea4bb76bfe31`；3 个方向：`881274.TI 影视院线`（100.0，high，重点池，真实流入）、`884275.TI 生猪养殖`（100.0，high，重点池，真实流入）、`884006.TI 水产养殖`（96.25，high，重点池，短线脉冲）。
- 身份稳定性：同命令 warm 复跑 `providerCalls` 46 → 38，`reportId` 仍为 `c037ea4bb76bfe31`。
- 谓词求值：对 `881274.TI` 的确认谓词传入空 `bars` → `unknown`（目标交易日尚无行情，不误判 `unmet`）。
- 文章校验：按 SKILL.md 约束撰写 `/tmp/qts04-real-article.md` 后运行

  ```bash
  .venv/bin/python .agents/skills/a-stock-qts04-sector-direction/scripts/check_report.py \
    --result /tmp/qts04-real-20261113.json --article /tmp/qts04-real-article.md
  ```

  → `status: PASS`，四项检查全部 `pass`，`numbersChecked: 34`，`issues: []`，退出码 0，回显 `reportId c037ea4bb76bfe31`。
- 反向验证：同一次真实 JSON 加写「宽度 73.21%」后校验返回 FAIL 并给出行列，`report.render_fallback()` 触发降级文案（离线用例覆盖）。

## Remaining Gaps（剩余缺口）

- 回测执行（`verify` / `ledger` / `stats`）未实现；本变更只让报告具备被回测的条件。
- 回测主口径（次日超额 vs 5 日累计超额）仍未定。
- `evaluate` 的 `pctChange` 以传入序列的前一根 bar 为基准，5 日累计口径需调用方自行截取窗口并多次求值。
- 文章篇幅上限（方向 ≤5 行 / 全文 ≤40 行）是经验值，需按实际阅读体验调整。
- 数字溯源只做「值存在性」比对：极小概率把真实数值误判为越界（如文章写「覆盖 50%」恰好命中 `broadAdvanceRatio`），这是 design 已接受的假阴性风险。
- 覆盖率闸门基于当前成分股，历史回溯有轻微前视偏差（沿用上一轮遗留）。

## Next Step（下一步）

1. 运行 `/openspec-archive-change add-qts04-sector-report-contract` 归档本 change，并把 `_index.md` 状态改为 completed。
2. 启动 STEP 2 题材层时，直接按 `schemaVersion: 1.0` + `reportId` 消费本 Skill 的 JSON，不再解析人类可读文本。
3. 后续若出现「或」条件或分组谓词，新增 `any` / `groups` 字段并升 `schemaVersion`，不要扩展当前扁平 `all` 语义。
4. 回测执行阶段优先复用 `predicate.evaluate()`，并在其上做批量窗口求值。