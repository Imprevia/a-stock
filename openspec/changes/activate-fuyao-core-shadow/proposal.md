## Why

当前 `core` 正式采集仍会在通达信、百度和新浪不可用时降级到腾讯历史 K 线，导致历史成交额可能缺失；仓库虽已具备 Fuyao v2 指数历史适配器和非破坏性 shadow 对账，但默认部署未启用 core shadow，现有单次验证也仍有成交额口径差异，尚不足以批准正式切换。

## What Changes

- 为 `core` 增加一个可审计的 shadow-only 激活路径：保持 Fuyao 正式切换关闭，只让 Fuyao v2 与现有正式来源并行采集和比较。
- 固定 shadow 配置不变量：`core.enabled=false`、`core.approvedRevision=fuyao-market-v2`、`core.shadowEnabled=true`，并保持其他数据集、镜像、Secret、调度、Service、PVC 和数据库配置不变。
- 记录五个核心指数的精确日期、历史长度、OHLC、涨跌幅、成交额差异及成交额证据口径；shadow 结果仅进入脱敏任务元数据，不得写成正式快照或改变公开数据质量状态。
- 以至少五个已结算交易日的连续观察作为后续正式切换评审输入；`mismatch`、`degraded`、`insufficient` 或成交额口径未解释清楚时继续保持正式切换关闭。
- 提供配置优先的回滚与验证流程；真实 provider 调用、生产部署和观察窗口执行仍需在实施阶段逐项获得明确授权。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `market-data-collection-management`: 增加 Fuyao core shadow-only 激活、非破坏性对账、连续观察验收和 fail-closed 回滚要求。

## Impact

- 预期实现范围：`deploy/helm/a-stock/`、`deploy/truenas/` 的 shadow-only values/验证资产，以及必要的 core shadow 配置和对账回归测试；若现有实现不能完整满足契约，再最小修改 `src/market_environment/infrastructure/providers/`。
- 文档范围：`docs/architecture.md`、`docs/runbooks.md`、`docs/repository-guide.md`、active exec plan 和部署/观察证据说明。
- 不改变公开 API payload、交易规则、正式 provider 顺序、数据库 schema、调度所有权或普通 GET 的 provider-free 边界。
- 不在本变更规划阶段调用真实 Fuyao、写生产 PostgreSQL、修改 Kubernetes/Helm release、Secret、PVC 或远端状态。
