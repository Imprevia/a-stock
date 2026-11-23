## 1. 文档与规则注册（先行）

- [x] 1.1 新增 `搭建交易系统-量化版/04-板块、题材与个股筛选/09.消息面极性规则.md`，写入 `QTS-04-09-01`~`-05` 五条规则（证据归属、极性判定、时效与强度、个股硬否决、覆盖率闸门），含目标与输出、输入与数据口径、规则表、数据缺失与异常处理、校准与验证、输出接口；验证：五条 ID 均在文件中出现，且阈值与状态 `needs-backtest` 与 design.md 一致。
- [x] 1.2 更新 `搭建交易系统-量化版/04-板块、题材与个股筛选/0-板块、题材与个股筛选.md`，在章节清单中加入 `09.消息面极性规则.md` 的相对链接与一句话定位；验证：链接目标文件存在，索引无重复编号。
- [x] 1.3 在 `trading-rules/coverage.yaml` 增加 5 条 `documented-only` 条目（`documentRef` 指向 09 文档），把 `documentedRules` 由 330 改为 335，并同步 `tests/test_trading_rule_platform.py` 的期望值；验证：`.venv/bin/python -m src.trading_system.cli rules coverage` 通过，`.venv/bin/python -m pytest tests/test_trading_rule_platform.py -q` 通过。
- [x] 1.4 新增 `docs/exec-plans/active/add-qts04-news-catalyst-polarity.md`（含 Stage/Status/Acceptance/Completion Evidence/Remaining Gaps/Next Step 六个字段），并在 `docs/exec-plans/active/_index.md` 登记；验证：`python scripts/check-docs-contract.py --mode=full` 的 Gate 4 通过。

## 2. 共享底座扩展

- [x] 2.1 在 `.agents/skills/qts04-core/scripts/qts04/client.py` 增加区间版 `anomaly_analysis(start, end)`，单日方法改为委托；保持 `thscode/tagName/keyWords/content/url` 归一化与 6 位裸码补后缀逻辑；验证：新增单测用 fake runner 断言 argv 含 `--begin-date`/`--end-date`，且单日调用只发一次请求。
- [x] 2.2 增加 `stock_timeline(thscode, size, max_pages)`，按响应 `offset`/`has_more` 有界翻页，`FUYAO_5003`/`FUYAO_1002` 映射为 `FuyaoInsufficient` 并保留原始错误码；验证：单测覆盖首页、翻页、提前结束、数据源不可用四条路径；解析字段以 `hithink-finance schema news.stock-timeline-list --format json` 与实际响应为准，未知字段透传到 `raw`。
- [x] 2.3 确认 v1 调用路径不包含 `notice-detail`（无列表枚举入口），且未引入死代码；验证：`grep -R "notice-detail" .agents/skills/a-stock-qts04-news-catalyst .agents/skills/qts04-core/scripts/qts04` 无命中。

## 3. 词表与纯函数

- [x] 3.1 新增 `.agents/skills/a-stock-qts04-news-catalyst/references/lexicon.v1.json`：每条规则含 `id`、`ruleId`（取值必须属于 `QTS-04-09-01`~`-05`）、`class`（`event`/`topic`/`context`）、`eventType`、`polarity`、`severity`、`weight`、`patterns`、`negation`（`drop`/`downgrade`/`flip`）、`uncertaintySensitive`；事件规则不少于 80 条，覆盖退市/立案/财务造假/减持/解禁/预亏/商誉减值/中标/预增/回购/增持/涨价/控制权变更等族；验证：加载器按 `id` 排序计算 sha256，重复加载哈希稳定，非法 `ruleId` 直接报错。
- [x] 3.2 实现 `news.py` 的否定与不确定作用域：否定词只在命中词左侧 8 个字符内且中间无 `。；;！!` 时生效；`negation=drop` 直接取消、`downgrade` 只降级、`flip` 才翻转；不确定词使严重度降一级且可信度封顶 `speculative`；验证：单测覆盖「终止减持计划」「未实施减持」「拟减持」「不存在退市风险」「跨分句否定不生效」五类。
- [x] 3.3 实现极性打分与五档判定（`mixed` 双份额 ≥0.30、`positive`/`negative` 净分 ±0.25、`neutral` 有证据无方向、`unknown` 无证据或未过闸门），以及个股风险优先级（hard→`block`、medium→`downgrade`、weak→`watch`、有证据无负向→`none`、无证据→`uncovered`）；验证：单测覆盖「硬利空+利好仍 block」「利好+减持→mixed 且 downgrade」「澄清公告→neutral」「无证据→unknown」「未覆盖≠none」「单元仅 1 条证据→unknown」。
- [x] 3.4 实现 `keyWords` 三分类路由：`event` 参与打分、`topic`/`context` 只入证据列表、未匹配关键词按频次写入 `unmatchedKeywords`（最多 50 条）；验证：用含「业绩预亏/存储芯片/板块回调/未知新词」的样本断言只有第一类改变分数，第四类进入台账。

## 4. 管线与数据

- [x] 4.1 实现目标日校验与证据归一：未来日期、当日 15:10 前（`Asia/Shanghai`）、非交易日一律 `insufficient`；异动日期从 `url` 的 `date=` 解析，缺失时用窗口末日并标 `dateInferred=true`；同文本按规范化内容去重；验证：单测覆盖四类拒绝、日期推断与去重。
- [x] 4.2 实现单元装配与归属：STEP 2 用 `themes[].members.codes`，STEP 1 用 `directions[].thscode` 并拉当前成分股（`pointInTime=false`），个股用 `--codes` 或上游成员并集；只按 `thscode` 精确归属；验证：单测覆盖两种上游、上游 `schemaVersion` 不兼容拒绝、成员外证据不计分。
- [x] 4.3 实现状态矩阵与 `quality.sources`：主源/涨停池均失败→`insufficient`；`stock-timeline` 不可用或部分单元未过闸门→`degraded`；全部通过→`ok`；验证：fixture 覆盖 `FUYAO_5003` 降级、单源失败、全通过三种状态。
- [x] 4.4 组装 JSON 合同：`schemaVersion`/`step`/`ruleVersion`/`reportId`/`asOf`/`config`（窗口、阈值、半衰期、闸门、词表哈希）/`input`/`status`/`quality`/`units`/`stocks`/`lexicon`/`disclaimer`/`calibration`；验证：同日同输入重跑 `reportId` 稳定，修改词表后 `reportId` 变化，排序稳定。

## 5. 报告与机械校验

- [x] 5.1 实现 `news_report.py` 事实骨架与 `render_fallback`：输出极性、风险、证据条数、覆盖缺口与免责声明，标签只取 JSON 值；验证：fixture 渲染快照断言含「未覆盖」且不含「无利空」。
- [x] 5.2 实现 `news_check_report.py`：先调用 `qts04.check.validate`（数字溯源、禁词、必备项、免责声明），再叠加极性/风险标签溯源与覆盖措辞检查（`uncovered` 必须写「未覆盖」，`unknown` 不得写「中性」）；验证：PASS/FAIL 各覆盖「unknown 写成中性」「uncovered 写成无利空」「已证实」「买入」四类反例。
- [x] 5.3 编写 `SKILL.md` 与 `references/data-contract.md`、`references/scoring-rules.md`，说明命令、窗口、降级、五档标签、词表版本与按需参考路由；验证：新增「文档字段与输出一致」测试（`test_documented_keys_match_output`），并检查 frontmatter 的 `name`/`description` 不含交易指令。

## 6. Fixture 与端到端

- [x] 6.1 新增 `tests/fixtures/a_stock_qts04_news_catalyst/` 七类样本：利好、硬利空、多空交织、否定翻转、未覆盖、空结果、`FUYAO_5003` 降级；验证：每个 fixture 可被管线读取并产出结构化 JSON。
- [x] 6.2 新增 `tests/test_a_stock_qts04_news_catalyst_skill.py` 端到端用例：`ok`/`degraded`/`insufficient`、`reportId` 稳定性、词表变更换号、CLI 退出码 0/1/2；验证：`monkeypatch` 让 `FuyaoClient.call` 抛错，断言 fixture 模式零网络调用。
- [x] 6.3 覆盖 `--codes`、`--step1`、`--step2`、`--refresh`、`--cache-dir` 五条 CLI 参数路径；验证：单测逐个调用并断言输出字段与缓存行为。

## 7. 文档收尾与门禁

- [x] 7.1 更新 `docs/repository-guide.md`（新增 Skill 的 `scripts/`、`references/`、测试与 fixture 映射行）、`docs/status.md`、`docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md`（STEP 2.5 定位、数据可得性台账补 `stock-timeline` 不可用、阶段证据）；验证：`python -m src.trading_system.cli docs sync-check` 通过。
- [x] 7.2 运行 `python scripts/check-docs-contract.py --mode=full`、`.venv/bin/python -m pytest tests/test_a_stock_qts04_news_catalyst_skill.py tests/test_trading_rule_platform.py -q`、`.venv/bin/python -m src.trading_system.cli rules validate` 与 `rules coverage`；验证：四项全部通过，输出摘要记入 active plan 的 Completion Evidence。
- [x] 7.3 回填 active plan 的 `Status`/`Completion Evidence`/`Remaining Gaps`/`Next Step`，并把 `docs/exec-plans/active/_index.md` 的状态列更新；验证：Gate 4 六字段齐全且 Next Step 非空。
- [x] 7.4 运行 `openspec validate add-qts04-news-catalyst-polarity --strict`；验证：无错误。归档由评审通过后单独执行 `openspec-archive-change`，不包含在本变更的实现步骤内。
