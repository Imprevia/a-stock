## ADDED Requirements

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

## MODIFIED Requirements

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
