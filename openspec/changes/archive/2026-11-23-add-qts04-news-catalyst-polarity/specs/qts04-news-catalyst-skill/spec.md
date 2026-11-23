## Purpose

把公告摘要、异动解读与涨停原因归一到板块、题材和个股三个单元，输出可机械复算的利好/利空极性、个股风险分级、证据溯源与覆盖缺口声明，供 STEP 2 催化分级与 STEP 8 风险过滤消费。

## ADDED Requirements

### Requirement: 消息证据必须归属到单元成员

Skill SHALL 只把股票代码属于该单元成员的证据计入该单元的极性，MUST NOT 用板块名、题材名或新闻标题与名称的字面匹配建立归属。同一段文本被重复抓取时 MUST 按规范化内容去重后只计一次。

#### Scenario: 证据指向单元外股票

- **WHEN** 一条异动解读指向的股票不在某题材的成员列表中
- **THEN** 该证据 MUST NOT 计入该题材的极性与事件统计
- **AND** 该题材的输出 MUST 不因这条证据改变方向或强度

#### Scenario: 同一文本多渠道重复

- **WHEN** 同一段异动解读在同一天被涨停原因与异动解读两个来源同时返回
- **THEN** 极性统计 MUST 只计一次
- **AND** 证据列表 MAY 保留两个来源引用，但 MUST 标注为同一条文本

### Requirement: 极性五档且未知不等于中性

Skill SHALL 把每个单元的极性标注为 `positive` / `negative` / `mixed` / `neutral` / `unknown` 之一。当窗口内没有任何可用证据，或证据未达到最小覆盖闸门时，MUST 输出 `unknown` 并给出原因，MUST NOT 输出 `neutral`。

#### Scenario: 窗口内没有证据

- **WHEN** 某单元在回看窗口内没有任何归属证据
- **THEN** 该单元极性 MUST 为 `unknown`
- **AND** 输出 MUST 带 `missingReason`，说明是「无证据」还是「证据不足」

#### Scenario: 利好与利空同时出现

- **WHEN** 同一单元既有达到强度下限的正向事件，也有达到强度下限的负向事件
- **THEN** 该单元极性 MUST 为 `mixed`
- **AND** 输出 MUST 同时给出正向与负向的分数和各自的主要事件

#### Scenario: 只有澄清类公告

- **WHEN** 某单元的证据只有异动公告、澄清公告或风险提示模板文本，没有方向性事件
- **THEN** 该单元极性 MUST 为 `neutral`
- **AND** MUST NOT 因「有新闻」而写成 `positive` 或 `negative`

### Requirement: 否定与不确定语义必须改变判定

Skill SHALL 在命中词的就近作用域内处理否定词与不确定词。否定词命中时 MUST 翻转或取消该事件的极性；不确定词命中时 MUST 把该事件的严重度降一级并把可信度上限压到 `speculative`，MUST NOT 让「拟减持」「预计亏损」这类未落实事项触发最高等级风险。

#### Scenario: 计划中的减持被终止

- **WHEN** 文本为「终止减持计划」或「未实施减持」
- **THEN** 该条 MUST NOT 产生负向事件
- **AND** 不得据此把个股标为 `downgrade` 或 `watch`

#### Scenario: 尚未实施的减持

- **WHEN** 文本为「拟减持」「计划减持」且没有已实施表述
- **THEN** 该事件严重度 MUST 降一级
- **AND** 该股风险等级 MUST NOT 达到 `block`

#### Scenario: 否定词跨越分句

- **WHEN** 否定词只出现在另一个分句，与命中词之间隔着句号或分号
- **THEN** 该否定词 MUST NOT 作用于该命中词

### Requirement: 个股风险五档且硬否决优先

Skill SHALL 把每只个股的风险标注为 `block` / `downgrade` / `watch` / `none` / `uncovered` 之一。命中硬否决事件时 MUST 输出 `block`，且 MUST NOT 被同一窗口内的正向事件抵消。窗口内有证据但没有负向事件时输出 `none`；窗口内没有任何证据时 MUST 输出 `uncovered`，MUST NOT 输出 `none`。

#### Scenario: 硬利空与利好同时存在

- **WHEN** 某股同时命中「退市风险警示」与「业绩预增」
- **THEN** 风险等级 MUST 为 `block`
- **AND** 输出 MUST 保留正向事件，但 MUST NOT 用正向事件把等级降为 `downgrade`

#### Scenario: 有证据但无负向事件

- **WHEN** 某股在窗口内至少有一条归属证据，且没有命中任何负向规则
- **THEN** 风险等级 MUST 为 `none`
- **AND** 输出 MUST 同时给出实际检出的证据条数

#### Scenario: 个股没有任何证据

- **WHEN** 某股在窗口内没有归属证据，或抓取源不可用
- **THEN** 风险等级 MUST 为 `uncovered`
- **AND** 文章 MUST 写「未覆盖」，MUST NOT 写「无利空」「未见风险」

### Requirement: 主源不可枚举时可信度最高为 partial

Skill SHALL 输出 `primarySourceAvailable = false` 及原因。当证据只来自厂商 AI 摘要、涨停原因或媒体聚合时，单条证据可信度 MUST 最高为 `partial`，MUST NOT 输出 `confirmed`，文章 MUST NOT 出现「已证实」「确认利好」「官方确认」。

#### Scenario: 只有 AI 汇总的异动解读

- **WHEN** 当日所有证据都带「由 AI 技术搜集公开信息总结生成」的免责声明
- **THEN** 每条证据可信度 MUST 为 `partial` 或更低
- **AND** 顶层 MUST 声明主源不可用

#### Scenario: 文章声称已证实

- **WHEN** 文章出现「已证实」或「确认利好」，而 JSON 中没有 `confirmed`
- **THEN** 机械校验 MUST 判为 FAIL
- **AND** 该文章 MUST NOT 作为最终结论呈现

### Requirement: 覆盖缺口必须显式且不得按安全处理

Skill SHALL 在 `quality.sources` 中逐源记录可用状态、条数与降级原因。当 `stock-timeline-list` 不可用时 MUST 记为 `unavailable` 并整体降级为 `degraded`。板块/题材单元 MUST 达到最小证据闸门（至少 2 条证据且覆盖 2 只成员）才允许给出非 `unknown` 极性；未达到时 MUST 输出 `insufficient` 语义并保留缺口。

#### Scenario: 个股新闻源返回数据源不可用

- **WHEN** `news stock-timeline-list` 返回数据源不可用
- **THEN** `quality.sources.stockTimeline.status` MUST 为 `unavailable`
- **AND** 整体状态 MUST 为 `degraded`
- **AND** 个股层 MUST 只按可用源给出覆盖结论，MUST NOT 补造证据

#### Scenario: 题材只有一条证据

- **WHEN** 某题材窗口内只有 1 条证据或只覆盖 1 只成员
- **THEN** 该题材极性 MUST 为 `unknown`
- **AND** 输出 MUST 记录未达闸门的具体原因

#### Scenario: 板块成员数很大而证据很少

- **WHEN** 板块成员数远大于有证据的成员数
- **THEN** 输出 MUST 给出 `memberCoverage` 实际值
- **AND** MUST NOT 把低覆盖方向写成高置信度

### Requirement: 输出可复算 JSON 且词表版本冻结

Skill SHALL 以 JSON 为唯一事实源，JSON MUST 包含 `schemaVersion`、`step`、`ruleVersion`、`reportId`、`asOf`、`config`、`input`、`status`、`quality`、`units`、`stocks`、`lexicon`、`disclaimer`、`calibration`。`config` MUST 冻结回看窗口、强度阈值、时效半衰期、最小证据闸门与词表哈希；同一输入与同一词表重跑 MUST 得到相同 `reportId`。

#### Scenario: 同日重跑

- **WHEN** 同一交易日、同一输入、同一词表重跑
- **THEN** `reportId` MUST 不变
- **AND** `units` 与 `stocks` 的排序 MUST 稳定

#### Scenario: 词表调整

- **WHEN** 词表新增或修改一条规则
- **THEN** `lexicon.sha256` MUST 变化
- **AND** `reportId` MUST 随之变化

### Requirement: 可链式消费上游且不重算上游结论

Skill SHALL 可独立运行，也可读取 STEP 1 或 STEP 2 的 JSON。消费上游时 MUST 校验其 `schemaVersion` 并记录上游 `reportId`；题材单元 MUST 直接使用上游成员列表，板块单元在缺少成员时 MAY 重新拉取当前成分股并把 `pointInTime` 标为 `false`。上游版本不兼容时 MUST 拒绝消费并输出 `insufficient`。

#### Scenario: STEP 2 结果作为输入

- **WHEN** 调用方提供合法的 STEP 2 JSON
- **THEN** 题材单元 MUST 使用其 `themes[].members.codes`
- **AND** `input.step2ReportId` MUST 记录上游身份
- **AND** MUST NOT 重新判定上游的题材真伪或分级

#### Scenario: 上游 schemaVersion 不兼容

- **WHEN** 上游 JSON 的 `schemaVersion` 不受支持
- **THEN** Skill MUST 拒绝消费
- **AND** 输出 `insufficient` 并说明版本不匹配

### Requirement: 报告只表达观察且标签必须溯源

Skill SHALL 只允许文章使用 JSON 中出现的极性、风险与状态标签，并 MUST 在结尾给出免责声明与 `needs-backtest`。文章 MUST NOT 出现买入、加仓、仓位、必涨、目标价、买卖点或个股推荐；数字 MUST 能在 JSON 中找到出处。

#### Scenario: 文章使用未出现的标签

- **WHEN** 文章把 `unknown` 写成「中性」，或把 `uncovered` 写成「无利空」
- **THEN** 机械校验 MUST 判为 FAIL

#### Scenario: 文章出现交易指令

- **WHEN** 文章出现「买入」「加仓」「目标价」等禁用措辞
- **THEN** 机械校验 MUST 判为 FAIL
- **AND** MUST 回退到事实骨架并标注未通过项

### Requirement: 非交易日与未收盘日期必须拒绝

Skill SHALL 只接受已收盘交易日。未来日期、当日 15:10 前（`Asia/Shanghai`）与非交易日 MUST 拒绝运行并输出 `insufficient`，MUST NOT 用相邻交易日的数据顶替。

#### Scenario: 盘中请求当日结果

- **WHEN** 目标日为当天且当前时间早于 15:10
- **THEN** Skill MUST 拒绝并说明未收盘

#### Scenario: 目标日无交易

- **WHEN** 目标日是非交易日
- **THEN** Skill MUST 输出 `insufficient`
- **AND** MUST NOT 回退到上一交易日取数