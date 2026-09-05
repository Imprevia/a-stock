# 1.21 一键发布到 TrueNAS k3s

## Stage（阶段）

部署自动化脚本、TrueNAS 环境参数模板与运维文档。

## Status（状态）

`completed`

## Scope（范围）

- 在 1.21 VM 增加一键发布脚本：构建镜像、本地烟测、导出校验、SSH/SCP 传输、1.20 containerd 导入、Helm 发布和 rollout 验证。
- 增加不含密钥的 TrueNAS 环境参数模板，支持固定镜像 tag、实际 StorageClass、Ingress Host、Traefik 入口端口和 CronJob 暂停开关。
- 更新 runbook，记录脚本前提、首次发布、后续更新、Tailscale/NGINX 入口和失败排查。

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

## Remaining Gaps（剩余缺口）

- 当前工作机没有目标 1.20/1.21 环境，无法执行真实 Podman 构建、远端 containerd 导入、Helm rollout 或 NGINX reload。
- NGINX 的证书路径、Tailscale Serve 模式和 1.20 Traefik 实际端口必须在目标机按现状配置。
- 当前工作区已有 staged `apps/market-environment-dashboard/package-lock.json` 改动，导致全局 `check-docs-contract.py --mode=fast` 报既有的 docs 映射错误；本任务未回退或覆盖该改动，清理该独立变更后需重新运行 gate。

## Next Step（下一步）

在目标 1.21 配置 `deploy/truenas/deploy.env`，执行脚本完成首次发布；确认 CronJob 后将 `SCHEDULED_COLLECTION_SUSPEND` 改为 `false`，再按 NGINX/Tailscale 现状启用外部入口。
