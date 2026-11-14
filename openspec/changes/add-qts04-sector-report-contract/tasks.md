## 0. 前置

- [x] 0.1 归档 `add-qts04-sector-direction-skill`，使 `openspec/specs/qts04-sector-direction-skill/` 存在；验证 `openspec list --specs` 中出现该能力且 `openspec validate add-qts04-sector-report-contract --strict` 不再报告 archive 前目标缺失的 INFO。

## 1. JSON 接口化

- [x] 1.1 在 `sector_pipeline.py` 顶层新增 `schemaVersion`（`"1.0"`）、`reportId`、`config` 三个字段；验证离线 fixture 运行产出的 JSON 三字段齐全。
- [x] 1.2 实现 `config` 冻结块：权重、分位五档边界、最少观测数、覆盖率门槛、`breadthUniverse`、确认/失效系数；验证改动 `--breadth-universe` 后 `config.breadthUniverse` 跟随变化。
- [x] 1.3 实现 `reportId`：对 `{schemaVersion, asOf, benchmark, config, directions}` 取规范化 JSON 的 SHA-256 前 16 位，排除 `generatedAt`、`providerCalls`、`cacheState`、`credentialSource`；验证同一 fixture 连跑两次 `reportId` 相同。
- [x] 1.4 验证配置敏感：改变宽度范围或任一阈值后 `reportId` 改变；验证 `cacheState` 从 `cold` 变 `warm` 时 `reportId` 不变。

## 2. 条件谓词化

- [x] 2.1 新增 `predicate.py`，实现 `build_confirmation()` / `build_invalidation()`，返回 `{text, horizonDays, all:[{field, op, value, basis}]}`；验证结构符合设计 D2 的扁平约定。
- [x] 2.2 让 `text` 由同一组数值渲染，替换当前 `sector_pipeline.py` 中拼接中文串的代码；验证 `text` 与谓词数值一一对应（同一次运行内）。
- [x] 2.3 实现 `evaluate(predicate, bars)` 纯函数，按 `field`/`op`/`value`/`horizonDays` 求值，返回 `met`/`unmet`/`unknown`；验证对构造的行情逐条判定正确。
- [x] 2.4 验证 `evaluate` 在目标交易日缺失行情时返回 `unknown` 而非 `unmet`，且不抛异常。
- [x] 2.5 更新 `report.py` 与 SKILL.md 中引用 `confirmation` 为字符串的位置；验证全量测试通过。

## 3. 确定性校验器

- [x] 3.1 新增 `scripts/check_report.py`，实现数字 token 抽取（`%`、`×`、`亿`、`万`、`总分 N`），归一为 float 并在 JSON 数值中匹配，相对容差 1%；验证构造的匹配与不匹配样例都被正确判定。
- [x] 3.2 实现小整数白名单，使方向序号、观测数等不参与溯源；验证文章写「3 个方向」不误报。
- [x] 3.3 实现禁词检查（`买入`、`加仓`、`仓位`、`必涨`、`已验证`、`目标价`），输出命中位置；验证每个禁词都被拦截。
- [x] 3.4 实现必备项检查（免责声明、`needs-backtest`、数据状态、每方向置信度）；验证缺任一项时校验失败并指出缺失项。
- [x] 3.5 验证 `insufficient` 时不要求方向小节，但要求说明未产出原因。
- [x] 3.6 验证校验确定性：同一 JSON 与同一文章连续两次校验结论相同，且全程无网络调用。

## 4. 输出约束与降级

- [x] 4.1 改写 SKILL.md 输出段落：由固定模板改为四类约束（必备字段、必备警告、禁止措辞、篇幅上限）；验证段落不再规定固定小标题顺序。
- [x] 4.2 规定呈现流程：生成文章 → 运行校验 → PASS 才呈现；验证 SKILL.md 明确写出该顺序且要求贴出校验结果。
- [x] 4.3 实现降级路径：校验失败时呈现 `report.py` 事实骨架并标注「文章未通过校验，以下为事实骨架」；验证该路径在构造的失败样例上触发。
- [x] 4.4 把 `report.py` 的对外定位改为事实骨架，更新 `--format markdown` 的帮助文本；验证 `--help` 文案不再称其为对外主报告。

## 5. 文档与门禁

- [x] 5.1 更新 `references/data-contract.md`：新增 `schemaVersion`/`reportId`/`config`/谓词结构说明，替换「Markdown 报告由 report.py 纯渲染」的过时表述。
- [x] 5.2 更新 `references/scoring-rules.md`：记录确认/失效系数为冻结配置的一部分。
- [x] 5.3 调整既有 12 个 `report.py` 用例以匹配"事实骨架"定位，并补充谓词与校验器用例；验证 `pytest tests/test_a_stock_qts04_sector_direction_skill.py -q` 全绿。
- [x] 5.4 运行 `openspec validate add-qts04-sector-report-contract --strict`、`scripts/check-docs-contract.py --mode=full` 与 `git diff --check`，把结果记入 active plan。
- [x] 5.5 验证本轮未改动 `trading-rules/`、`src/`、`coverage.yaml`、生产集群与数据库：`git status --porcelain` 不含这些路径。
- [x] 5.6 用真实 fuyao 数据跑一次完整链路（生成 JSON → 写文章 → 校验 → 呈现），把 `reportId` 与校验结果记入 Completion Evidence。