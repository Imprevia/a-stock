## 0. 前置

- [x] 0.1 确认 `hithink-finance` 可用且凭据可解析；验证 `hithink-finance capabilities --format json` 返回 `ok=true`，且 STEP 1 的凭据解析顺序未被改动。
- [x] 0.2 记录基线：运行 `python -m pytest tests/test_a_stock_qts04_sector_direction_skill.py -q`，把通过数与 STEP 1 的 `reportId` 样例值记入 active plan，作为后续抽取回归的对照。
- [x] 0.3 确认 `docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md` 的阶段 1.5 已存在且 `Next Step` 指向本变更。

## 1. 抽取共享模块 qts04-core

- [x] 1.1 新建 `.agents/skills/qts04-core/scripts/`，把 STEP 1 的 `fuyao_client.py`、`cache.py`、`contract.py`、`predicate.py`、`check_report.py` 复制过去；验证 `python -c "import sys; sys.path.insert(0,'.agents/skills/qts04-core/scripts'); import fuyao_client, cache, contract, predicate, check_report"` 无 ImportError。
- [x] 1.2 在 STEP 1 的 `scripts/` 保留同名 shim 模块，转发到 core；验证 STEP 1 的既有 import 与 `--help` 全部照常工作。
- [x] 1.3 运行 STEP 1 全量用例，验证通过数与 0.2 记录一致。
- [x] 1.4 把 STEP 1 的 `sector_pipeline.py` / `report.py` 的 import 改为直接引用 core；再次运行用例，验证 `reportId` 与 0.2 记录逐字节一致。

## 2. 数据取数与缓存

- [x] 2.1 实现概念目录取数（`index catalog --tag cn_concept`）与缓存；验证重复调用只打一次网络，且 `catalogAsOf` 写入输出。
- [x] 2.2 实现概念快照取数（`index snapshot`，实测 390 个代码单次可用）；验证返回行数与目录条目数一致，缺行时记 `insufficient`。
- [x] 2.3 实现概念日线取数与缓存（复用 core 的 `history-batch`，每批 10 个代码）；验证 5 年窗口下 `observations` 与返回根数一致。
- [x] 2.4 实现涨停池取数与分页（`special limit-up-pool`，`--size 200` 翻页至 `pagination.total`）；验证当日行数与 `total` 一致，缺页时报 `degraded`。
- [x] 2.5 实现涨停统计与异动解读取数（`special limit-up-statistics`、`news anomaly-analysis`）；验证 `seal_rate`、`promotion_rate` 与涨停池行数交叉一致。
- [x] 2.6 实现成分股取数（`index constituents`，单代码一次）；验证成员数与概念快照该日成交额非零成员数偏差被记录为 `membershipGap`。
- [x] 2.7 实现目标日校验：未来日期、当日 15:10 前、非交易日一律拒绝；验证三种输入都返回 `insufficient` 并给出原因，不借相邻日期。

## 3. 题材单元与 lift 判定

- [x] 3.1 实现 `limit_up_reason` 的 token 拆分（含 `＋` 全角与 `+` 混用）与规整；验证构造样例拆分结果稳定、去重后顺序确定。
- [x] 3.2 实现成员共现：`概念成分股 ∩ 当日涨停池`，并只在交集内部统计共享 token（`count ≥ 2` 才计入）；验证单股 token 不计入共享。
- [x] 3.3 实现 lift 计算与硬闸门：`lift = 命中数 / (成员数 × 全市场涨停率)`，冻结分母口径进 `config`；验证 2026-11-13 复算得到短剧游戏 9.95、算力租赁 2.26、新能源汽车 1.33 附近的值。
- [x] 3.4 实现属性类 token 过滤：内置停用表 + 跨概念共现检测；验证「股份回购」「三季报增长」「预重整」被排除且不产生共享催化。
- [x] 3.5 实现概念指数价格与资金指标：成员涨跌比、涨幅中位数、`sectorAmount / mean(20)`、相对基准 `000001.SH` 的 5/20 日强度；验证指标缺失时 `status=insufficient` 且 `score=null`。

## 4. 催化标签与分级

- [x] 4.1 实现四级催化标签判据：`confirmed` / `partial` / `speculative` / `unknown`，并把主源不可枚举导致的 `confirmed = unavailable` 写入顶层声明；验证构造样例每档都能命中。
- [x] 4.2 实现分级：核心 / 扩散 / 事件 / 伪题材，闸门同时约束分数、lift、共享 token、梯队；验证任一项不满足即降级。
- [x] 4.3 实现 `noCoreTheme` 与原因枚举（lift 不足 / 共享 token 不足 / 梯队不足 / 分数不足）；验证弱题材日输出 `noCoreTheme=true` 且 `themes` 不含核心条目。
- [x] 4.4 实现每日 point-in-time 快照：把当日入选题材的成员与 token 写入 `.cache/qts04/point-in-time/{asOf}.json`；验证重复运行同一天产生同一文件内容。

## 5. JSON 合同与谓词

- [x] 5.1 实现顶层字段：`schemaVersion`、`step`、`reportId`、`asOf`、`config`、`input`、`status`、`quality`、`noCoreTheme`、`themes`、`unmappedTokens`、`disclaimer`；验证离线 fixture 运行后字段齐全。
- [x] 5.2 实现 `reportId`：对 `{schemaVersion, step, asOf, config, input, themes}` 取规范化 JSON 的 SHA-256 前 16 位，排除 `generatedAt` / `providerCalls` / `cacheState` / `credentialSource`；验证同日重跑同号、改 `liftThreshold` 换号。
- [x] 5.3 实现确认/失效谓词，复用 core 的扁平结构与求值器；验证谓词可由后续交易日行情求值，缺行情返回 `unknown`。
- [x] 5.4 实现 STEP 1 消费：校验上游 `schemaVersion` 与 `reportId`，计算 `direction.overlapJaccard`；验证缺失 `schemaVersion` 时拒绝消费并给出原因。
- [x] 5.5 验证独立运行与链式运行结构等价：除 `input` 与方向关联字段外，两份 JSON 的 schema 完全一致。

## 6. 报告与校验

- [x] 6.1 扩展 core 的 `check_report.py`：新增可选标签映射参数，未提供时行为与现在完全一致；验证 STEP 1 的现有校验用例全部通过。
- [x] 6.2 实现标签溯源检查：文章声明的分级与催化标签必须在 JSON 中存在对应值；验证「伪题材写成核心题材」与「`noCoreTheme` 日仍写核心题材」都被判失败。
- [x] 6.3 实现事实骨架 `theme_report.py` 渲染：缺失值渲染 `—`、`insufficient` 走三节结构、固定免责声明与 `needs-backtest`；验证骨架不含被禁措辞。
- [x] 6.4 编写 `SKILL.md`：前置条件、工作流、三种产物、输出约束、呈现流程（生成 → 校验 → PASS 才呈现 → FAIL 回退骨架）、不变量；验证内容与 spec 的八条要求逐条对应。
- [x] 6.5 编写 `references/data-contract.md` 与 `references/scoring-rules.md`：记录命令契约、字段、窗口、lift 公式、四级判据、停用表与降级语义。

## 7. 测试与 fixture

- [x] 7.1 建立 fixture：强题材日、弱题材日（`noCoreTheme`）、宽概念伪题材日、成分股缺失日、上游 STEP 1 缺失日；验证每个 fixture 都能离线跑通。
- [x] 7.2 新增 `tests/test_a_stock_qts04_theme_layer_skill.py`，覆盖 token 拆分、共享 token、lift 闸门、四级标签、分级、空结果、`reportId` 稳定性与降级路径；验证 `python -m pytest tests/test_a_stock_qts04_theme_layer_skill.py -q` 全绿。
- [x] 7.3 验证确定性：同一 fixture 连续两次运行，`reportId` 与 `themes` 顺序完全一致。
- [x] 7.4 验证无网络依赖：在无凭据环境下跑 fixture，确认不发起任何请求且输出 `insufficient` 而非异常。

## 8. 真实数据与回测边界

- [x] 8.1 用 2026-11-13 真实数据跑一次完整链路（生成 JSON → 写文章 → 校验 → 呈现），把 `reportId`、`noCoreTheme`、各题材 lift 与校验结果记入 active plan 的 Completion Evidence。
- [x] 8.2 选取至少 3 个弱题材日与 2 个强题材日验证分级稳定性；把结果与人工判断的偏差记入 Remaining Gaps。
- [x] 8.3 在约 1 年窗口上跑一次批量回放（只统计，不做收益回测），验证 `backtestGrade` 标注与实际可用窗口一致，样本不足时输出 `insufficient`。

## 9. 文档与门禁

- [x] 9.1 更新 `docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md` 的阶段 1.5 状态、Completion Evidence 与 Remaining Gaps；更新 `docs/exec-plans/active/_index.md` 的状态列。
- [x] 9.2 更新 `docs/repository-guide.md` 的代码-文档映射，加入两个新 Skill 路径。
- [x] 9.3 运行 `openspec validate add-qts04-theme-layer-skill --strict`、`python scripts/check-docs-contract.py --mode=full` 与 `git diff --check`，把结果记入 active plan。
- [x] 9.4 验证本轮未改动 `trading-rules/`、`src/`、`coverage.yaml`、生产集群与数据库：`git status --porcelain` 不含这些路径。
- [x] 9.5 归档前置检查：确认 `add-qts04-sector-report-contract` 的归档顺序不阻塞本变更（本变更为全新能力，不修改 `qts04-sector-direction-skill`）。
