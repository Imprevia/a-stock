## ADDED Requirements

### Requirement: TDX 派生容量方向只使用普通 A 股股票宇宙

当 `activeDirection` 走 TDX 派生路径时，系统 MUST 在成交额排序前复用与 `breadth` 相同的、按请求日期版本化的普通 A 股证券宇宙策略。结果至少覆盖上海主板、科创板、深圳主板、创业板和北京证券交易所普通股票；基金、债券、指数、权证、B 股、存托凭证及其他不能证明为普通股票的行 MUST 被排除。过滤后的样本不足 30 条或关键市场覆盖/身份事实不足时，不得写入派生成功快照。

#### Scenario: 混合 TDX 包不污染成交额 Top-N

- **WHEN** TDX 包同时包含普通 A 股、基金、债券、指数和其他有成交额证券，且 Eastmoney 两条路径均失败
- **THEN** `activeDirection` 的本地成交额排序、Top-30 观测和 Top-10 展示只使用通过普通 A 股策略的行

#### Scenario: 北交所代码按请求日期解释

- **WHEN** 请求日期早于或不早于北交所 `920` 号段规则生效日，且包内同时出现历史有效号段、`920` 号段和非股票号段
- **THEN** 系统按请求日期选择版本化规则，保留适用日期的普通北交所股票，并排除不能证明为普通股票的行

#### Scenario: 过滤后不足以形成派生榜单

- **WHEN** 普通 A 股过滤后少于 30 条有效行、必要市场缺失、身份无法分类或金额/收盘价事实不完整
- **THEN** TDX 候选被拒绝，任务使用 `failed-retained` / `failed-missing`，不得把未过滤的全证券 Top-N 作为成功结果

### Requirement: TDX 派生容量方向暴露 universe 审计信息

当 `activeDirection` 使用 TDX 派生路径时，质量元数据 MUST 暴露与 `breadth` 一致的策略版本、过滤前行数、保留普通 A 股行数、排除行数、未分类行数和按市场保留统计；既有来源、状态、Top-N 和行业映射字段 MUST 保持兼容。

#### Scenario: 派生结果完整且可追溯

- **WHEN** TDX 包通过精确日期、普通 A 股过滤、最小样本、名称、成交额和收盘价校验
- **THEN** 系统以 `tdx-daily-package-derived` / `fallback-derived` 保存精确日期结果，`observations` 等于验证后的 Top-30 数量，并保留 universe 过滤审计字段

#### Scenario: 过滤审计不完整

- **WHEN** 分类策略版本、保留统计或关键市场覆盖无法证明
- **THEN** 系统拒绝将 TDX 候选标记为派生成功，并输出可诊断 warning，不回退到全证券计数或排序
