## Why

当前 `activeDirection` 依赖东方财富返回已经按成交额排序的榜单；主域和延迟域同时不可用时，即使通达信盘后包包含精确日期的全市场成交额数据，系统也只能失败。真实 TDX 包的原始行并不保证成交额降序，因此需要明确允许一种可审计的本地派生质量，而不是把本地排序结果伪装成 provider-ranked 数据。

## What Changes

- 在 Eastmoney 主域和延迟域均失败后，允许使用精确日期、完整性通过的 TDX 全市场盘后包作为 `activeDirection` 候选。
- 对 TDX 全市场行执行本地稳定排序：按成交额降序，并使用证券身份作为确定性并列排序键。
- 新增明确的质量状态 `fallback-derived` 和来源标识 `tdx-daily-package-derived`，表示结果由本地计算得到，不代表上游已提供排序榜单。
- 保留至少 30 条有效股票、代码、名称、收盘价和成交额校验；名称可由盘后包或受限的批量名称查询补齐，但不得用其他来源的价格、成交额或日期替代 TDX 事实。
- 为 Top-30 行业聚集增加版本化行业映射、映射日期和覆盖率证据；映射不足时仍可展示 Top-10 股票，但方向聚集状态必须为 `insufficient` 或 `unverified`。
- 使采集协调器能够保存 `fallback-derived` 的精确日期快照，并将该任务/父运行标记为部分成功或降级，而不是全量 `success`。
- 在质量元数据、数据采集页和 active-direction 页面中区分 provider-ranked、普通 fallback 和本地派生 fallback。
- 保持 Eastmoney 主链顺序、默认关闭开关、失败保留、禁止跨日期回填和 provider-free 状态读取语义不变。

## Capabilities

### New Capabilities

<!-- No standalone capability is introduced; this is an extension of existing collection contracts. -->

### Modified Capabilities

- `active-direction-data-collection-stability`: 增加 TDX 本地排序的 derived fallback，并定义其字段、日期、排序、行业映射和质量证据边界。
- `market-data-collection-management`: 允许 `fallback-derived` 结果作为可保存的精确日期快照，同时将采集任务和父运行保持为降级/部分成功语义。

## Impact

- 后端：`src/market_environment/providers.py`、`src/market_environment/tdx_daily.py`、`src/market_environment/collection.py`、质量状态常量和行业映射组件。
- 前端：active-direction 与数据采集页的质量状态标签、来源和 warning 展示；现有 Top-10 字段保持兼容。
- 文档：`docs/architecture.md`、`docs/runbooks.md`、对应 active plan，以及 TDX 上游 revision 和行业映射版本的审计说明。
- 测试：TDX 排序与并列稳定性、行业映射覆盖率、质量状态、快照保存、失败保留、父运行状态和前端质量标签测试。
- 部署：默认不启用新的派生路径；启用仍需显式 feature flag、脱敏 real probe 和受控发布验证。不新增数据库删除或跨日期回填操作。
