## Why

现有 `sectors` 只保留 Fuyao `industry` 目录的 Top 10 兼容行，完整编号、量价历史和成员内部结构都没有形成可查询的本地事实；其兼容投影还把 THS observation 与申万 canonical analysis 混在同一公共标识下，并在一次成功采集后未能物化 Chapter 01。需要把该兼容任务拆成职责清晰、可审计且可恢复的三个数据集。

## What Changes

- **BREAKING**：公共 collection dataset 枚举由 `core`、`breadth`、`limits`、`sectors`、`activeDirection` 迁移为 `core`、`breadth`、`limits`、`industry-ranking`、`sector-turnover`、`sector-breadth`、`activeDirection`；显式请求 `sectors` 返回可识别的不支持错误。
- 建立 `industry`、`cn_concept`、`region`、`tszs` 四类版本化 THS 目录，保存分类关系、共享代码身份、provider/fetch 时间、数量、checksum 和 revision，并从完整当日快照生成稳定分类排名。
- 建立板块日线事实，完整保存 OHLC、`volume` 和 `turnover`；每日快照追加全部编号，单编号历史按最多近五年、每批最多 60 编号进行显式、可恢复和幂等的分片回填。
- 建立仅当日的板块宽度结果，每类默认 Top 10 并支持用户点选编号；从当前成员和同日个股事实计算涨跌平、上涨占比、涨跌家数差率、中位涨幅、MA20 宽度、涨跌停、Top 成交/涨幅、单股成交贡献和扩散率。
- 以 Fuyao 全市场日 K、最近 10 日增量和复权因子 dump 为成员事实主源，以 TDX 精确日期盘后事实为降级源；不足或混合来源必须输出质量与 lineage，禁止用当前成员回算历史宽度。
- 三任务按 `industry-ranking -> sector-turnover -> sector-breadth` 依赖执行，兄弟任务失败隔离；首次新任务成功后重建 Chapter 01，修复“快照成功但章节未物化”。
- 普通 GET 仅查询本地 PostgreSQL；目录同步、历史回填、dump 导入和 provider 请求只允许由显式 POST/CLI 在盘后、权限、请求预算和 capability revision 门禁下触发。
- **BREAKING**：Chapter 01 删除 `sectors` 字段，新增 `industryRanking`、`sectorTurnover`、`sectorBreadth`，并将已有申万分析迁移到独立 `sectorAnalysis`；旧 `sectors` 快照只作为审计证据保留，不改写为新数据集。
- 数据管理页用三张任务卡替换 `sectors`；第 05 页提供“排名、板块宽度、量价 K 线、申万持续性”四个视图，THS observation 不进入申万一级 `QTS-01-05-*` 输入。

## Capabilities

### New Capabilities

- `fuyao-ths-sector-datasets`: 定义四类 THS 目录、完整当日排名、OHLC/volume/turnover、按需历史回填、成员事实导入、当日宽度计算、质量 lineage、provider-free 查询及显式写入门禁。

### Modified Capabilities

- `market-data-collection-management`: 将 `sectors` 公共任务迁移为三个独立任务，定义依赖、失败隔离、状态/重试/进度接口和不支持旧标识的行为。
- `sector-data-collection-stability`: 退役旧 Eastmoney/Fuyao 兼容 `sectors` 公共投影，保留历史审计证据，并明确 THS observation 与申万 canonical analysis 的身份隔离。
- `after-market-data-collection-scheduling`: 更新受控调度的数据集覆盖和三任务依赖，同时继续保持默认 `enabled=false`、`suspend=true`。
- `market-data-snapshot-cache`: 更新 Chapter 01 物化字段和重建语义，保证新数据集成功提交后可原子重建且旧 `sectors` 证据不被重写。

## Impact

- 后端：`src/market_environment/` 的领域模型、provider adapter、application commands、collection registries/coordinator、PostgreSQL schema/repositories/UoW、materialization、HTTP schemas/routes 和 CLI。
- 数据库：新增 additive PostgreSQL 表和索引；旧 snapshot/task/aggregate 记录保留，不执行破坏性迁移。
- 前端：collection API/types、数据管理页、第 05 页、文档上下文和 ECharts 量价视图。
- 部署：Helm/Kustomize dataset 配置和调度参数保持默认关闭；真实 provider probe、生产数据库迁移、首次回填、部署与调度激活需要另行明确授权。
- 文档与验证：同步产品规格、架构、runbook、仓库映射、状态、active plan、OpenAPI/TypeScript 契约和离线 fixture；记录 Fuyao 动态接口索引 `https://fuyao.aicubes.cn/llms-full.txt`，但不提交其远程全文或真实目录数据。
