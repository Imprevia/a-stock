# 优化构建机磁盘容量

## 目标

恢复构建机根分区的安全余量，并让 TrueNAS k3s 部署入口在导出大体积镜像前选择容量充足的临时文件系统、校验可用空间和给出可操作的失败提示，避免再次把根分区写满。

## 范围

包含：清理明确可再生的本机缓存和遗留临时归档、清理 dangling Podman 镜像、只读审计 k3s 节点容量、改进部署脚本临时目录选择与空间门禁、补充测试和运维文档。

排除：删除 Codex 会话、Playwright 浏览器、带标签的回滚镜像、运行中的 PostgreSQL 恢复容器、生产 PVC/Secret/备份，以及扩容 LVM、清理 systemd journal 或修改生产集群资源。

## Stage（阶段）

- 当前阶段：**实现与验证完成，等待提交推送**
- 阶段序列：容量审计 → 低风险回收 → 部署防护 → 离线验证 → 提交推送

## Status（状态）

`implementation-complete-awaiting-commit` · 本机空间回收、k3s 只读审计、部署归档容量门禁、文档与离线验证均已完成，等待提交推送。

## 事实源

- `docs/architecture.md`
- `docs/repository-guide.md`
- `docs/runbooks.md`
- `scripts/deploy-truenas-k3s.sh`
- `deploy/truenas/deploy.env.example`
- `tests/test_truenas_scheduling_guard.py`

## 阶段任务

- [x] 盘点根分区、日志、用户缓存、Podman 存储和部署遗留临时文件
- [x] 清理明确可再生且未被占用的本机空间并记录前后容量
- [x] 只读审计 k3s 节点、容器运行时和 PVC 容量
- [x] 为部署脚本增加可配置临时根目录、容量选择和导出前门禁
- [x] 同步部署环境示例、架构说明与 runbook
- [x] 补充并运行聚焦测试、docs contract 和差异检查
- [ ] 提交并推送代码

## Acceptance（验收）

- 构建机根分区从 99% 降至具备至少 2 GiB 可用空间，且未删除不可再生用户数据或生产资产。
- 部署入口支持显式 `DEPLOY_TMP_ROOT`，未显式配置时只选择可写且容量满足门禁的临时文件系统。
- 镜像导出前按本地镜像体积和安全余量校验目标文件系统；不足时在 `podman save` 前失败并提示配置方式。
- database/schedule 等不执行镜像导出的组件不被临时归档容量门禁误阻塞。
- 聚焦 pytest、全量 docs contract 与 `git diff --check` 通过。

## Completion Evidence（完成证据）

- 本机根分区从 `48G / 45G used / 604MiB available / 99%` 恢复到 `48G / 40G used / 5.8G available / 88%`；inode 原本仅使用 24%，确认问题是数据块容量。
- 精确删除未占用的 `/var/tmp/4167527528`（388,485,632 bytes）及已由本地镜像保留、校验通过的 `/tmp/a-stock-market-environment-20261013-162900-8f0a6bc.tar`（613,585,920 bytes）与 checksum；未删除带标签镜像、运行容器或用户会话。
- `pip cache purge` 删除 1,061 个文件（缓存从约 520 MiB 降到 7.1 MiB）；`uv cache clean` 清空约 1.5 GiB；`npm cache clean --force` 将 `~/.npm` 从约 2.3 GiB 降到 36 MiB；`podman image prune -f` 清理无引用 dangling 层，保留一个仍被镜像层级引用的 448 MiB 父镜像。
- k3s 只读审计：`/mnt/xiaomi` 547G 中可用约 400G、`DiskPressure=False`；应用 PVC 约 5.8 MiB、PostgreSQL PVC 约 39 MiB。未执行远端 tar/containerd 清理，未修改集群、PVC、Secret、CronJob 或数据库备份。
- `bash -n scripts/deploy-truenas-k3s.sh` 通过；`tests/test_truenas_scheduling_guard.py` 为 117 passed；`tests/test_deployment_manifests.py` 为 190 passed；`python scripts/check-docs-contract.py --mode=full` 通过（代码 1 / 文档 5 / plan 1）；`git diff --check` 通过。

## Remaining Gaps（剩余缺口）

- systemd journal 约 3 GiB，但本机 `sudo` 需要交互密码；本计划不绕过权限清理。
- LVM volume group 是否有未分配空间尚无法在无 sudo 条件下确认；扩容属于独立管理员操作。
- TrueNAS 历史镜像归档约 5.7 GiB 实占，但节点尚有约 400G 可用；远端保留/删除策略需要独立授权，本轮不清理。
- 本地归档门禁不覆盖 Podman graphRoot 构建过程或远端 `REMOTE_IMAGE_DIR` 空间，二者仍需独立监控。

## Next Step（下一步）

提交实现与证据文档，记录代码提交 SHA 后推送 `main`。
