# 部署到 192.168.1.20 k3s

## Stage（阶段）

目标集群适配、发布与验证。

## Status（状态）

`completed`

## Scope（范围）

- 兼容目标 TrueNAS k3s 1.26 集群无默认 StorageClass、IngressClass 和 Traefik 的现状。
- 使用静态本地 PV/PVC 保存 SQLite，并通过独立 NodePort 暴露 Dashboard。
- 构建不可变镜像、导入目标节点、执行 Helm 发布并验证健康、日志与持久卷。

## Acceptance（验收）

- Helm Chart 在 Kubernetes 1.26 且关闭定时采集时可安装。
- Service 可显式配置 NodePort，默认 ClusterIP 行为不变。
- 工作负载以非 root 单副本运行，PVC 为 Bound，健康探针通过。
- 从 `192.168.1.20` 的 NodePort 可访问 `/api/health` 与首页。
- docs-contract full gate 通过，并记录部署版本、资源状态与剩余风险。

## Completion Evidence（完成证据）

- 部署清单测试 `6 passed`，Helm strict lint 与 Kubernetes 1.26 render 通过。
- `python scripts/check-docs-contract.py --mode=full` 使用仓库 `.venv` 运行通过。
- 不可变镜像 `localhost/a-stock-market-environment:20260905-1904b66` 构建并完成本地非 root 健康 smoke，归档 SHA-256 为 `706f6fd568fc166db713835f095363334f3d89df6f34709b47a1fa816769466a`。
- Helm release `a-stock` revision 1 在 `192.168.1.20` 部署成功：Deployment `1/1`、Pod `Running`/0 重启、PVC `Bound`、NodePort `32001`。
- `http://192.168.1.20:32001/api/health` 返回 200/`{"status":"ok"}`，首页返回 200；未认证采集 POST 返回 403。
- Pod 以 UID 10001、只读根文件系统运行，持久目录为 `10001:10001`/`0770`。

## Remaining Gaps（剩余缺口）

- 目标集群为 Kubernetes 1.26，不支持 CronJob `spec.timeZone`，盘后定时采集保持关闭。
- 目标集群没有 Ingress Controller；当前仅提供局域网 HTTP NodePort，不提供域名与 TLS。
- npm 构建审计报告 7 个现有依赖漏洞（4 moderate、1 high、2 critical），需单独评估升级兼容性。

## Next Step（下一步）

由集群负责人决定升级到 Kubernetes 1.27+ 后启用盘后 CronJob，或为 1.26 设计不依赖 `spec.timeZone` 的调度策略；另行接入 TLS/认证入口。
