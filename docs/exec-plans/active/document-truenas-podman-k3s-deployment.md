# 编写 TrueNAS Podman 到 k3s 部署教程

## Stage（阶段）

部署教程编写与命令校验。

## Status（状态）

`in-progress`

## Scope（范围）

- 新增 TrueNAS SCALE 24.04 + Ubuntu VM + Podman + k3s/containerd + Helm 的完整操作文档。
- 覆盖 VM、SSH、Podman、镜像构建/传输/导入、集群前置检查、首次发布、更新、回滚、备份和故障排查。
- 覆盖市场数据 CronJob 的默认启用、暂停、一次性补跑、日志检查和 partial 恢复。
- 在 `docs/runbooks.md` 增加教程入口。

## Acceptance（验收）

- 教程不要求 TrueNAS 宿主机安装 Docker、Podman 或 BuildKit。
- 镜像名称在 Podman、containerd 和 Helm values 间保持一致，并使用不可变 tag。
- 部署前显式检查 StorageClass、IngressClass、k3s 节点和镜像导入结果。
- 首次部署、后续更新、回滚、卸载和数据保留命令完整。
- Dashboard Deployment 与市场数据 CronJob 使用同一不可变镜像和 PVC，教程能区分其与 GitHub Actions 交易规则证据任务。
- 文档链接和 docs-contract 可用检查通过。

## Completion Evidence（完成证据）

- 待文档完成后回填。

## Remaining Gaps（剩余缺口）

- 当前工作机没有 TrueNAS SCALE 24.04 目标环境，无法执行真实 VM、containerd 导入和 rollout 验证。

## Next Step（下一步）

创建教程并在 runbook 中增加入口，纳入盘后 CronJob 运维步骤，然后执行文档链接和 gate 检查。
