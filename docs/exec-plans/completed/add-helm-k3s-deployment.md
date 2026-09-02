# 新增 Helm k3s 部署配置

## Stage（阶段）

Helm Chart 实现与渲染验证。

## Status（状态）

`completed`

## Scope（范围）

- 在 `deploy/helm/a-stock/` 新增市场环境看板 Helm Chart。
- 保持与 `deploy/k3s/` 一致的单副本、Traefik、PVC、探针、资源与安全约束。
- 在根目录 README 记录首次 Helm 部署和后续镜像更新命令。
- 同步架构、仓库地图、runbook 和仓库状态。

## Acceptance（验收）

- `helm lint --strict deploy/helm/a-stock` 通过。
- `helm template` 可渲染 Deployment、Service、Ingress 和可选 PVC，YAML 可解析且引用闭合。
- values 可覆盖镜像、Ingress host/TLS、持久化、资源、调度和额外环境变量。
- README 包含 `helm upgrade --install` 首次部署命令和 `helm upgrade --reuse-values` 后续更新命令。
- docs-contract 可用检查通过；环境限制或并行工作导致的阻塞已记录。

## Completion Evidence（完成证据）

- Chart：新增 `Chart.yaml`、`values.yaml`、`.helmignore`、helpers、Deployment、Service、Ingress、PVC 和 NOTES 模板。
- 默认渲染：生成 `PersistentVolumeClaim/a-stock-data`、`Service/a-stock`、`Deployment/a-stock` 和 `Ingress/a-stock`；selector、探针、安全上下文与 PVC keep annotation 检查通过。
- 覆盖渲染：自定义仓库/tag、Ingress host/TLS 和 `persistence.existingClaim` 时渲染通过，且不创建新 PVC。
- 降级渲染：关闭 persistence 与 ingress 时只生成 Service/Deployment，数据卷正确变为 `emptyDir`。
- Helm 校验：使用临时 Helm 3.17.3 二进制执行 `helm lint --strict deploy/helm/a-stock`，结果为 `1 chart(s) linted, 0 chart(s) failed`；未安装 Helm、未连接集群、未创建 release。
- README：已记录镜像构建/推送、首次 `helm upgrade --install`、后续 `helm upgrade --reuse-values`、status/history/rollback 命令。
- 文档门禁：隔离临时索引下 docs-contract fast 通过；`SKIP_PLAN_GATE=1` 后 full 的其余规则通过。

## Remaining Gaps（剩余缺口）

- 本机未配置 kubectl/k3s 目标集群，未执行 server-side dry-run、release 安装或 rollout；这符合本任务只创建配置、不实际部署的范围。
- 当前分支既有提交范围仍触发 docs-contract full 的 Gate 3，未带逃生开关的 full 结果受并行 snapshot 工作影响。

## Next Step（下一步）

使用目标环境的镜像仓库、固定 tag、域名/TLS 和凭据 values 执行 README 中的 `helm upgrade --install`；后续发布只更新不可变镜像 tag。
