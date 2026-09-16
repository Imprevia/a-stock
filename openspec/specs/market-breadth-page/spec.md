## ADDED Requirements

### Requirement: 复盘卡展示当日六项结果与宽度标签
系统 MUST 在第 02 页最上方渲染"复盘卡"section，包含六张结果卡（上涨家数、上涨占比、下跌家数、下跌占比、平盘家数、涨跌家数差）+ 一张全 A 涨跌幅中位数卡 + 一个六选一的宽度标签（同向增强 / 同向走弱 / 指数强个股弱 / 指数弱个股修复 / 混合 / 数据不足）+ 一段自然语言依据。涨跌家数差 MUST 等于 `advanceCount - declineCount`。上涨占比与下跌占比 MUST 来自后端预计算字段 `advanceRatio` / `declineRatio`，前端不重新计算。

#### Scenario: 数据完整日
- **WHEN** 后端 `breadth` 章节中 `validCount` ≥ 1 且所有关键字段非空
- **THEN** 复盘卡 7 个数值卡全部显示数字与单位；宽度标签从六个候选中选中一项，依据以一句自然语言展示

#### Scenario: 数据不足日
- **WHEN** `validCount` 为 0 或 `quality.status` 为 `missing` / `failed` / `insufficient`
- **THEN** 数值卡显示 `--`；宽度标签固定为 `数据不足`；依据显示具体缺失原因

### Requirement: 量化证据展示五条规则的当前值与得分
系统 MUST 在复盘卡下方渲染"量化证据"section，列出 `QTS-01-02-01` 到 `QTS-01-02-05` 五条规则，每行 MUST 展示规则 ID、标题、当前值、250 日分位条（mini bar）、得分、权重。前 4 条规则使用分位带（`P20=0 / P20<P40=25 / P40<P60=50 / P60<P80=75 / >P80=100`），第 5 条使用 boolean（一致=100 / 不一致=0）。section 底部 MUST 显示加权得分、置信度、覆盖率与缺失输入列表。

#### Scenario: 全部规则证据可用
- **WHEN** 5 条规则的 `value` / `score` 全部返回非空
- **THEN** 五行全部显示分位条与得分；底部加权得分、置信度、覆盖率有具体值

#### Scenario: 部分规则缺失
- **WHEN** 至少一条规则 `score` 为 null
- **THEN** 该规则行显示 `--` 与缺失原因；底部"缺失输入"列出未提供的 metric；置信度按缺失比例下调

### Requirement: 近五日宽度趋势表与折线图
系统 MUST 渲染"近 5 个已验证交易日"section，包含表格（asOf、上涨家数、下跌家数、平盘家数、涨跌差、上涨占比、下跌占比、中位数、5 日动量、宽度标签、指数一致性）与一张双轴 ECharts 折线图（左轴上涨占比 %、右轴涨跌幅中位数 %）。表格 MUST 用 `--` 表达缺失值，不补 0；折线图 MUST 用连续折线连接有数据的交易日，缺失日跳过。图表 X 轴 MUST 用 5 个交易日 asOf 标签；当日行 MUST 加粗并标 ★。

#### Scenario: 历史 5 日数据齐全
- **WHEN** `breadth.history` 包含 5 个非空点位
- **THEN** 表格显示 5 行；折线图绘制 5 个数据点；当前交易日标记 ★

#### Scenario: 历史不足 5 日
- **WHEN** `breadth.history` 仅含 N 个点位（N < 5）
- **THEN** 表格显示 N 行；折线图 X 轴缩短；section 顶部提示"近 5 日观察仅 N / 5"

### Requirement: 指数与广度一致性矩阵
系统 MUST 渲染"指数与广度一致性"section，包含 5 个指数（上证、沪深300、深证成指、创业板、中证500）的表格列：涨跌幅、方向、中位数方向、一致性（✓ / ✗）、提示文字。section 底部 MUST 显示综合判定（5/5 强一致 / 4/5 多数一致 / ≤3/5 权重分歧）。"一致"定义为 `sign(indexChangePct) == sign(breadthMedianReturn)`，缺失指数该列显示 `--`。

#### Scenario: 5 个指数数据齐全
- **WHEN** 5 个指数 `changePct` 全部非空
- **THEN** 矩阵 5 行齐全；底部综合判定有具体数字（如"4/5 同向 = 多数一致"）

#### Scenario: 部分指数缺失
- **WHEN** 至少一个指数 `changePct` 为 null
- **THEN** 缺失指数的方向与一致性列显示 `--`；底部判定基于有效指数的过半数

### Requirement: 次交易日验证项与质量元数据
系统 MUST 渲染"次交易日验证项"section，包含自然语言卡片（今日宽度标签 / 核心证据 / 下一交易日验证项 / 确认条件 / 失效条件）以及"质量元数据"子 section（数据源、状态、缓存状态、抓取时间、观察数、数据警告列表）。确认条件 MUST 基于量化版分位带给出建议范围（如"上涨占比 ≥ 60% 且中位数 ≥ +0.50%"）；失效条件 MUST 给出反向范围。验证项 MUST 提供"一键复制"按钮，复用现有 copy 按钮模式。

#### Scenario: 验证项可复制
- **WHEN** 用户点击"复制验证项"
- **THEN** 整段验证项文本写入剪贴板；UI 显示成功提示

#### Scenario: 数据警告非空
- **WHEN** `quality.warnings` 含至少 1 条
- **THEN** 质量元数据底部列出全部警告，字体 ≥ 14px，不截断

### Requirement: 后端契约同时扩展 11 个新字段
`BreadthEvidence`（后端 Pydantic） MUST 新增：`declineRatio`、`advanceDeclineSpread`、`advanceRatioPercentile`、`medianReturnPercentile`、`spreadPercentile`、`momentum`、`momentumPercentile`、`indexConsistent`、`widthLabel`、`widthLabelReason`。`BreadthAnalysis`（章节契约） MUST 额外新增 `history: list[BreadthHistoryPoint]` 与 `percentile250: dict[str, float | None]`（覆盖与有效观察统计）。`BreadthHistoryPoint` MUST 包含 `asOf` / 5 个计数字段 / `advanceRatio` / `declineRatio` / `advanceDeclineSpread` / `medianReturn` / `momentum` / `widthLabel` / `indexConsistent` / `quality`。所有新字段 MUST 为可空，缺失时返回 `null` 而非 0。

#### Scenario: 字段填充完整
- **WHEN** `validCount` ≥ 1 且 PostgreSQL 中至少 60 个历史交易日可用
- **THEN** 11 个新字段全部返回非空；`history` 包含 5 个点位

#### Scenario: 历史不足或样本失效
- **WHEN** PostgreSQL 中历史 breadth 快照少于 60 个或当条样本失效
- **THEN** 3 个分位字段返回 `null` 并标记 `confidence=insufficient`；`widthLabel=数据不足`；`history` 仅含可用的天数

### Requirement: 历史来源固定为 snapshot_store
`_breadth_result` MUST 通过 `snapshot_store.get("breadth", previous_date)` 拉取历史快照，窗口固定为最近 5 个交易日（不含当日）。历史快照读取 MUST 复用现有 `service.py` 第 249-273 行模式，不引入新数据源。

#### Scenario: 历史快照读取成功
- **WHEN** PostgreSQL 中存在目标日期的 breadth 快照
- **THEN** 该日点位进入 `history`

#### Scenario: 历史快照缺失
- **WHEN** 目标日期 PostgreSQL 中无 breadth 快照
- **THEN** 该日从 `history` 中跳过；不影响其它日；不报错

### Requirement: 宽度标签 6 档分类与依据
宽度标签 MUST 按以下顺序派生（命中即返回）：`数据不足` → `指数强个股弱`（多数指数上涨 + 上涨占比 < 40% 或中位数 < 0）→ `指数弱个股修复`（多数指数下跌 + 上涨占比 ≥ 50% + 中位数 ≥ 0）→ `同向增强`（指数方向与中位数同向 + 较前一日共同改善）→ `同向走弱`（同向 + 共同恶化）→ `混合`。`widthLabelReason` MUST 用一句话中文说明判定依据。

#### Scenario: 同向增强
- **WHEN** 中位数为正、多数指数上涨、且上一交易日 `advanceRatio` 与 `medianReturn` 均改善
- **THEN** `widthLabel=同向增强`；`widthLabelReason` 含"上涨占比 X% 与中位数 +Y% 同向且较前一日改善"

#### Scenario: 数据不足
- **WHEN** 任何关键字段为 null
- **THEN** `widthLabel=数据不足`；`widthLabelReason` 含具体缺失字段名

### Requirement: 前端视觉语言约束
02 页所有新增 section MUST 沿用现有 token：≥ 14px 字号；面板使用 `panel-heading` / `panel-kicker`；表格使用 `limits-table` / `history-table` 视觉；矩阵使用 `combination-matrix` 同级 token；不使用新颜色、不修改 spacing；移动端 390px 宽 MUST 不出现页面级横向溢出（宽表自身滚动除外）。新增 ECharts 折线图 MUST 使用独立 `breadthChart` 实例，不与现有 `chart` / `volumeChart` 共享，离开 02 页时 dispose。

#### Scenario: 桌面端渲染
- **WHEN** 视口宽度 ≥ 1024px
- **THEN** 5 section 自上而下排列；宽表不滚动；图表占满容器宽度

#### Scenario: 移动端渲染
- **WHEN** 视口宽度 = 390px
- **THEN** 5 section 单列堆叠；宽表自身滚动；不出现页面级横向溢出；字号 ≥ 14px