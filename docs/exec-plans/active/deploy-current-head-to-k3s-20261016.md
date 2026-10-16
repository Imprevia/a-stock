# 部署当前 main 到 TrueNAS k3s（2026-10-16）

## Stage（阶段）

生产发布与发布后验证已完成。

## Status（状态）

completed-with-production-write

## Scope（范围）

- 将已推送并审阅的 `main` 当前 commit 通过仓库受支持的 TrueNAS k3s 普通发布入口部署到 `a-stock` namespace / Helm release。
- 使用 `--component all`，按 database → schema migration → service → full-release convergence 顺序发布。
- 不创建或激活 Kubernetes CronJob，不执行 provider 采集，不删除或替换 Secret、PVC/PV，不使用 `helm uninstall` 或历史 revision 回滚。

## Acceptance（验收）

- 候选 commit 与 `origin/main` 一致，发布源 worktree 洁净且 `REVIEWED_GIT_HEAD` 精确绑定。
- Helm lint、离线 render 与部署相关测试通过，render 不含 application CronJob。
- 受控入口完成镜像构建、传输、containerd 导入和三阶段 Helm 收敛。
- Deployment rollout 成功且唯一 Ready Pod 的 repo/tag/imageID 与冻结 digest 一致。
- PostgreSQL、PVC、Secret identity、安全上下文、NodePort 及手工/自动化开关保持合同状态；两个历史 CronJob identity 和 namespace Job 在成功后均 absent。
- Dashboard health 与首页检查通过，不触发 provider 或生产采集。

## Completion Evidence（完成证据）

- 发布候选为 clean detached commit `d5e00c2d7223f5734fffcea903284071610e4cb2`，与执行时 `origin/main` 一致；私有 `deploy.env` 和未跟踪嵌套仓库均未进入候选。
- 离线门禁通过：`bash -n scripts/deploy-truenas-k3s.sh`、Helm strict lint、k3s 1.26.6 render 均为 exit 0；`tests/test_deployment_manifests.py` 与 `tests/test_truenas_scheduling_guard.py` 合计 `196 passed`。
- 发布前只读基线为 Helm revision 117、节点 Ready、Dashboard/PostgreSQL `1/1`、两个 PVC Bound、CronJob/Job absent、`manual=0`、`automation=1`。本地旧 values 会反转两个开关，因此没有使用；本次从 revision 117 live values 冻结 baseline，SHA-256 为 `75a47ea1b0971ea75b7eb7ad6d71d1159f6189c31bac857c4d854cfcb35cde5f`。
- 2026-10-16 15:00–15:12 Asia/Shanghai 使用受支持的 `scripts/deploy-truenas-k3s.sh --component all` 入口完成发布。镜像为 `localhost/a-stock-market-environment:20261016-150003-d5e00c2`，archive SHA-256 `f62a1521010eebf6e48e8a4a049a6670b8c917f88c4b095c749d5bed6f1d94ee`，containerd manifest digest `sha256:7002bcd6f90ef2e38d69a2ec69d47707bb23df0220f496864778abcc96a479ad`。
- database/service/final convergence 分别完成 revision 118/119/120；schema hook 只在 database 阶段执行一次并成功清理，最终 schema/Alembic 为 `11 / 0008_collection_idempotency`，namespace CronJob/Job absent。
- Deployment `a-stock` 为 `1/1`，Pod `a-stock-67ddc86b78-nfntc` Ready、0 restart，运行时 imageID 为 `sha256:232d3afbf357d185a53a1a51fc165ce316aeed56ead87688ba48560d2ec18e1a`；PostgreSQL `1/1`、0 restart。
- 发布后 `http://192.168.1.20:32001/api/health` 与首页均为 HTTP 200，health body 为 `{"status":"ok"}`。`manual=0`、`automation=1`、NodePort `32001`、两个 PVC UID 与两个 Secret UID 均保持既有合同状态；未调用 provider、未触发采集、未创建 CronJob。
- 发布启动曾尝试以 `/dev/fd` 传入环境文件，因普通文件检查在任何 SSH、构建或集群写入前退出；随后改用不含密钥的 `/tmp` 包装配置引用既有私有配置，未复制或回显凭据。

## Remaining Gaps（剩余缺口）

- 无本次部署范围内缺口。业务数据采集与 Hermes 调度观察属于既有独立运行流程，本次未触发。

## Next Step（下一步）

维持常规只读健康观察；如需回滚，检出受审 rollback commit 并使用新的不可变 tag 重跑 `service` 或 `all`，不得使用 `helm uninstall`、删除 PVC 或直接恢复历史 revision。
