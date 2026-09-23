## ADDED Requirements

### Requirement: Date-bound daily-package fallback for stock datasets
当 `breadth` 或 `activeDirection` 的现有 Eastmoney 主路径和延迟路径均不可用时，系统 SHALL 允许使用通达信盘后全市场日线包作为独立备用来源。备用结果 MUST 同时证明请求的精确交易日、源侧日期、完整性和必需字段，并通过现有质量契约暴露 `source`、状态、观测数和 Eastmoney 失败 warning。

#### Scenario: Daily package proves the requested date
- **WHEN** Eastmoney 两条路径均失败，通达信盘后包已发布，且包内日期、请求日期和有效证券行一致
- **THEN** 对应的 `breadth` 或 `activeDirection` 任务使用通达信盘后包完成，标记为 fallback/degraded，记录来源和原 Eastmoney 失败原因，并只写入所选交易日快照

#### Scenario: Daily package is unavailable or not yet published
- **WHEN** Eastmoney 两条路径均失败，通达信盘后包不存在、尚未发布、下载失败或格式无法解析
- **THEN** 任务保持 `failed-missing` 或 `failed-retained`，记录可审计 warning，不把空包、零值或其他日期数据写成成功快照

#### Scenario: Daily package date evidence conflicts
- **WHEN** 盘后包声明的日期与所选日期不一致，或包内有效行无法证明属于所选交易日
- **THEN** 备用结果被拒绝，所选日期不会写入该来源的成功快照，且失败状态保留现有 exact-date 语义

#### Scenario: Status reads remain provider-free
- **WHEN** 用户读取数据采集状态、任务历史或失败重试信息
- **THEN** 系统只读取本地状态和快照，不为判断通达信盘后包是否可用而调用任何外部 provider
