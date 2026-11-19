# active-industry-scan-skill Specification

## Purpose

让 Agent 在盘中任意时点回答「资金正在进入哪些行业」：并行取成交额与换手率双榜，过滤上市不足一年的新股，映射到同花顺一级与二级行业，输出行业命中数、四象限归属与双榜交集股票，并把候选行业交由下游 Skill 正式打分。

## Requirements

### Requirement: 双榜并行且不可互相替代

Skill SHALL 在一次运行中同时采集成交额榜与换手率榜，并把两者作为独立榜单输出。Skill MUST NOT 只输出其中一个榜，MUST NOT 把换手率榜的行业分布当作资金规模的证据。

#### Scenario: 两榜行业分布显著不同

- **WHEN** 成交额 Top50 集中在少数行业、换手率 Top50 散落在多数行业
- **THEN** 两个榜的行业分布 MUST 分别输出
- **AND** 输出 MUST 保留两榜的交集股票及其在各自榜中的排名

#### Scenario: 只有一个榜可用

- **WHEN** 其中一个榜的请求失败而另一个成功
- **THEN** Skill MUST 输出成功榜单的完整结果
- **AND** 顶层质量状态 MUST 为 `degraded` 并记录失败榜单的原因
- **AND** 四象限 MUST 标记为不可用而非用缺测值推断

### Requirement: 新股按上市日期过滤并可审计

Skill SHALL 在排名前剔除上市不足 `--min-listing-days` 个自然日的股票，默认值 MUST 为 250。过滤 MUST 发生在取 Top N 之前，Skill MUST 用大于 N 的候选池补足名额，MUST NOT 先取 Top N 再删除导致榜单不足。

被剔除的股票 MUST 输出到独立的排除段，包含代码、名称、上市日期、上市天数与被剔除时的原始排名。

#### Scenario: Top50 内存在次新股

- **WHEN** 换手率候选池前 50 名中有股票上市不足 250 日
- **THEN** 这些股票 MUST 被排除出榜单
- **AND** 榜单 MUST 由候选池后续名次补足到 N 条
- **AND** 排除段 MUST 列出每只被剔除股票的原始排名

#### Scenario: 上市日期缺失

- **WHEN** 某只股票无法获得上市日期
- **THEN** 该股票 MUST 被排除并计入排除段
- **AND** Skill MUST NOT 假设其上市时间足够长

### Requirement: 行业聚合区分一级与二级

Skill SHALL 把双榜股票映射到同花顺一级与二级行业，并分别输出两个层级的行业命中数。输出 MUST 包含每个行业的成交额榜命中数、换手率榜命中数、成分股总数与命中率。分母为零或成分股缺失时，命中率 MUST 记为 `null`，MUST NOT 记为 0。

#### Scenario: 一只股票属于多个层级

- **WHEN** 某股票在一级行业与二级行业各有归属
- **THEN** 该股票 MUST 同时计入两个层级的对应行业
- **AND** 两个层级的命中数 MUST 独立统计，不可相互推导

#### Scenario: 行业成分股数量差异极大

- **WHEN** 两个行业的命中数相同但成分股总数相差一个数量级
- **THEN** 输出 MUST 同时给出命中数与命中率
- **AND** 排序 MUST NOT 只依据命中率，以免小行业因分母过小而虚高

### Requirement: 四象限分类只依赖横截面证据

Skill SHALL 依据「成交额榜命中数」与「换手率榜命中数」把行业归入四象限之一：真实活跃、权重拉升、小盘情绪、冷门。分类 MUST 只使用当次运行的横截面计数，MUST NOT 依赖历史分位、相对强度或任何需要完整交易日窗口的指标。

#### Scenario: 行业在两榜均有多只命中

- **WHEN** 某行业的成交额榜命中数与换手率榜命中数都达到阈值
- **THEN** 该行业 MUST 归入真实活跃
- **AND** 输出 MUST 给出两个计数作为依据

#### Scenario: 行业只在大成交额榜命中

- **WHEN** 某行业成交额榜命中数达到阈值但换手率榜命中数为零
- **THEN** 该行业 MUST 归入权重拉升
- **AND** Skill MUST NOT 因此把它判为弱势

### Requirement: 任意时点运行都给出确定的截止时刻

Skill SHALL 接受盘中任意时点运行，并始终输出 `sessionState`、`dataCutoff` 与 `elapsedBars`。`sessionState` MUST 取 `preopen`、`intraday`、`lunch`、`settling`、`closed` 之一。当已过 bar 数不足以形成稳定排名时，输出 MUST 显式标注早期快照不稳定。

#### Scenario: 开盘后不久运行

- **WHEN** 用户在开盘后不久提问，已过 bar 数为 1 至 3
- **THEN** Skill MUST 正常返回榜单
- **AND** 输出 MUST 标注 `elapsedBars` 与该快照不稳定的提示
- **AND** 说明首根 bar 含集合竞价、权重显著偏高

#### Scenario: 收盘后运行

- **WHEN** 用户在结算时刻之后运行
- **THEN** `sessionState` MUST 为 `closed`
- **AND** 输出 MAY 补充依赖完整交易日的个股历史分位字段
- **AND** 盘中运行的分位字段 MUST 标记为不可用并给出原因与可补算时刻

### Requirement: 盘中不输出依赖完整交易日的历史分位

Skill SHALL 在 `sessionState` 为 `intraday`、`lunch` 或 `settling` 时把换手率历史分位与放大倍数字段置为不可用。Skill MUST NOT 用「当日累计成交量 ÷ 历史平均全天成交量」或任何按固定比例缩放的换算来充当分位。

#### Scenario: 用户盘中要求历史分位

- **WHEN** 用户在盘中运行时请求个股换手率的历史分位
- **THEN** 该字段 MUST 返回不可用状态
- **AND** 输出 MUST 给出原因：当日累计量与历史全天分布不可比
- **AND** MUST 给出该字段可用的最早时刻

### Requirement: 双榜交集为空时不放宽阈值

Skill SHALL 输出同时进入两个榜 Top N 的股票集合。当该集合为空时，Skill MUST 输出空数组并说明本次无交集，MUST NOT 自动放宽 Top N、MUST NOT 改用「任一榜前若干名」等替代口径。

#### Scenario: 两个榜完全不相交

- **WHEN** 双榜 Top N 没有任何共同股票
- **THEN** 交集 MUST 为空数组
- **AND** 输出 MUST 说明本次无交集
- **AND** 整体质量状态 MUST 仍为 `ok`，不得因交集为空而判为失败

### Requirement: 候选行业以代码清单移交下游打分

Skill SHALL 把候选行业的 thscode 列表输出到独立的交接段，交由 `a-stock-qts04-sector-direction` 按已登记规则打正式分。Skill MUST NOT 自行计算行业评分、相对强度、成交额增量或持续性，MUST NOT 输出候选方向数量限制。

#### Scenario: 上游产出候选行业

- **WHEN** 扫描得到若干满足计数阈值的行业
- **THEN** 输出 MUST 包含这些行业的 thscode 列表与入选原因
- **AND** 输出 MUST 声明本 Skill 不评分
- **AND** 该列表 MUST 可直接作为下游 Skill 的输入

### Requirement: 行业成分股缓存可重建且带时效标记

Skill SHALL 把行业成分股映射缓存到本地可重建目录，MUST NOT 写入数据库、MUST NOT 提交到 git。当缓存不可用而接口失败时，Skill SHALL 使用过期缓存并在输出中标注缓存年龄。

#### Scenario: 成分股接口失败但存在旧缓存

- **WHEN** 行业成分股接口调用失败且本地存在旧缓存
- **THEN** Skill MUST 使用旧缓存继续产出行业段
- **AND** 输出 MUST 标注缓存日期与年龄
- **AND** 顶层质量状态 MUST 为 `degraded`

#### Scenario: 成分股接口失败且无缓存

- **WHEN** 行业成分股接口调用失败且本地无任何缓存
- **THEN** Skill MUST 仍然输出双榜与交集
- **AND** 行业段 MUST 标记为 `insufficient`
- **AND** MUST NOT 输出空的行业列表冒充成功

### Requirement: 单一数据源失败不得导致整体失败

Skill SHALL 在任一数据源失败时降级而非中止。每个数据源 MUST 有明确的降级路径与对应的质量状态记录。全程 MUST NOT 用其他日期数据替代目标时点，MUST NOT 伪造成功。

#### Scenario: 排序接口不可用

- **WHEN** 服务端排序接口请求失败
- **THEN** Skill SHALL 退回全量拉取后在本地重排
- **AND** 输出 MUST 记录使用了降级路径
- **AND** 质量状态 MUST 为 `degraded`

#### Scenario: 全部数据源不可用

- **WHEN** 双榜、分时与成分股全部失败
- **THEN** Skill MUST 以非零状态退出并给出失败原因
- **AND** MUST NOT 输出任何看似成功的空结果

### Requirement: 结果同时提供 JSON 与 Markdown

Skill SHALL 在一次运行中同时产出 JSON 与 Markdown。Markdown MUST 由 JSON 纯渲染生成，MUST NOT 重新计算任何指标，因此两份产物的数值 MUST 完全一致。JSON MUST 携带 `schemaVersion`、`ruleVersion`、`reportId` 与运行时刻。

#### Scenario: 校验两份产物一致

- **WHEN** 同一次运行产出 JSON 与 Markdown
- **THEN** Markdown 中的每个数值 MUST 可在 JSON 中找到同源字段
- **AND** 排除段与交集段 MUST 在两份产物中都出现

### Requirement: 输出不构成投资建议

Skill SHALL 把全部结论标记为观察用，规则状态 MUST 保持 `needs-backtest`。输出 MUST NOT 包含买入、卖出、仓位、目标价、个股推荐或交易指令，MUST 说明四象限是资金分布描述而非买卖信号。

#### Scenario: 用户询问是否可买

- **WHEN** 用户在扫描结果基础上询问某行业或个股是否可以买入
- **THEN** Skill MUST 说明本能力只描述资金分布
- **AND** MUST NOT 给出方向性交易判断

### Requirement: 离线 fixture 可验证全部降级路径

Skill 的测试与校验 MUST 在无网络条件下通过。Skill SHALL 支持 fixture 输入，使双榜采集、新股过滤、行业聚合、四象限、交集为空、各数据源降级与分位不可用状态均可在离线状态验证。取数 MUST 与计算分离，使计算部分可被纯函数测试覆盖。

#### Scenario: 无网络运行测试

- **WHEN** 在断网环境执行 Skill 的测试
- **THEN** 全部用例 MUST 通过
- **AND** 不得依赖真实行情接口或真实凭据

#### Scenario: 验证单源失败降级

- **WHEN** fixture 中把某一个数据源配置为失败
- **THEN** 输出 MUST 落在 `degraded` 或 `insufficient`
- **AND** 其余段 MUST 保持完整