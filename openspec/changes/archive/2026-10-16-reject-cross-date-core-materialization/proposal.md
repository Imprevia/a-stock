## Why

盘后 `core` 采集可能在请求日期为当日时取得仍停留在前一交易日的指数历史，却被记录为成功并物化到请求日期，最终形成数据库键日期与 payload `asOf` 不一致的聚合。该状态已导致生产看板的 v2 overview 返回 500、legacy core 返回 503，因此必须在采集、持久化、物化和读取边界统一执行精确日期合同，并以受控错误替代裸异常。

## What Changes

- 当 `core` 指数证据无法证明请求日期时，将该次采集分类为日期不匹配失败；不得把前一日 payload 标为请求日期成功，也不得发布请求日期聚合。
- 在 snapshot 与 materialized aggregate 的实际写路径统一校验 key、payload `asOf`、candidate `actual_as_of` 和指数历史有效日期；legacy 兼容只允许读取已知历史形态，不再放宽新写入。
- 保留同日期成功证据和兄弟数据集结果；日期不匹配按 `failed-retained` 或 `failed-missing` 表达，并保留真实来源、实际日期和 warning。
- v2 exact-date GET 遇到存量完整性冲突时返回稳定、可诊断的 503，而不是未处理的 500；legacy 路径继续 fail closed，普通 GET 不触发 provider、采集或数据修复。
- 增加存量错位记录的只读审计与显式修复运行手册：不自动改日期、不跨日期复制、不删除或覆盖已有成功证据；生产修复仍需独立授权。
- 扩充采集、PostgreSQL repository、物化、v2/legacy HTTP、前端 fallback 和发布 smoke 的确定性回归，覆盖 provider 仅返回前一日数据的场景。

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-data-collection-management`: 强化 core 日期能力验证、失败留存和物化发布条件，禁止跨日期结果被记为成功。
- `market-data-snapshot-cache`: 强化 durable snapshot 与 materialized aggregate 的精确日期写入和存量完整性处理合同。
- `ai-market-data-api`: 为存量完整性冲突增加稳定、provider-free 的错误语义，避免 v2 exact-date GET 裸 500 或跨日期替代。

## Impact

- 后端采集与领域边界：`src/market_environment/infrastructure/providers/core_acquisition.py`、normalized outcome/quality/date evidence。
- PostgreSQL 写读与物化：snapshot repository、core committer、materialized aggregate composer/CAS、v2 read adapter。
- HTTP 与前端：v2/legacy 错误映射、dashboard v2-to-legacy fallback 的错误展示。
- 测试与文档：相关 backend/frontend tests，以及 `docs/architecture.md`、`docs/product-specs/market-environment-dashboard.md`、`docs/repository-guide.md`、`docs/runbooks.md` 和 active exec plan。
- 生产状态：不包含自动数据修改、provider 采集、部署或 PostgreSQL 写操作；存量 `2026-10-16` 错位证据的处置须在实现验收后另行授权执行。
