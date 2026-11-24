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

当上市日期字段整体不可用（接口返回非空的股票列表，但所有记录的上市日期都缺失）时，Skill MUST 把它识别为「过滤能力不可用」并降级：继续输出双榜、交集与行业段，标记顶层质量状态为 `degraded`，并显式告警本次未执行新股过滤。Skill MUST NOT 因此产出空榜单或以非零状态退出，MUST NOT 把缺失上市日期的股票当作上市时间足够长而不作任何说明。

#### Scenario: Top50 内存在次新股

- **WHEN** 换手率候选池前 50 名中有股票上市不足 250 日
- **THEN** 这些股票 MUST 被排除出榜单
- **AND** 榜单 MUST 由候选池后续名次补足到 N 条
- **AND** 排除段 MUST 列出每只被剔除股票的原始排名

#### Scenario: 上市日期缺失

- **WHEN** 某只股票无法获得上市日期，而其他股票的上市日期可用
- **THEN** 该股票 MUST 被排除并计入排除段
- **AND** Skill MUST NOT 假设其上市时间足够长

#### Scenario: 上市日期字段整体不可用

- **WHEN** 上市日期接口返回非空列表，但所有股票的上市日期都缺失
- **THEN** Skill MUST 跳过新股过滤并继续产出双榜与行业段
- **AND** 顶层质量状态 MUST 为 `degraded`，并记录「新股过滤未执行」的告警
- **AND** 榜单 MUST NOT 为空，进程 MUST NOT 以退出码 2 结束

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

### Requirement: 方向与活跃度正交且只做描述

Skill SHALL 在双榜明细、行业段与交集段同时输出方向字段。方向 MUST 由个股当日涨跌幅或板块指数涨跌幅独立判定，MUST NOT 由成交额榜命中数、换手率榜命中数或四象限标签推断。

方向 MUST NOT 参与行业排序，MUST NOT 用于筛选交接清单，MUST NOT 产生任何评分或方向数量限制。

#### Scenario: 双榜命中多但整体下跌

- **WHEN** 某行业在成交额榜与换手率榜上的命中数都达到四象限阈值，但其板块指数与上榜股多数下跌
- **THEN** 该行业 MUST 仍按活跃度进入行业段并保持 `quadrant` 为 `真实活跃`
- **AND** 其方向 MUST 输出为下跌，复合标签 MUST 为 `真实活跃·下跌`
- **AND** Skill MUST NOT 因方向为下跌而把它改判为冷门、移出榜单或降低排序

#### Scenario: 交接清单不受方向影响

- **WHEN** 扫描得到若干满足活跃度阈值的候选行业
- **THEN** `handoff.candidateThscodes` MUST 仍只由活跃度决定
- **AND** 每个候选项 MUST 附带方向字段，供使用者在阅读时区分上涨与下跌
- **AND** Skill MUST NOT 因方向为下跌而剔除该候选

### Requirement: 方向使用绝对与相对双基准

Skill SHALL 同时输出绝对方向与相对方向。绝对方向 MUST 是个股或板块指数相对前一收盘价的涨跌幅。相对方向 MUST 是同一口径下相对全市场中位涨跌幅的超额，单位为百分点。

相对基准 MUST 使用全市场逐股涨跌幅的中位数（等权），MUST NOT 改用成交额加权指数或其他加权口径替代。基准不可用时，相对字段 MUST 为 `null` 并记录原因，MUST NOT 用 0 替代，MUST NOT 回退到其他日期或其他指数的数据。

#### Scenario: 单边下跌交易日

- **WHEN** 全市场多数股票下跌、绝对方向把大多数行业标为下跌
- **THEN** 输出 MUST 同时给出每个行业的相对方向
- **AND** 相对方向 MUST 能把「跌幅小于市场」与「跌幅大于市场」的行业区分开
- **AND** 输出 MUST 显式给出所用基准值，使相对方向可复算

#### Scenario: 基准数据源不可用

- **WHEN** 全市场快照获取失败
- **THEN** 绝对方向 MUST 仍然输出
- **AND** 所有相对字段 MUST 为 `null`
- **AND** 顶层质量状态 MUST 为 `degraded` 并记录失败原因
- **AND** Skill MUST NOT 用指数涨跌幅冒充全市场中位

#### Scenario: 开盘前运行

- **WHEN** `sessionState` 为 `preopen`
- **THEN** 方向字段 MUST 标注其反映的是前一交易日收盘方向
- **AND** 输出 MUST NOT 把该方向描述为当日方向

### Requirement: 停牌与无昨收样本剔除并单列

Skill SHALL 在计算任何方向分母时剔除当日成交量为 0 或涨跌幅缺失的股票，并把数量输出到独立的停牌计数。MUST NOT 把停牌股票计入平盘，MUST NOT 把缺失涨跌幅当作 0。

#### Scenario: 全市场快照包含停牌股票

- **WHEN** 全市场快照中存在成交量为 0 或涨跌幅为 `null` 的股票
- **THEN** 这些股票 MUST 被排除出上涨、下跌、平盘三个计数
- **AND** 停牌数量 MUST 单独输出
- **AND** 上涨数、下跌数与平盘数之和 MUST 等于有效样本数

#### Scenario: 行业成分股包含停牌股票

- **WHEN** 某行业的部分成分股当日停牌
- **THEN** 该行业的宽度分母 MUST 只统计有效样本
- **AND** 覆盖率 MUST 按有效成员数除以成分股总数计算
- **AND** 停牌股票 MUST NOT 计入平盘家数

### Requirement: 行业方向必须给出三类证据

Skill SHALL 为每个行业输出三类方向证据：板块指数涨跌幅、上榜股上涨与下跌家数、全成分股上涨与下跌与平盘家数及中位涨跌幅。

全成分股宽度的覆盖率 MUST 按有效成员数除以成分股总数计算。覆盖率低于 70% 时，该行业的宽度字段 MUST 标记为 `insufficient` 且数值 MUST 为 `null`，MUST NOT 用不足的样本给出宽度结论。

#### Scenario: 三类证据同向

- **WHEN** 某行业的板块指数下跌、上榜股多数下跌、全成分股多数下跌
- **THEN** 输出 MUST 同时给出三组数值
- **AND** 三组数值 MUST 来自同一次运行的同一时点
- **AND** 输出 MUST NOT 只保留其中一类证据

#### Scenario: 宽度覆盖率不足

- **WHEN** 某行业的有效成分股不到成分股总数的 70%
- **THEN** 该行业宽度字段 MUST 为 `null` 并标记 `insufficient`
- **AND** 板块指数与上榜股方向 MUST 仍然输出
- **AND** 该行业的复合标签 MUST 由可用证据给出并显式说明宽度缺失

### Requirement: 方向分组随 JSON 与 Markdown 一起输出

Skill SHALL 在结果中输出市场方向基准块与双榜方向汇总，并在 Markdown 中给出「活跃上涨」与「活跃下跌」两个方向分组。分组内容 MUST 由 JSON 字段纯渲染，MUST NOT 重新计算方向或分数。

#### Scenario: 同一次运行的两份产物一致

- **WHEN** 同一次运行同时产出 JSON 与 Markdown
- **THEN** Markdown 中每个方向分组条目 MUST 能在 JSON 中找到同源字段
- **AND** 分组成员数量与方向标签 MUST 与 JSON 完全一致

#### Scenario: 某个方向分组为空

- **WHEN** 所有行业方向一致，导致其中一个方向分组为空
- **THEN** 该分组 MUST 明确说明本次为空
- **AND** Skill MUST NOT 放宽方向判定阈值来填充分组

### Requirement: 方向数据源独立降级

板块指数或全市场快照失败时，Skill MUST 保留其余可用证据并降级，MUST NOT 因为方向层失败而中止运行。MUST NOT 用其他日期的数据或其他指数的数据替代目标时点的方向证据。

#### Scenario: 板块指数接口失败

- **WHEN** 板块指数快照请求失败
- **THEN** 行业段 MUST 仍输出上榜股方向与全成分股宽度
- **AND** 板块指数涨跌幅字段 MUST 为 `null`
- **AND** 顶层质量状态 MUST 为 `degraded` 并记录失败原因

#### Scenario: 全部方向数据源失败

- **WHEN** 板块指数与全市场快照都失败
- **THEN** 双榜与交集 MUST 仍按原口径输出
- **AND** 方向相关字段 MUST 全部为 `null` 或不可用状态
- **AND** 顶层质量状态 MUST 为 `degraded`
- **AND** Skill MUST NOT 输出看似完整的方向结论
