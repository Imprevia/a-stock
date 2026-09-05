## Why

TrueNAS k3s 上的 `a-stock` release 当前通过局域网 HTTP NodePort `32001` 无认证暴露，并显式关闭手工采集，因此未认证 collection POST 返回 403。直接把 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 改为开启会把可触发外部行情 provider、写入共享 SQLite PVC 的操作开放给所有能访问该 NodePort 的客户端，不符合现有产品规格和架构安全边界。

需要先确定一个最小权限的访问路径，再决定是否重部署。推荐复用已有 SSH/kubeconfig 身份，将 Service 收回为 ClusterIP，仅通过绑定本机回环地址的临时隧道访问数据管理页；这样无需假设应用已经具备认证能力，也不新增常驻安全组件。

## What Changes

- 推荐方案：将现有 NodePort Service 收回为 ClusterIP，显式开启 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED`，由获授权运维人员通过 `kubectl port-forward`（必要时外层使用 SSH）临时访问完整 Dashboard 和手工采集 API。
- 保持 Deployment 单副本、现有不可变镜像、静态 PVC、SQLite 路径和采集协调器不变；配置变更不得删除、替换或迁移 PVC。
- 部署前导出当前 Helm values、release revision、工作负载状态和 SQLite 备份；以受版本控制的环境 values 执行 Helm upgrade，不使用可能遗漏新默认值的盲目 `--reuse-values`。
- 定义 provider 出口、并发 lease、日期能力、部分失败、容量与审计验证；手工采集仍只能由既有五类数据集和 API 契约触发。
- 定义配置级快速回滚：先关闭手工采集，再按需回滚 release；PVC 和成功快照全程保留。
- 备选方案 A：若必须持久局域网访问，在应用前增加具备 TLS、身份认证和路径授权的反向代理，仅授权操作者访问 collection POST，应用 Service 仍保持 ClusterIP。
- 备选方案 B：若只需补数据而不需要网页手工模式，继续关闭 HTTP 写入口，通过受控一次性 CLI Job 采集；该方案攻击面最小，但不满足网页按钮随时可用。
- 明确拒绝方案：不得仅在当前无认证 NodePort 上把开关改为开启；CORS、隐藏按钮、源 IP 日志均不是认证或授权边界。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `market-data-collection-management`: 增加已部署无应用认证环境启用手工采集时的受保护访问、最小权限、配置发布、数据保留、回滚和运行验证要求。

## Impact

- 规划中的部署配置：`deploy/helm/a-stock/` 的环境覆盖将把 Service 设为 ClusterIP，并向 Dashboard 容器显式注入手工采集开关；本 change 当前不修改任何 values 或模板。
- 规划中的运维流程：更新 TrueNAS 部署 runbook、产品规格、架构和 active exec plan，记录隧道建立、备份、Helm upgrade、验证和回滚命令。
- 网络：实施后不再从 `192.168.1.20:32001` 直接访问；操作者通过本机回环地址上的临时端口访问。k3s API 和 SSH 仍不得向普通局域网或公网扩大暴露。
- 数据：继续挂载现有 PVC 和 `/data/snapshots.sqlite3`；不执行 schema 迁移。collection run/task、成功快照和失败保留语义不变。
- 外部依赖：手工 POST 可触发通达信 TCP 和腾讯、百度、新浪、东方财富 HTTPS；必须保持现有限流、串行门、重试和 `degraded` / `insufficient` 行为。
- 当前状态：仅完成架构提案，尚未进入开发、Helm 配置修改或 TrueNAS 生产部署。
