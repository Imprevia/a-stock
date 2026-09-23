## MODIFIED Requirements

### Requirement: Active direction uses a validated endpoint fallback chain
系统 SHALL 先请求东方财富成交额排序主端点；只有主路径耗尽有界恢复预算或返回无效载荷后，才请求东方财富兼容延迟端点；只有两条东方财富路径均失败后，才允许请求通达信指定日期盘后全市场日线包。每条路径 MUST 按同一 active-direction 契约验证，且不得因来源不同而放宽日期、样本或字段要求。

#### Scenario: Primary active-direction endpoint succeeds
- **WHEN** 主端点返回有效的成交额排序 Top-N 载荷
- **THEN** 系统使用主端点行，记录来源 `eastmoney-clist`，且不调用延迟端点或通达信盘后包

#### Scenario: Primary active-direction endpoint remains unavailable
- **WHEN** 主端点在有界恢复后仍不可用，延迟端点返回有效载荷
- **THEN** 系统使用延迟端点行，完成 active-direction 采集，并不调用通达信盘后包

#### Scenario: Both Eastmoney endpoints fail and daily package succeeds
- **WHEN** 主端点和延迟端点均不可用，通达信盘后包证明属于所选交易日并返回满足契约的全市场日线行
- **THEN** 系统使用通达信行生成 active-direction，来源标记为 `tdx-daily-package`，质量状态标记为 fallback/degraded，并保留两条 Eastmoney 失败 warning

#### Scenario: Both active-direction endpoints fail
- **WHEN** 主端点和延迟端点均不可用，且通达信盘后包未启用或未返回可验证结果
- **THEN** active-direction 采集报告失败，warning 标识两条 Eastmoney 路径和通达信盘后包的最终结果

#### Scenario: Every active-direction endpoint fails
- **WHEN** 主端点、延迟端点和通达信盘后包均未返回可验证结果
- **THEN** active-direction 采集报告失败，warning 标识所有尝试过的路径，且不写入伪成功快照

### Requirement: Every active-direction source satisfies the same Top-N contract
系统 MUST 在生成或保存 active-direction 证据前验证主端点、延迟端点或通达信盘后包的候选载荷；每个来源都 MUST 提供至少 30 个有效行、证券代码、可信证券名称、数值成交额和非递增成交额顺序。系统不得把证券代码当作缺失名称，也不得为备用来源本地重排后冒充来源排序结果。

#### Scenario: Delayed endpoint returns enough valid sorted rows
- **WHEN** 延迟端点返回至少 30 行，且每行包含证券代码、证券名称、数值成交额并按成交额非递增排列
- **THEN** 系统可以从该载荷推导 Top-30 行业聚集和 Top-10 展示行

#### Scenario: Daily package returns enough valid sorted rows
- **WHEN** 通达信盘后包属于所选日期，且经过名称映射后的至少 30 行包含证券代码、可信名称、数值成交额并按成交额非递增排列
- **THEN** 系统可以从该载荷推导与现有 schema 兼容的 Top-30 和 Top-10 结果

#### Scenario: Delayed endpoint returns too few valid rows
- **WHEN** 延迟端点少于 30 行包含完整代码、名称和成交额字段
- **THEN** 载荷被拒绝，且不从该载荷写入成功快照

#### Scenario: Delayed endpoint returns unsorted rows
- **WHEN** 延迟端点的任一后续有效行成交额大于前一行
- **THEN** 载荷被拒绝，不得通过本地排序把它表示为 provider-ranked 结果

#### Scenario: Candidate source lacks names or enough rows
- **WHEN** 任一来源少于 30 个有效行，或无法为有效代码解析可信证券名称
- **THEN** 候选载荷被拒绝，不写入 successful active-direction snapshot

#### Scenario: Candidate source returns unsorted rows
- **WHEN** 任一来源的后续有效行成交额大于前一行
- **THEN** 候选载荷被拒绝，不得通过本地排序把它表示为 provider-ranked 结果

#### Scenario: Provider returns a keyed diff object
- **WHEN** 任一兼容行情端点返回按行号索引的对象而不是数组
- **THEN** 系统可以先规范化其行集合，再执行相同的字段、样本数、日期和排序校验

### Requirement: Active-direction fallback quality is auditable
系统 SHALL 通过现有 quality 契约暴露实际 active-direction 来源、质量状态、观测数和恢复 warning。

#### Scenario: Delayed endpoint supplies the result
- **WHEN** 延迟端点在主端点失败后提供有效结果
- **THEN** quality source 为 `eastmoney-clist-delay`，状态为 `fallback`，观测数反映通过校验的 Top-30 样本，且 warning 保留主端点失败和降级说明

#### Scenario: Daily package supplies the result
- **WHEN** 通达信盘后包在两条 Eastmoney 路径失败后提供有效结果
- **THEN** quality source 为 `tdx-daily-package`，状态为 `fallback` 或 `degraded`，观测数反映通过校验的 Top-30 样本，且 warning 保留全部前序失败原因

#### Scenario: Primary endpoint supplies the result
- **WHEN** 主端点提供有效结果
- **THEN** quality source 保持 `eastmoney-clist`，状态保持 `partial`，不添加 fallback warning

#### Scenario: Consumer ignores quality metadata
- **WHEN** 既有消费者只读取 active-direction 的 state、summary 和 Top-10 stock 字段
- **THEN** 这些字段保持兼容，不要求 API 或前端迁移

### Requirement: Active-direction failure preserves exact-date data semantics
系统 SHALL 将成功的 active-direction 快照与失败采集尝试分开保存，且 MUST NOT 用其他日期的快照替代所选日期。

#### Scenario: Fallback chain fails with a same-date snapshot
- **WHEN** 主端点、延迟端点和通达信盘后包均失败，且所选日期已有成功快照
- **THEN** 任务记录为 `failed-retained`，同日期快照保持可用，并暴露最新失败 warning

#### Scenario: Fallback chain fails without a same-date snapshot
- **WHEN** 主端点、延迟端点和通达信盘后包均失败，且所选日期没有成功快照
- **THEN** 任务记录为 `failed-missing`，active-direction 证据保持 `insufficient`

#### Scenario: Historical active-direction collection is requested
- **WHEN** 所选日期不是当前上海市场日，且 provider 无法证明返回结果属于所选日期
- **THEN** 请求在任何 provider 被调用前被拒绝，且不会把当前数据写入历史日期
