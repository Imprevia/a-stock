## Why

当前 `core` 在通达信、百度和新浪不可用时会降级到腾讯历史 K 线，历史成交额可能缺失；Fuyao v2 已证明可为五个核心指数提供精确日期的 OHLC 与直接成交额，因此需要将其直接启用为正式首选源，而不是继续建设 shadow 对账流程。

## What Changes

- 将 Fuyao `fuyao-market-v2` 启用为 `core` 五个指数的正式第一数据源，逐指数失败时继续降级到既有 `mootdx -> 百度 -> 新浪 -> 腾讯 -> 东方财富` 链路。
- 明确不启用 shadow、不生成跨 provider 对账报告、不要求连续多日一致性比较；`core.shadowEnabled` 必须保持关闭。
- 正式启用仍要求一份经过审查、脱敏、checksum-valid 且状态为 `eligible` 的 core capability report；报告只证明 Fuyao 自身端点、字段、日期、历史深度、权限和请求预算，不包含跨源对账结论。
- 保留现有精确日期、至少 280 根有效 OHLC/成交额、规范指数身份、当前日期腾讯独立报价校验、单指数失败隔离、同日留存和跨日期拒绝契约。
- 增加同镜像、无 hook、配置优先的启用与回滚路径；正式启用只允许改变 core 批准版本和 enabled 开关，其他数据集、调度、Secret、Service、PVC、数据库与镜像保持不变。
- 启用后执行一次经单独授权的盘后 core-only 采集，验证 Fuyao 正式来源、直接成交额、五指数日期完整性和降级可见性；不自动触发额外连续观察。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `market-data-collection-management`: 增加 Fuyao core 正式首选路由、无 shadow 的 capability-gated 启用、逐指数降级和可逆配置发布要求。

## Impact

- 预期实现范围：`deploy/helm/a-stock/`、`deploy/truenas/`、部署 packet/validator、core provider 路由与门禁回归测试；现有正式路由代码已支持 Fuyao-first，优先复用而非重写。
- 持久化：需要将一份 reviewed core capability report 晋升到运行时 `provider_capability_reports`；不改变数据库 schema、快照主键或公开 API payload。
- 文档：同步 `docs/architecture.md`、`docs/runbooks.md`、`docs/repository-guide.md`、市场环境产品规格和 active exec plan。
- 安全边界：API key 仅来自既有 Secret；真实 probe、capability promotion、生产部署和 core-only 采集均需实施阶段分别获得明确授权。
- 本规划阶段不调用真实 provider、不读取或修改 Secret、不写生产数据库、不执行 Helm/kubectl 写操作。
