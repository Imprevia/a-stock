# 部署统一市场数据采集适配器到 TrueNAS k3s（2026-10-08）

## Stage（阶段）

生产发布前只读发现与调度回退授权准备。

## Status（状态）

blocked-awaiting-explicit-schedule-disable-authorization

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
- Git 只读预检确认候选 `b2dd689` 尚未推送，`origin/main=b070442`；工作树另有用户已有的未跟踪嵌套目录 `a-stock/`。未删除、移动、忽略或提交该目录。

## Remaining Gaps（剩余缺口）

- 操作责任人尚未明确授权停止并删除当前 active `a-stock-data-collection`；在授权前，受控 `--disable-schedule` 和普通应用发布均保持 NO-GO。
- 需为当前 revision `82` 冻结 exact rollback packet、hash 与运行镜像 digest，取得绑定后的 rollback-only authorization，再在 clean checkout 中执行。
- 候选提交需推送并与 upstream 对齐；不得从包含未跟踪嵌套仓库的工作区构建生产镜像。
- 尚未产生新镜像 tag/digest、Helm revision、发布后资源状态或健康检查证据。

## Next Step（下一步）

等待操作责任人明确授权：停止后续自动采集，并通过受控 `--disable-schedule` 删除 Helm-owned `a-stock-data-collection`。授权后冻结 rollback packet，先证明 CronJob absent，再推送受审候选并从 clean checkout 执行 `--component all`；最后补齐发布后证据与 docs-contract full。
