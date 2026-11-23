## Context

现有底座已经具备三件可复用的事实：`qts04-core` 统一了 `hithink-finance` 调用、凭据隔离、日线缓存、`schemaVersion`/`reportId` 与文章校验；STEP 2 已把「涨停原因 + 异动解读」按股票代码归一到题材成员；STEP 1/2 都用「JSON 是唯一事实源、agent 只负责表达」的形态。见 `proposal.md` 的 Why，这里只记录影响实现选择的现状约束：

- 异动解读每条都带 `thscode`、`tagName`、`keyWords` 和含 `date=` 的 `url`，实测单日 773 条、1264 个关键词；关键词里混着事件（业绩预亏/股东减持/退市风险）、题材（存储芯片/商业航天）与市场语境（板块回调/特朗普搞事情）三类，不能一律当方向信号。
- `keyWords` 是厂商已经做过的结构化归类，比正文正则更干净，但词表未知且会长尾；正文里存在否定（终止减持）、不确定（拟减持）和跨分句否定。
- `news stock-timeline-list` 在 2026-11-13 实测返回 `FUYAO_5003`；`notice-detail` 只接受 opaque `seq`，没有公告列表枚举入口。个股层不能假设全量新闻可得。
- STEP 1 的 JSON 不保留成分股代码，STEP 2 的 `themes[].members.codes` 保留；板块层若链式消费 STEP 1，需要重新拉当前成分股并标 `pointInTime=false`。
- `trading-rules/coverage.yaml` 的 `documentedRules` 是硬计数（当前 330），新增量化规则必须同批更新计数与 `tests/test_trading_rule_platform.py`。
- 文章校验器已有数字溯源、禁词、必备项与标签溯源能力；本 Skill 需要新增极性/风险两组标签，但不应改变 STEP 1/2 的校验语义。

## Goals / Non-Goals

**Goals:**

- 一个管线同时产出板块/题材级极性与个股级风险，共用同一套证据归集与词表。
- 词表可审计、可版本化：任何规则调整都能通过 `lexicon.sha256` 与 `reportId` 追溯。
- 把「没查到」与「查到了没问题」在数据结构和文章措辞上彻底分开。
- 复用 `qts04-core` 的身份、校验与缓存契约，保持离线可测、无网络单测。

**Non-Goals:**

- 不预测收益、不做事件研究或收益回测；只做标签方向与人工标注准确率校准。
- 不枚举公告/政策主源，不实现 `notice-detail` 抓取，不把 AI 摘要升级为 `confirmed`。
- 不改变 STEP 1/2 的 JSON 合同、`reportId` 或分级逻辑。
- 不做盘中、不做自动排除/入选、不接调度、不写数据库。

## Decisions

### D1. 新建独立 Skill，而不是给 STEP 2 加字段

选独立 `a-stock-qts04-news-catalyst`。理由：极性与风险跨 STEP 2 和 STEP 8 两个消费方；给 `themes[]` 加 `catalyst.polarity` 会让 STEP 2 的 `reportId` 变号、fixture 与校验器全部返工，而且装不下个股层。备选「扩展现有题材层」被否。

### D2. 分析单元与成员来源

- 题材单元：直接消费 STEP 2 的 `themes[].members.codes`，不重新判定题材真伪。
- 板块单元：消费 STEP 1 的 `directions[].thscode`，用 `index constituents` 拉当前成分股；输出 `pointInTime=false` 与 `membershipAsOf`。
- 个股单元：显式 `--codes`，或由上游题材成员与异动解读中出现且属于上述单元的代码取并集；默认不扫全市场。
- 归属只认 `thscode` 精确相等，沿用 STEP 2 的 6 位裸码补 `.SH`/`.SZ` 规则（`marketId=17/33`）。

备选「按板块名/关键词映射」被否：这正是 STEP 2 已经证伪的名称匹配路径。

### D3. 词表结构：事件 / 题材 / 语境三分

`references/lexicon.v1.json` 每条规则：

```json
{"id":"neg.hard.delisting","ruleId":"QTS-04-09-04","class":"event",
 "eventType":"退市风险","polarity":"negative","severity":"hard","weight":1.0,
 "patterns":["退市风险警示","终止上市","面值退市","市值退市"],
 "negation":"drop","uncertaintySensitive":true}
```

- `class=event` 才参与极性/风险；`topic`（存储芯片、商业航天）只用于展示与人工核对；`context`（板块回调、特朗普搞事情、此前涨幅较大）只入证据列表、不参与打分。实测关键词里三类混杂，不分开会把「板块普跌」误判成个股利空。
- `keyWords` 与正文正则同时匹配：关键词命中权重 1.0，正文命中 0.8（正文噪声更大）。
- 长尾未匹配关键词写入 `unmatchedKeywords`（按频次降序，最多 50 条），作为下一版词表的输入，不参与打分。
- 词表 JSON 而非 YAML：与仓库现有 JSON 合同一致，零解析依赖；规则按 `id` 排序后计算 sha256，保证哈希稳定。

### D4. 否定与不确定的就近作用域

- 否定词表：`不/未/无/否认/并非/终止/取消/未能/不及预期/低于预期`。
- 作用域：命中词左侧 8 个字符内，且中间不得出现 `。；;！!`；跨分句不生效。
- `negation` 三态：`drop` 直接取消（v1 默认）、`downgrade` 降一级、`flip` 反转极性；硬风险（如「退市风险」）用 `drop`，因为「不存在退市风险」既不是利空也不是利好。正文明确否定时，同一规则的关键词命中也置为无效，避免厂商关键词「减持」压过「终止减持」的正文。
- 不确定词表：`拟/计划/预计/有望/或将/传闻/媒体报道/据悉`，命中后严重度降一级、可信度上限 `speculative`。
- 已实施/完成类表述（`已/完成/实施完毕/收到`）可抵消不确定降级，但不得把可信度提到 `partial` 以上。

### D5. 极性打分与阈值

- 单条证据权重：`baseWeight × sourceFactor × recencyDecay × certaintyFactor`；`sourceFactor` 关键词 1.0、正文 0.8；`recencyDecay = 0.5 ** (daysAgo / halfLife)`，`halfLife=3` 交易日；`certaintyFactor` partial 1.0、speculative 0.6、unknown 0.3。
- 单元汇总：`posShare = pos/(pos+neg)`、`negShare = neg/(pos+neg)`；判定顺序为
  1. `posShare ≥ 0.30 且 negShare ≥ 0.30` → `mixed`
  2. `net ≥ +0.25` → `positive`
  3. `net ≤ -0.25` → `negative`
  4. `evidenceCount ≥ 1` → `neutral`
  5. 否则 → `unknown`
- 置信度：`high` 需 ≥3 条证据、≥2 只成员、主方向份额 ≥0.70 且无相反方向的 hard/medium 事件；`medium` 需 ≥2 条证据；`low` 为 1 条；未过闸门为 `insufficient`。
- 分数只表示文本方向强度，不是概率、不是预期收益；JSON 与文章都必须带这句限定。

备选「按条数投票」被否：一条退市风险公告和一条回购公告等权，会把硬风险稀释掉。

### D6. 个股风险分级与优先级

- 先判 hard 负向事件 → `block`；否则 medium → `downgrade`；否则 weak → `watch`。
- 正向事件不参与降级，只在 `events[]` 展示；`block` 不被同一窗口的正向事件抵消。
- 无负向但 `evidenceCount ≥ 1` → `none`；`evidenceCount = 0` 或来源不可用 → `uncovered`。
- 语义不确定事件（控制权变更、重组、股权转让）标 `ambiguous`，不计正负、不改变风险等级，只列出并提示需人工判断。
- 风险等级用完整窗口、不做时效衰减；极性分数才衰减。30 天前的退市风险仍然 block。

### D7. 数据获取、探测与降级

- 主源：`news anomaly-analysis --begin-date --end-date`，一次调用覆盖回看窗口（默认 10 个自然日，可配到 30）；日期从 `url` 的 `date=` 解析，缺失时用窗口末日并标 `dateInferred=true`。
- 辅源：`special limit-up-pool --date` 的 `reason` 文本，只覆盖涨停股。
- 扩展源：`news stock-timeline-list` 仅在需要补覆盖的股票上按需探测，默认最多 10 只；首次遇到 `FUYAO_5003`/`FUYAO_1002` 即停止本轮探测并记 `unavailable`，避免无界重试与 429。
- `notice-detail` 不进入 v1 调用路径（无列表枚举入口）；`qts04-core` 也不新增该方法，避免死代码。
- 缓存：`.cache/qts04/news/{asOf}/anomaly.json`、`limit-up.json`、`timeline/{code}.json`，全部 git 忽略；`--refresh` 只禁用读取，不删缓存。
- 状态矩阵：主源与涨停池均失败 → `insufficient`；扩展源不可用或部分单元未过闸门 → `degraded`；全部通过 → `ok`。

### D8. 校验器组合而非改写

- `news_check_report.py` 先调用 `qts04.check.validate`（数字溯源、禁词、必备项、免责声明），再叠加本地三项：极性标签溯源、风险标签溯源、覆盖措辞检查（`uncovered` 必须写「未覆盖」，`unknown` 不得写「中性」）。
- 不修改 `qts04/check.py` 的默认标签表，避免 STEP 1/2 的既有校验行为变化；本地标签表在 `news_check_report.py` 内定义。
- `FAIL` 时回退 `news_report.render_fallback` 的事实骨架，与 STEP 1/2 一致。

### D9. 文档先行与规则注册

- 先写 `搭建交易系统-量化版/04-板块、题材与个股筛选/09.消息面极性规则.md`（QTS-04-09-01~05），再写代码；文档中的阈值与词表版本必须与代码常量一致。
- `trading-rules/coverage.yaml` 增加 5 条 `documented-only`（与 QTS-04-01/02 同口径），`documentedRules` 330→335，并同步 `tests/test_trading_rule_platform.py` 的断言。
- 新增 `docs/exec-plans/active/add-qts04-news-catalyst-polarity.md`，含 Stage/Status/Acceptance/Completion Evidence/Remaining Gaps/Next Step，并在 `_index.md` 登记。

### D10. 测试策略

- 纯函数（词表加载、否定作用域、打分、分级）与管线（fixture 端到端）分离；fixture 覆盖七类：利好、硬利空、多空交织、否定翻转、未覆盖、空结果、`FUYAO_5003` 降级。
- 必须断言 fixture 模式不发起网络：monkeypatch `FuyaoClient.call` 抛错。
- 必须断言同日重跑 `reportId` 稳定、词表变更后 `reportId` 变化、`uncovered ≠ none`、硬利空不被利好抵消。
- 覆盖计数断言与量化文档规则表同批修改，避免文档/代码漂移。

## Risks / Trade-offs

- **词表准确率未测** → 先做人工标注 200 条异动解读的 precision/recall 校准；校准前 `needs-backtest`，`block` 只作提示，不自动排除。
- **AI 摘要噪声与归因错误** → 只按代码归属、同文本去重、可信度封顶 `partial`；每篇文章必须给出证据条数与覆盖。
- **`stock-timeline-list` 持续不可用** → 个股覆盖只到异动池；`quality.sources.stockTimeline` 显式 `unavailable`，整体 `degraded`，绝不把未覆盖写成 `none`。
- **板块成分股只有当前快照** → `pointInTime=false`，板块极性不做历史回测；需要历史时先建 point-in-time 快照。
- **关键词长尾与口径漂移** → `unmatchedKeywords` 台账 + 词表哈希 + 版本号；每次词表变更必须跑回归 fixture。
- **否定/反讽误判** → 就近作用域 + 跨分句拒绝 + 人工标注样本中的否定类专项用例。
- **覆盖面成本** → 只对上游单元成员与显式代码取数；不做全市场逐股 timeline，默认探测上限 10 只。
- **过度解读为交易信号** → 禁词、标签溯源、`needs-backtest` 与免责声明三重约束。

## Migration Plan

- 无运行时迁移：新 Skill 只读 `hithink-finance`，不写数据库、不改 STEP 1/2 输出、不部署。
- 上线顺序：量化文档 09 → coverage.yaml 与计数断言 → 词表与纯函数 → 管线与 fixture → 校验器与报告 → repository-guide/plan/status。
- 回滚：删除 `.agents/skills/a-stock-qts04-news-catalyst/` 与测试/fixture，回退 coverage.yaml 计数与文档索引；不影响现有 STEP 1/2。

## Open Questions

- 个股层是否需要在 v2 接入 `news flash-list` 做全市场补覆盖？当前判断是暂不接入（无逐股过滤、噪声高），留待词表校准后再评估。
- `block` 在 STEP 8 的消费方式（硬排除还是人工复核）需在 STEP 8 落地时由主控决定；本 Skill 只输出等级与证据，不替下游做排除决策。