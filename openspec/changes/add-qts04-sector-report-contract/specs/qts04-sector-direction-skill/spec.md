## MODIFIED Requirements

### Requirement: 方向输出包含确认与失效条件

Skill SHALL 输出 1 至 3 个候选方向，每个方向 MUST 包含板块总分、持续性分、四象限归属、五指标明细，以及可机器求值的次日确认条件与失效条件。数量 MUST NOT 超过 3 个。确认条件与失效条件 MUST 同时提供结构化谓词与人类可读文本，两者 MUST 由同一组数值生成。

#### Scenario: 存在合格方向

- **WHEN** 至少一个行业板块分不低于 50
- **THEN** Skill 输出最多 3 个方向
- **AND** 每个方向的确认条件与失效条件都带结构化谓词和对应的人类可读文本

#### Scenario: 无合格方向

- **WHEN** 所有行业板块分都低于 50 或全部被覆盖率闸门排除
- **THEN** Skill 输出空方向列表
- **AND** 它说明是被分数门槛还是覆盖率闸门排除

#### Scenario: 谓词可由未来行情直接求值

- **WHEN** 给定某方向的确认谓词与后续交易日的行情
- **THEN** 求值只需要字段名、比较符、阈值与评估窗口
- **AND** 求值过程 MUST NOT 需要理解自然语言文本

### Requirement: 同时产出机器可读与人工可读结果

Skill SHALL 产出 JSON 作为唯一事实源，并产出面向人阅读的文章。文章 MUST 由调用方按 Skill 声明的输出约束依据该 JSON 生成，MUST NOT 引入 JSON 中不存在的数据。JSON MUST 自包含到可被下游 Skill 直接消费的程度。

#### Scenario: JSON 可被下游直接消费

- **WHEN** 下游流程按 `schemaVersion` 读取 JSON
- **THEN** 它能定位每个方向的标识、分数、指标与冻结配置
- **AND** 它 MUST NOT 需要解析人类可读文本才能取得判定所需数值

#### Scenario: 默认写出 Markdown 报告

- **WHEN** 调用方给出 `--output result.json`
- **THEN** Skill 同时写出 `result.json` 与 `result.md`
- **AND** `result.md` 作为事实骨架，包含结论速览表、每个方向的五指标表、次日确认与失效条件
- **AND** 它 MUST NOT 被表述为对外主报告

#### Scenario: 文章通过机械校验后才呈现

- **WHEN** 调用方生成人类可读文章
- **THEN** 文章在呈现前 MUST 通过数字溯源、禁词与必备项校验
- **AND** 未通过校验的文章 MUST NOT 作为最终结论呈现

#### Scenario: 缺分数不渲染成零

- **WHEN** 某指标 `score` 为 `null` 且 `normalizedWeight` 为 `null`
- **THEN** 事实骨架把得分与权重渲染为 `—`
- **AND** 该方向的权重列合计 MUST NOT 超过 100%

#### Scenario: 报告不越界

- **WHEN** 生成任何面向人的报告
- **THEN** 报告包含免责声明与 `needs-backtest` 标记
- **AND** 报告中不出现 `validated`、买卖点、仓位或个股推荐

#### Scenario: 数据不足时报告不给方向

- **WHEN** 结果为 `insufficient`
- **THEN** 报告写明「本次不产出方向」并列出全部原因
- **AND** 它不渲染任何方向小节

## ADDED Requirements

### Requirement: 报告可标识且配置被冻结

Skill 输出的 JSON MUST 包含 `schemaVersion`、`reportId` 与 `config`。`reportId` MUST 由参与判定的冻结内容确定性计算，MUST NOT 包含生成时间等易变字段。`config` MUST 冻结本次判定实际使用的权重、分位五档边界、最少观测数、覆盖率门槛、宽度范围与确认/失效系数。

#### Scenario: 同一输入得到相同 reportId

- **WHEN** 用相同交易日、相同行情与相同配置运行两次
- **THEN** 两次产出的 `reportId` 相同
- **AND** 仅 `generatedAt` 等易变字段允许不同

#### Scenario: 配置变化改变 reportId

- **WHEN** 宽度范围或任一阈值发生变化
- **THEN** `reportId` 随之改变
- **AND** 调用方可据此判断两份结论是否可比

#### Scenario: 旧格式被明确拒绝

- **WHEN** 下游读取到的 JSON 缺少 `schemaVersion`
- **THEN** 下游 MUST 拒绝消费并报告版本不兼容
- **AND** 它 MUST NOT 按当前版本静默解析

### Requirement: 人工报告必须通过机械校验

Skill SHALL 提供一个确定性校验器，仅依据 JSON 与文章文本判断文章是否可呈现。校验 MUST 覆盖数字溯源、禁用措辞与必备项三类检查，且 MUST NOT 调用语言模型。

#### Scenario: 文章数字必须能在 JSON 中找到出处

- **WHEN** 文章中出现的百分比、倍数、金额或评分在 JSON 中不存在对应值
- **THEN** 校验失败并指出该数字与所在位置
- **AND** 允许按展示精度舍入后匹配

#### Scenario: 禁用措辞被拒绝

- **WHEN** 文章出现 `买入`、`加仓`、`仓位`、`必涨`、`已验证` 或 `目标价`
- **THEN** 校验失败并指出命中的措辞

#### Scenario: 必备项缺失被拒绝

- **WHEN** 文章缺少免责声明、`needs-backtest` 标记、数据状态或方向置信度
- **THEN** 校验失败并指出缺失项

#### Scenario: 校验结论确定

- **WHEN** 用同一份 JSON 与同一篇文章重复校验
- **THEN** 每次得到相同的通过或失败结论
- **AND** 校验 MUST NOT 依赖网络或外部服务

#### Scenario: 数据不足时不要求文章编造方向

- **WHEN** JSON 状态为 `insufficient`
- **THEN** 校验器 MUST NOT 要求文章包含方向小节
- **AND** 它要求文章说明未产出方向的原因