## ADDED Requirements

### Requirement: Collection tasks expose provider provenance and shadow state

采集任务结果 SHALL 分别报告正式 provider、实际来源 revision、是否运行 shadow、shadow 结论和差异 warning。shadow 或能力探测的失败不得被汇总为正式数据集成功，也不得改变现有五类任务的独立状态和父批次 `partial` 语义。

#### Scenario: Formal collection succeeds with shadow match
- **WHEN** 一个数据集使用现有 provider 正式写入成功，扶摇 shadow 对账在容差内通过
- **THEN** 任务报告正式来源为现有 provider、shadow 状态为 `match`，并保持成功快照不变

#### Scenario: Shadow mismatch accompanies formal success
- **WHEN** 正式 provider 成功但扶摇 shadow 出现差异
- **THEN** 正式快照仍可保留，任务 warning 标记差异，shadow 不得升级为扶摇正式来源

### Requirement: Provider cutover is validated before collection writes

数据集切换请求 MUST 在创建 provider 采集任务前校验能力状态、开关和验证证据。未通过验证的数据集切换请求 SHALL 被拒绝且不产生外部 provider 写入；切换验证只影响目标数据集，不得阻塞其他已授权数据集任务。

#### Scenario: Cutover request lacks capability evidence
- **WHEN** 请求启用扶摇采集但能力矩阵状态不是 `eligible`
- **THEN** API 或 CLI 返回可审计的拒绝结果，不创建该数据集的采集 lease 或快照

#### Scenario: One dataset is rejected during a full run
- **WHEN** 一键采集包含一个未通过扶摇切换校验的数据集和多个正常数据集
- **THEN** 被拒绝的数据集记录独立失败原因，其他数据集继续按各自 provider 执行，父批次按现有规则汇总为 `partial` 或相应状态
