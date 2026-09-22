## Purpose

为市场环境采集提供可审计的扶摇能力验证、按数据集适配和受控迁移边界，确保替换数据源不会伪造历史日期、丢失字段质量或绕过现有降级与快照契约。

## ADDED Requirements

### Requirement: Fuyao capability inventory is explicit per dataset

系统 SHALL 为 `core`、`breadth`、`sectors` 和 `activeDirection` 分别输出扶摇能力状态，至少包含端点、字段覆盖、日期证据、历史窗口、分页或排序证据、权限/限流结果和当前结论（`eligible`、`ineligible` 或 `unverified`）。已接入的 `limits` 能力 SHALL 单独标注为现有实现，不得被重复声明为待迁移能力。

#### Scenario: Capability is sufficient for a dataset
- **WHEN** 扶摇端点在隔离验证中提供所需字段、精确日期证据、完整分页或排序和通过对账的结果
- **THEN** 该数据集报告为 `eligible`，并记录验证样本、provider revision 和剩余风险

#### Scenario: Capability evidence is incomplete
- **WHEN** 端点缺少必需字段、无法证明请求日期、历史窗口不足或分页/排序校验失败
- **THEN** 该数据集报告为 `ineligible` 或 `unverified`，列出缺失证据，且不得启用扶摇替换

### Requirement: Fuyao adapters preserve dataset contracts

对被允许试点的数据集，扶摇适配结果 MUST 保留现有数据集的 payload 字段、`quality` 结构、精确 `asOf` 语义、观察数、warning 和缺失值语义。适配器不得用当前日期、其他交易日或默认零值补齐无法从扶摇证明的值。

#### Scenario: Historical result passes contract validation
- **WHEN** 扶摇返回一个已由交易日历和响应字段共同证明的历史交易日结果
- **THEN** 适配器返回与既有数据集契约兼容的结果，并把实际日期、来源和抓取时间写入质量元数据

#### Scenario: Provider cannot prove requested date
- **WHEN** 扶摇只返回最新快照或响应日期与请求日期不一致
- **THEN** 适配器返回 `insufficient` / `failed` 质量，不写入所选历史日期的成功快照

### Requirement: Shadow comparison is non-destructive and auditable

系统 SHALL 支持扶摇与当前 provider 的 shadow 对账，并按数据集适用的指数代码、规范证券身份、计数、排序和数值容差输出差异。shadow 结果不得覆盖成功快照、改变公开数据集状态或被解释为已验证替换。

#### Scenario: Shadow results agree within policy
- **WHEN** 两个 provider 都返回可比较结果且差异在数据集容差内
- **THEN** 对账报告标记为 `match`，记录比较范围、样本数和容差，但仍保持当前 provider 为正式来源，除非已显式启用切换

#### Scenario: Shadow results diverge or one provider fails
- **WHEN** 结果出现身份缺失、字段冲突、排序不一致、数值超差或任一 provider 失败
- **THEN** 报告标记为 `mismatch` / `degraded` / `insufficient`，保留 warning，并禁止由该次 shadow 自动切换来源

### Requirement: Dataset cutover is opt-in and fail-closed

系统 MUST 以数据集为粒度控制扶摇切换，默认关闭 `core`、`breadth`、`sectors` 和 `activeDirection` 的扶摇正式采集。只有能力状态为 `eligible` 且通过离线契约测试、shadow 对账和隔离盘后 smoke 的数据集才能启用；切换失败时必须回退现有 provider 或保留同日期成功快照。

#### Scenario: Unverified dataset is requested for cutover
- **WHEN** 操作者启用一个状态为 `unverified` 或 `ineligible` 的数据集
- **THEN** 配置校验拒绝启动，并说明缺少的能力证据，不调用扶摇写入快照

#### Scenario: Enabled dataset encounters a runtime failure
- **WHEN** 已启用的扶摇数据集发生权限、限流、网络、字段或日期校验失败
- **THEN** 采集任务按现有失败隔离语义结束，使用已授权的旧 provider 降级或报告 `failed-retained` / `failed-missing`，不得跨日期回填

### Requirement: Fuyao credentials and external verification are isolated

扶摇 API key MUST 只通过独立运行时 Secret 或进程环境注入，不得出现在仓库、values、日志、API 响应、fixture 或 shadow 报告中。真实 provider 验证 MUST 由显式盘后/本地命令写入隔离存储，PR 确定性测试 MUST 使用脱敏 fixture。

#### Scenario: Credential is missing or denied
- **WHEN** provider key 缺失、无效或权限不足
- **THEN** 扶摇数据集 fail closed，保留现有快照和 warning，且日志中不包含 key 内容

#### Scenario: Pull request runs provider tests
- **WHEN** CI 或本地离线门禁执行扶摇相关测试
- **THEN** 测试只使用脱敏 fixture 和固定响应，不访问真实 provider，不写生产或共享运行时数据库
