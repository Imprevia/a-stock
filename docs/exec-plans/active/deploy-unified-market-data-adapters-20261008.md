# 部署统一市场数据采集适配器到 TrueNAS k3s（2026-10-08）

## Stage（阶段）

生产发布前只读发现与调度回退授权准备。

## Status（状态）

authorized-schedule-disable-packet-ready

## Acceptance（验收）

- 将应用候选 `b2dd6898eb79a06a4cff00c2a14213fc0f28648c` 通过 `scripts/deploy-truenas-k3s.sh --component all` 发布到 TrueNAS `192.168.1.20` 的 Helm release `a-stock` / namespace `a-stock`。
- 发布前必须通过受控 `--disable-schedule` 将 exact `a-stock-data-collection` 安全关闭并证明 absent；该操作需操作责任人单独明确授权，禁止裸 `kubectl patch/delete` 或 `helm rollback/uninstall`。
- 普通发布最终值保持 `scheduledCollection.enabled=false`、`suspend=true`，Scrapling 保持 disabled 且生产 allowlist 为空；不启用新的 Fuyao、TDX 或 sector enrichment 开关，不创建 provider-backed Job，不调用刷新接口。
- 不创建、修改或输出 Secret；不删除、替换、扩容、重绑 PostgreSQL/SQLite PVC，不修改生产数据。
- 发布后验证 Helm revision、Deployment/StatefulSet/Pod Ready、精确镜像 tag/digest、NodePort 健康、provider-free GET、两个 exact CronJob absent，并证明两个 PVC 的 UID/PV/容量保持不变。

## Deployment Boundary（部署边界）

- 目标集群：`192.168.1.20`，k3s `v1.26.6+k3s-6a894050-dirty`。
- release / namespace：`a-stock` / `a-stock`。
- 应用候选：`b2dd6898eb79a06a4cff00c2a14213fc0f28648c`；执行生产写入前还需与 `origin/main` 对齐并在 clean、受审 checkout 中运行。
- 普通发布入口：`bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component all`。
- 回退：先确保 exact CronJob absent/suspended，再从受审 rollback commit 构建新的不可变 tag 并重跑同一普通入口；不得恢复历史 Helm revision、卸载 release 或删除 PVC。

## Completion Evidence（完成证据）

- 2026-10-08 只读发现确认节点 `ix-truenas` 为 `Ready`，`k3s` systemd 为 `enabled/active`，集群版本为 `v1.26.6+k3s-6a894050-dirty`。
- 当前 Helm release 为 revision `82`，Dashboard 镜像为 `localhost/a-stock-market-environment:20260930-115139-40c3498`；Deployment `1/1`。
- 当前 exact `a-stock-data-collection` 为 `30 16 * * 1-5`、`suspend=false`，2026-10-08 16:30（Asia/Shanghai）已自然触发 Job。普通应用发布的 off/absent 前置条件不成立，因此未执行镜像构建、传输、containerd 导入或 Helm 写入。
- PostgreSQL PVC `a-stock-postgresql-data` 为 `Bound`，UID `6c426fc5-10e2-4e88-b534-b258c70869c4`、PV `a-stock-postgresql-data`、容量 `5Gi`；旧 SQLite PVC `a-stock-data` 为 `Bound`，UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe`、PV `a-stock-data`、容量 `2Gi`。
- baseline Helm lint 与 Kubernetes `1.26.6` template 通过；合并值为 `scheduledCollection.enabled=false`、`suspend=true`。线上已有的手工刷新、TDX fallback、TDX 派生容量方向和 Fuyao Secret 引用与 baseline 一致，本次不扩大这些开关。
- Git 初次只读预检发现候选 `b2dd689` 尚未推送，随后已按操作责任人要求将代码及本计划提交推送到 `origin/main`；工作树另有用户已有的未跟踪嵌套目录 `a-stock/`。未删除、移动、忽略或提交该目录，生产操作改用独立 clean worktree。
- 2026-10-08 操作责任人明确授权“允许停止后续自动采集”。授权范围为 release `a-stock` / namespace `a-stock` 的受控 `--disable-schedule`，删除 exact Helm-owned `a-stock-data-collection` 并停止后续自动触发；不授权裸 `kubectl`/Helm 写入、provider-backed Job、Secret/PVC/生产数据修改或其他调度变更。
- 调度关闭 packet 使用 reviewed HEAD `eee52eacc5ca9d7a55a423293778133c196a8646`；该提交的 chart、部署脚本、验证器和 off overlay 与 revision 82 激活时的 reviewed HEAD `40c3498c16325ad0962661a841a3efe6d23cb7d2` 一致，并包含已归档的完整 scheduling baseline。
- 冻结镜像为 `localhost/a-stock-market-environment:20260930-115139-40c3498`，containerd manifest digest 为 `sha256:53c1219db808acd6860286725fa77ebda7da40f8dbcbf8e66e001056cfe05883`；chart/baseline/off-overlay/render SHA-256 依次为 `3ad82655fee3d42b6527b75608132e805b0238561101c71e6f9d4b31590fd01a`、`d7e6492934ccf56ebaeb77c3a16e6e1e83ef074d306c8d84f0dc8efb5a68e25c`、`d624601138ca7e803c7e1b7c85c86172fa17f6c1295b5ac49c576924f0fff8ff`、`b03baadde1914dbf23b3c11c96fc0569d811eb312fb7394a94ddf7e204e93ab6`。
- rollback-v1 canonical binding SHA-256 为 `c38c1ce02dd942750a1499b485a408525fa9ef24008c5c03e39aa51dca7c213d`，授权引用为 `rollback-v1:user-20261008-stop-auto-collection:c38c1ce02dd942750a1499b485a408525fa9ef24008c5c03e39aa51dca7c213d`；`--disable-schedule` 不适用 activation catch-up 行为。

## Remaining Gaps（剩余缺口）

- 需从 clean、upstream-aligned rollback worktree 执行受控 `--disable-schedule`，并读回 Helm revision 与 exact CronJob absent 后置条件。
- 普通应用发布必须在调度关闭成功后从 clean、upstream-aligned checkout 执行；不得从包含未跟踪嵌套仓库的工作区构建生产镜像。
- 尚未产生新镜像 tag/digest、Helm revision、发布后资源状态或健康检查证据。

## Next Step（下一步）

先从 clean rollback worktree 执行绑定上述 hashes 的受控 `--disable-schedule` 并证明 CronJob absent；再从最新 `origin/main` clean worktree 执行 `--component all`，最后补齐镜像、Helm、健康、PVC 与调度后置条件并运行 docs-contract full。
