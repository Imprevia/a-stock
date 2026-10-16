## Why

当前市场环境 API 虽已提供 core 与 chapter section 入口，但 section 查询仍返回完整 Chapter 01，完整聚合样本约 174–185 KB，且指数历史、涨跌停证券池和板块明细缺少面向 AI 上下文预算的资源级拆分与分页。需要新增一套只读、精确日期、可发现且有界的 API，使 AI 能先读取紧凑概览，再按需获取单一资源，而不触发 provider 或下载无关数据。

## What Changes

- 新增版本化的 AI 友好市场环境只读 API，以 overview 作为发现入口，并将指数、市场广度、涨跌停、板块、容量方向、事件和综合评估拆成独立资源。
- 将指数当前分析与单指数历史拆分；将涨跌停汇总、证券池、历史和规则/风险证据拆分；将板块 observation、持续性分析和 operation checkpoint 以有界列表返回。
- 为所有新响应统一提供精确 `asOf`、`generatedAt`、opaque `snapshotRevision`、质量/来源/warning，以及适用时的稳定分页与资源链接。
- 新增 `/llms.txt` 与 `/llms-full.txt` 发现文档，以 OpenAPI 和仓库事实文档为来源，说明可用资源、日期语义、分页、质量状态和调用示例；文档不承载实时市场数据。
- 保留现有 `/api/market-environment`、`/core`、`/chapter-01` 与现有 THS 路径及响应字段，前端和其他消费者可渐进迁移；本变更不引入破坏性删除。
- 新增契约与体量护栏测试，证明细粒度 GET 只返回请求资源、列表受服务端边界约束、普通读取零 provider I/O，且跨请求 revision 可检测。
- 不扩展现有交易知识 MCP，不新增写接口、provider 采集、数据库迁移、部署调度或生产操作。

## Capabilities

### New Capabilities

- `ai-market-data-api`: 定义面向 AI 的市场环境发现文档、资源级只读端点、有界分页、版本一致性、质量语义和旧接口兼容边界。

### Modified Capabilities

- 无。

## Impact

- 后端：`src/market_environment/interfaces/http/` 的路由与专用响应 DTO、`application/queries/` 的资源级查询、必要的 repository read port 和 OpenAPI 元数据。
- 前端：`apps/market-environment-dashboard/` 渐进迁移到新资源端点，并修正 THS K 线请求页大小与服务端上限不一致的问题。
- 文档：`docs/architecture.md`、`docs/product-specs/market-environment-dashboard.md`、`docs/runbooks.md`、`docs/repository-guide.md`、active execution plan，以及由 OpenAPI/事实文档生成或校验的 AI 发现文档。
- 测试：API 路由与 schema 契约、section/resource 隔离、分页上限、exact-date、revision 一致性、provider-free 读取、前端请求与兼容回归。
- 无新增外部运行时依赖；不改变 PostgreSQL 事实、现有采集边界或 legacy 完整聚合契约。
