# Design: 指数、趋势位置和成交额补全与第四部分呈现重做

## Context

第 01 节现状：`src/market_environment/calculations.py` 已实现均线结构分类（`classify_trend`）、六类组合匹配（`classify_index_combination`）与量价状态分类；`service.py` 汇总同步性三态与市场层四问（`_combination_overview`）；前端第 01 页以三个独立面板呈现第四部分。约束：

- 量化版文档是规则的人读说明层，`trading-rules/` 是机器事实源；规则变更必须双侧同步并更新 coverage。
- 已有规则 ID 不得重排；第 01 章可执行规则当前 46 条，全部为 `metric.band`/`aggregate.rules` evaluator。
- 指数 K 线经 mootdx → 百度 → 新浪 → 东方财富 → 腾讯降级链获取，默认 `limit=160`（部分 provider 强制 `max(limit, 160)`）。
- 指数历史快照落 SQLite（盘后预计算 materialized aggregate），同日期成功结果保留不复用其他日期。
- 看板原则：未命中不兜底分类；风险输入缺失保留风险提示。

## Goals / Non-Goals

**Goals:**

- 同步性输出五态，可区分权重护盘与成长占优。
- `QTS-01-01-06/07/08` 三条规则按完整 executable 待遇登记（文档 + YAML + coverage + evaluator + 测试），且不改变任何既有评分组输出。
- MA20 斜率 250 日分位、量价推进效率 250 日分位、五指数均线多头比例在 API 与页面可见；provider 深度支持 250 日窗口。
- 第 01 页第四部分重做为"四问结论条 + 五指数 × 六组合矩阵 + 行展开证据"；页面同一位置输出盘后收束句。
- 指标 null 附带原因分层。

**Non-Goals:**

- 不改动六类组合的阈值与匹配优先级（维持现状与既有决策映射）。
- 不把新规则加入 `QTS-01-00-01` 评分组、不调整任何既有权重（无回测证据不改评分语义）。
- 不回填历史 SQLite 快照的 K 线深度；不新增第三方依赖；不做实时盘中推送。
- 不实现第 02 章及以后的规则。

## Decisions

### D1: 新规则 ID 分配与登记方式（append-only，不入组）

`QTS-01-01-06`（指数同步性五态）、`QTS-01-01-07`（20 日区间位置）、`QTS-01-01-08`（5 日成交额比值）追加在第 01 篇规则表末尾；YAML 中三者均为 `metric.band` evaluator、`status: defined`、阈值 `provenance: empirical-initial`（07/08 的区间分档为 fixed），且不加入任何 `aggregate.rules` 的 members。`QTS-01-00-01` 保持五成员原权重。

- 备选：入组并重分配权重——被否。会重算 golden trace、改变评分语义，且当前没有任何回测证据支持新权重；与量化文档"看板组合映射复用输入、不新增评分规则"的既有决策冲突。
- 新增 evaluator 输入字段：`index.sync_pattern`（五态编码 0–100 分档映射，见 D2）、`index.range_position_20`、`market.turnover_ratio_5`，进 snapshot schema 与固定快照 fixture。

### D2: 同步性五态判定算法

指数角色按原版口径分组：**权重组** = 上证指数、沪深300；**成长组** = 创业板指、中证500；**深证成指**为中性参照——计入同步多数判定，不计入分化两组（原版四种模式未给它角色）。

优先级判定（涨跌幅沿用现有 ±0.5% 阈值，经验初值）：

```
1. synchronized_rally   涨跌幅 >= +0.5% 的指数 >= 4/5
2. broad_weakness       涨跌幅 <= -0.5% 的指数 >= 4/5
3. weight_shelter       权重组两者均 >= +0.5% 且成长组两者均 < 0
4. growth_lead          成长组两者均 >= +0.5% 且权重组两者均 < 0
5. undetermined_divergence  其余全部
```

- 备选：把深成指划入成长组——被否。原版明确成长组指"创业板、中证500"，深成指代表"市场整体成长活跃度"，角色不同；强行归组会让权重护盘/成长占优的判定偏离原文口径。
- 五态在 API 同时输出中文标签与机器码；`QTS-01-01-06` 的分档把五态映射为 0/25/50/75/100（synchronized_rally=100、growth_lead=75、weight_shelter=50、undetermined_divergence=25、broad_weakness=0，经验初值待回测）。

### D3: 250 日分位计算与 provider 深度

新纯函数在 `calculations.py`：先构造日频指标序列（MA20 斜率序列 = 逐日 `MA20/MA20[-5]-1`；推进效率序列 = 逐日 `日收益/换手比20`，分母下限 0.5，与量化文档口径一致），再对当日值求过去 250 个观测的滚动分位。280 根 K 线可产出约 255 个斜率观测，满足窗口。

`limit` 从 160 提升到 280：mootdx `offset=280`；新浪 `datalen=max(limit, 280)`；东方财富 `lmt=max(limit, 280)`；腾讯 K 线 `param` 数量 280；百度按同口径调整。降级链、价格交叉校验、进程内缓存全部不变。

- 备选：用固定阈值替代 250 日分位（省历史）——被否。量化文档 `QTS-01-01-02/05` 明确为 250 日滚动分位口径，改口径等于改规则。
- 有效观测 < 250 但 ≥ 60：输出分位值并降置信（confidence 降一档）；< 60：输出 `insufficient`。

### D4: 分层改动与数据流

```
providers.py (280根) -> calculations.py (新纯函数: 五态/斜率分位/效率分位/多头比例/收束句成分)
  -> service.py (指数字段: ma20SlopePercentile, advanceEfficiencyPercentile, syncPattern
                 市场字段: bullishAlignmentRatio, summarySentence, dataGaps)
  -> schemas.py (新增可选字段, 向后兼容) -> App.vue (矩阵/四问条/收束句/缺失态)
trading_system: snapshot schema + 3条YAML规则 + fixture -> evaluator (metric.band 复用)
```

四问结论条数据仍来自后端 `combinationOverview`（strength 文案改用五态输出），矩阵数据直接用各指数已有的 `combination` 对象在前端聚合，**不新增 API 端点、不新增请求**。

### D5: 第四部分矩阵与呈现结构

页面第四部分重组为一个组件区块，自上而下：四问结论条（横排四卡，每卡答案 + 置信度色点 + 点击可定位矩阵对应列）→ 矩阵（行=五指数，列=六组合按风险优先排列，命中格显示 tone 色块 + 关键数值缩写；未命中行尾显示"未分类"徽标；行可点击，与顶部指数卡选中联动）→ 选中行证据展开（现有 evidence 列表迁移至此）→ 收束句面板（引用样式，含成分缺失标注）。

现有"六类规则对照"静态面板合并进矩阵列头（悬停显示组合定义），不再独立成块。

### D6: 收束句生成位置（后端）

收束句在 `service.py` 组装为 `summarySentence` 字段：成分 = 同步性五态、收盘相对 MA20、60 日区间位置分档、当日成交额相对 5 日均值、价格推进结果（复用组合/量价判定）、环境倾向（复用四问的交易模式）。任一成分缺失时该分段渲染"数据不足"，句式骨架保持原版第五部分模板。

- 备选：前端拼句——被否。收束句是可审计输出，应进 API 契约测试，前端只渲染。

### D7: 缺失原因分层

新增 `dataGaps: list[{field: str, reason: Literal[insufficient-history|missing-today|provider-failed|not-computable]}]`（指数层与市场层各一份），reason 为闭合枚举；前端按枚举映射差异化文案（"历史窗口不足，暂无法计算分位" vs "当日行情获取失败" 等）。现有 warning 机制保留，`not-computable` 复用既有退化窗口警告。

## Risks / Trade-offs

- [拉取 280 根后个别 provider 参数上限或响应变慢] → 各 provider 单独冒烟验证 280 根返回与价格校验；不满足者在降级链中按现有校验自然跳过；冷缓存耗时实测对比并记录 runbook。
- [历史 SQLite 快照仍是 160 根，历史日期分位输出 insufficient] → 按缺失分层如实输出，不回填历史快照（同日期快照不复用的既有原则）；限制写入 runbook。
- [五态阈值与分档映射无回测证据] → 全部标 `needs-backtest`；不入评分组，golden trace 不变，回滚无评分影响。
- [矩阵在移动端过宽] → 列紧凑化 + 横向滚动兜底；延续现有桌面/移动浏览器走查验收。
- [深成指中性角色可能与读者直觉不符] → 在量化文档 06 规则行与 design 同步说明该口径来源。

## Migration Plan

纯追加式变更：API 只新增可选字段，旧响应消费者不受影响；规则 append-only，golden replay 输出不变。回滚 = revert 提交，无数据迁移；升级后新采集快照自然携带 280 根历史。
