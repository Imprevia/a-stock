## ADDED Requirements

### Requirement: TDX breadth 快照只保存通过证券宇宙校验的结果

快照采集 MUST 在写入 `breadth` 精确日期快照前完成 TDX 证券宇宙筛选、市场覆盖、最小样本、日期和涨跌事实校验。过滤前的全证券行数不得作为 breadth 的 `observations`、`validCount` 或计数依据；快照质量 MUST 保存筛选策略版本和可审计的过滤统计。

#### Scenario: 合法 TDX breadth 候选写入

- **WHEN** TDX 候选属于请求交易日，且普通 A 股筛选、三地市场覆盖、最小样本和涨跌事实校验全部通过
- **THEN** 系统只保存过滤后普通 A 股计算出的 payload，`observations` 与 payload 的 `validCount` 一致，并保留同一请求日期、来源、质量状态、策略版本和过滤统计

#### Scenario: 全证券候选不得写成成功

- **WHEN** TDX 候选只有“有价格/有涨跌幅”事实，但没有通过普通 A 股证券宇宙校验，或过滤后样本不完整
- **THEN** 系统 MUST 拒绝将候选写为成功/fallback breadth 快照，并返回 `insufficient`/`failed` 及诊断 warning

### Requirement: 已知错误的 breadth 快照必须通过受控精确日期重采集纠正

系统 MUST 支持对已被识别为错误证券宇宙的精确日期 breadth 快照执行受控重采集。纠正过程 MUST 使用原请求日期重新取得和校验 TDX 包，不得直接修改 payload、将其他日期快照改名写入目标日期或在普通 GET 中自动触发 provider。重采集失败时 MUST 保留既有快照并记录 `failed-retained`；没有可保留快照时记录 `failed-missing`，不得继续把已知错误值标记为新的成功结果。

#### Scenario: 已知错误快照重采集成功

- **WHEN** 2026-09-23、2026-09-24 或其他被标记为全证券 universe 的日期按原日期重新采集，且新结果通过普通 A 股筛选和完整性校验
- **THEN** 系统以该精确日期的新 payload 原子替换旧错误快照，更新 checksum、observations、quality warning 和聚合证据，并保留可审计的重采集尝试

#### Scenario: 已知错误快照重采集失败

- **WHEN** 精确日期 TDX 包不可用、日期不匹配、过滤后样本不足或其他校验失败
- **THEN** 系统不得覆盖旧快照为失败 payload；采集尝试标记 `failed-retained` 或 `failed-missing`，普通 GET 继续显式暴露错误 universe 警告或不足状态

#### Scenario: 普通读取不触发纠正

- **WHEN** 用户通过普通市场环境 GET 请求包含已知错误或缺失 breadth 快照的日期
- **THEN** 系统只读取本地精确日期证据，不调用 TDX/Eastmoney，不自动写入或跨日期回填，并返回可诊断的质量状态
