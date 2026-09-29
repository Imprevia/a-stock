## Why

行业板块采集当前只能在东方财富 `push2` 与 `push2delay` 之间降级；两个端点属于同一供应商，供应商接口被远端断连时会同时失败，导致当天行业数据进入 `failed-missing`，而现有重试无法恢复。扶摇行业接口尚未通过真实能力验证，TDX 盘后包也没有可审计的行业映射，因此需要先建立独立 provider 的验证与受控回退边界。

## What Changes

- 增加独立行业数据 provider 的能力探测、脱敏报告和离线契约验证；未证明精确上海市场日期、分页/排序、行业字段和领涨股名称的 provider 不得启用。
- 在东方财富主域与延迟域均失败后，按明确的 provider 优先级尝试已批准的独立来源；成功时保留真实来源、版本、前序失败 warning 和质量状态。
- 保持行业行的现有 API 结构与缺失值语义；`rank`、行业代码/名称、涨跌幅、成交额、上涨/下跌家数和领涨股名称必须逐字段校验，无法提供的资金字段保持 `null` 并降低质量，不得用零值或其他日期补齐。
- 保持精确日期隔离和失败审计：独立来源失败时继续使用同日期 `failed-retained` / `failed-missing`，不得跨日期回填或把未验证结果写成成功快照。
- 补充周末/节假日日期被后端归一后仍能触发 `sectors` section 请求的前端回归覆盖，避免页面因原始选择日期与有效交易日不一致而静默显示空数据。
- 同步相关 capability spec、架构、运行手册、active plan、provider/collection 测试和受控开关；默认关闭新来源，正式切换需 capability revision 与 shadow 对账通过。

## Capabilities

### New Capabilities

无。该变更扩展现有行业板块采集契约，不引入新的用户可见能力边界。

### Modified Capabilities

- `sector-data-collection-stability`: 行业采集从同供应商双端点降级扩展为经过能力验证的独立 provider fallback，并明确字段、日期、来源和质量门禁。
- `market-data-collection-management`: 采集任务需要记录独立 provider 的 capability revision、实际来源和前序失败 warning，同时保留失败隔离、同日期留存和 provider-free 状态读取。

## Impact

- 后端：`src/market_environment/providers.py`、`collection.py`、provider capability/quality 适配层及行业 provider 客户端。
- API 与持久化：沿用现有 `SectorEvidence`、快照主键和失败留存结构；如需新增来源或 capability 元数据，只允许加法字段/记录。
- 前端：`DashboardLayout`、market store 及行业页导航/日期切换测试；不改变行业表格的现有展示结构。
- 配置与部署：新增独立 provider 的显式开关、批准 revision 和必要 Secret 引用，默认关闭且不得把凭据写入 values、日志或响应。
- 文档与验证：同步 `docs/architecture.md`、`docs/runbooks.md`、产品规格和 active plan；增加离线 fixture、shadow/contract 测试和真实 provider 的隔离盘后 probe，不能把真实网络访问混入 PR 门禁。
