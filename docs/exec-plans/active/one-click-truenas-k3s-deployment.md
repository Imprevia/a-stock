# 1.21 一键发布到 TrueNAS k3s

## Stage（阶段）

恢复 1.21 VM 到 TrueNAS k3s API 的受限管理链路，并从同一脚本入口重试部署。

## Status（状态）

`completed`

## Scope（范围）

- 在 1.21 VM 增加一键发布脚本：构建镜像、本地烟测、导出校验、SSH/SCP 传输、1.20 containerd 导入、Helm 发布和 rollout 验证。
- 增加不含密钥的 TrueNAS 环境参数模板，支持固定镜像 tag、实际 StorageClass、Ingress Host、Traefik 入口端口和 CronJob 暂停开关。
- 更新 runbook，记录脚本前提、首次发布、后续更新、Tailscale/NGINX 入口和失败排查。
- 当 TrueNAS 仅允许本机访问 `6443/tcp` 时，通过 SSH 回环隧道访问 k3s API，不扩大局域网防火墙暴露面。

## Acceptance（验收）

- 默认工作目录为 `/home/gyt/a-stock`，但可通过环境文件覆盖。
- 镜像始终使用不可变 tag，并在 Podman、containerd 和 Helm 间保持完整名称一致。
- 脚本使用 SSH 批处理模式和远端非交互 sudo；失败时停止，不跳过校验或 TLS 验证。
- 部署仍保持 Traefik Ingress → ClusterIP Service → 单副本 Deployment → RWO PVC 边界，不修改 NGINX 证书或已有 multica 路由。
- `docs/runbooks.md` 说明首次 CronJob 暂停、内部健康检查、Tailscale 访问 URL 和后续升级命令。

## Completion Evidence（完成证据）

- `bash -n scripts/deploy-truenas-k3s.sh` 通过，`--help` 可正常输出。
- 脚本已覆盖 Podman 构建/烟测、固定 tag、SHA-256、SCP、远端 `k3s ctr` 导入、Helm upgrade、rollout 和入口健康检查。
- `deploy/truenas/deploy.env.example`、`docs/runbooks.md` 与 `.gitignore` 已同步；未把本地 SSH 或证书信息写入仓库。
- `git diff --check` 通过。
- 2026-09-06 实机确认：1.21 为 `192.168.1.21/24`，到 `192.168.1.20` 路由直连；TrueNAS k3s active 并监听 `*:6443`，但 INPUT 规则仅允许 `192.168.1.20/32` 与 `127.0.0.1/32` 后丢弃其他来源。
- 通过 `127.0.0.1:16443 -> SSH -> TrueNAS 127.0.0.1:6443` 验证 Kubernetes API 可用，节点 `Ready`，现有 `a-stock` Pod `1/1 Running`。
- 首次同入口重试确认旧 `STORAGE_CLASS=ix-storage-class` 与现网不符；现网无 StorageClass/IngressClass/Traefik，revision 5 使用静态 `a-stock-data` 与 `NodePort:32001`，脚本已支持复用受版本控制的完整环境 values。
- 第二次重试完成镜像构建、本地 smoke 和 SCP，在远端 SHA-256 校验前停止；校验文件错误携带 1.21 临时绝对路径，已改为仅记录归档文件名。
- 第三次从 `bash scripts/deploy-truenas-k3s.sh` 同一入口完成：归档 SHA-256 通过、containerd 导入成功、Helm revision 6 deployed、Deployment `1/1`、新 Pod `Running`/0 重启。
- 实际镜像为 `localhost/a-stock-market-environment:20260906-001322-1904b66`；Service 保持 `NodePort:32001`，PVC `a-stock-data` 保持 `Bound`/`manual-local`，`MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1`。
- `http://192.168.1.20:32001/api/health` 返回 `{"status":"ok"}`，首页返回 200；脚本退出后 1.21 的 `127.0.0.1:16443` 无监听。

## Remaining Gaps（剩余缺口）

- NGINX 的证书路径、Tailscale Serve 模式和 1.20 Traefik 实际端口必须在目标机按现状配置。
- 当前工作区已有 staged `apps/market-environment-dashboard/package-lock.json` 改动，导致全局 `check-docs-contract.py --mode=fast` 报既有的 docs 映射错误；本任务未回退或覆盖该改动，清理该独立变更后需重新运行 gate。
- NGINX/Tailscale `8443` 外部入口不在本次网络恢复与 k3s 发布范围内，未修改或验证。

## Next Step（下一步）

保持 TrueNAS `6443/tcp` 的本机白名单规则；后续发布继续使用同一脚本入口和受版本控制的 TrueNAS values。若启用外部入口，另行按 NGINX/Tailscale runbook 验证 `8443`。
