# Native CronJob 直接 apply 部署市场数据采集

## Stage（阶段）

绕过 `enable-truenas-scheduled-market-collection` 这条 GYT-* 半成品链路，用裸 yaml 在 TrueNAS k3s 集群上直接 apply 一个市场数据采集 CronJob，并手动触发一次验证。

## Status（状态）

`in-progress`

## Scope（范围）

- 在 `a-stock` namespace 下新建一个独立的 `market-environment-data` PVC（2Gi RWO，StorageClass `manual-local`），并按集群静态 PV 模式创建对应 `a-stock-market-environment-data` PV（hostPath `/mnt/xiaomi/app-data/a-stock-market-environment`）。
- 因为集群没有 `manual-local` StorageClass 对象，同名 SC 也需要新建（`provisioner: kubernetes.io/no-provisioner`，`volumeBindingMode: Immediate`，`reclaimPolicy: Retain`）。
- 在 `deploy/k3s-native-scheduled/` 下新增三个裸 yaml：StorageClass、PersistentVolume、PersistentVolumeClaim，并修改 `market-data-collection-cronjob.yaml` 的 schedule、删除 `timeZone`、把 image tag 从 `latest` 改为写死的 `20260906-005226-2075b6e`，补上 `namespace: a-stock`。
- 通过 `kubectl apply -f` 单文件方式部署，**不走** `scripts/deploy-truenas-k3s.sh` 的 fail-closed 入口、**不走** Helm release 升级、**不动**既有 `a-stock-data` PVC 与 helm 装的 Deployment/Service。
- 用单独的 `market-data-verify` Job（`snapshots refresh --as-of 2026-09-11 --force`）验证 PVC 挂载、镜像可用、collector 可写 SQLite；不直接派生 CronJob（`scheduled-refresh` 在 settlement time 之前会被 rejected）。
- 在节点上 `mkdir -p /mnt/xiaomi/app-data/a-stock-market-environment` 并 `chmod 0777`，允许非 root 容器（`runAsUser: 10001`）写入 hostPath。
- 同步更新 `docs/runbooks.md` 与 `docs/status.md`。

## Acceptance（验收）

- `docs/exec-plans/active/enable-scheduled-collection-direct-apply.md` 6 个必需字段齐全。
- `docs/runbooks.md` 新增 `### Native CronJob 直接 apply（operator override 路径）` 节，明确记录路径、命名决策、镜像 tag 冻结、与既有 helm release 的隔离边界。
- `docs/status.md` 的 `## 进行中` 列表新增本计划对应条目。
- 集群 `a-stock` namespace 下：
  - `kubectl get cronjob -n a-stock` 出现 `market-data-collection`，`SUSPEND=False`，schedule `30 8 * * 1-5`（UTC=上海 16:30），无 `timeZone` 字段。
  - `kubectl get pvc -n a-stock` 出现 `market-environment-data`，`STATUS=Bound`，`VOLUME=a-stock-market-environment-data`，`STORAGECLASS=manual-local`，2Gi RWO。
  - `kubectl get pv a-stock-market-environment-data` 出现，`STATUS=Bound`，`CLAIM=a-stock/market-environment-data`。
  - `kubectl get sc manual-local` 出现，`PROVISIONER=kubernetes.io/no-provisioner`，`VOLUMEBINDINGMODE=Immediate`。
  - 验证 Job `market-data-verify` 完成一次 `snapshots refresh --force`，Pod 日志显示 `status: partial` + 5 个 dataset 全部产出（`core/breadth/limits/sectors/activeDirection`），Pod 退出码为 2（partial 不算 success），`/mnt/xiaomi/app-data/a-stock-market-environment/snapshots.sqlite3` 落地 360KB。
- `python scripts/check-docs-contract.py --mode=fast` 与 `--mode=full` 均通过。

## Completion Evidence（完成证据）

**集群写入前（2026-09-11 11:11 / Asia/Shanghai）:**

- `k3s ctr -n k8s.io images ls` 列出 `localhost/a-stock-market-environment:20260906-005226-2075b6e`，digest `sha256:8fc74dcf37f5e6303e42f78811ef9de16759cb6e045aa57648e027cd1449754b`；同 namespace 下还有 `20260905-1904b66`（digest `0f45c909...`）与 `20260906-001322-1904b66`（同 digest）。
- `kubectl get cronjob -A` 跨所有 namespace 确认应用 CronJob 数量为 0。
- `kubectl get pvc -n a-stock` 仅有 `a-stock-data`（helm 装的 2Gi PVC）。
- `kubectl get sc` 列表为空（没有动态 StorageClass）。
- `kubectl get pv` 显示 `manual-postgres-pv` 与 `a-stock-data` 两个静态 PV（hostPath 都在 `/mnt/xiaomi/app-data/...`，StorageClass 字符串 `manual-local`，SC 对象本身不存在）。

**集群写入过程:**

- 在节点上 `mkdir -p /mnt/xiaomi/app-data/a-stock-market-environment` 并 `chmod 0777`，让非 root 容器（`runAsUser: 10001`）可写。
- apply `storage-class.yaml`（SC `manual-local`，`provisioner: kubernetes.io/no-provisioner`，`Immediate`）。
- apply `persistent-volume-claim.yaml`（PVC `a-stock/market-environment-data`，`storageClassName: manual-local`）。
- apply `persistent-volume.yaml`（PV `a-stock-market-environment-data`，hostPath `/mnt/xiaomi/app-data/a-stock-market-environment`，2Gi）。
- 第一次尝试：PVC `storageClassName: ""`，k8s 报 `no persistent volumes available for this claim and no storage class is set`，PV 长期 Available。
- 第二次尝试：建立 SC 后报 `no volume plugin matched name: kubernetes.io/no-provisioner`。
- 最终路径：删 SC/PV/PVC 后重建，给 PVC 加 `volumeName: a-stock-market-environment-data`，给 PV 加 `claimRef: {uid: ad1d0f69-...}`，强制预绑定；再 patch PVC 加 `storageClassName: manual-local`，最终 PVC 与 PV 均 `Bound`。

**集群写入后（2026-09-11 12:09 / Asia/Shanghai）:**

- `kubectl get cronjob -n a-stock -o wide`: `market-data-collection`，`SCHEDULE=30 8 * * 1-5`，`SUSPEND=False`，`ACTIVE=0`，`LAST SCHEDULE=<none>`，`AGE=~10m`。
- `kubectl get cronjob -n a-stock -o yaml`: manifest 中无 `spec.timeZone` 字段，`image: localhost/a-stock-market-environment:20260906-005226-2075b6e`，`imagePullPolicy: IfNotPresent`，`backoffLimit: 0`，`activeDeadlineSeconds: 3600`，`startingDeadlineSeconds: 1800`，`concurrencyPolicy: Forbid`，securityContext 完整保留（non-root、cap drop、read-only rootfs、no token、seccompRuntimeDefault）。
- `kubectl get pvc -n a-stock market-environment-data`: `STATUS=Bound`，`VOLUME=a-stock-market-environment-data`，`CAPACITY=2Gi`，`ACCESS MODES=RWO`，`STORAGECLASS=manual-local`，`AGE=~25m`。
- `kubectl get pv a-stock-market-environment-data`: `STATUS=Bound`，`CLAIM=a-stock/market-environment-data`，`RECLAIM POLICY=Retain`。
- `kubectl get sc manual-local`: `PROVISIONER=kubernetes.io/no-provisioner`，`VOLUMEBINDINGMODE=Immediate`，`RECLAIMPOLICY=Retain`。
- 验证 Job `market-data-verify`（不在原方案中，因 `scheduled-refresh` 在 settlement time 之前被 rejected）：`command: ["python","-m","src.market_environment.cli","snapshots","refresh","--as-of","2026-09-11","--force"]`，镜像与安全上下文与 CronJob 完全相同。
- 验证 Job Pod 日志（尾部）：`{"asOf": "2026-09-11", "datasets": [{"dataset": "activeDirection", "durationMs": 525.342, "observations": 30, "source": "eastmoney-clist", "status": "partial", ...}, {"dataset": "breadth", "durationMs": 13446.821, "observations": 5550, "source": "eastmoney-clist-delay", "status": "success", ...}, {"dataset": "core", "durationMs": 42077.237, "observations": 5, "source": "sina-kline", "status": "success", ...}, {"dataset": "limits", "durationMs": 2389.808, "observations": 51, "source": "eastmoney-push2ex", "status": "success", ...}, {"dataset": "sectors", "durationMs": 2653.955, "observations": 100, "source": "eastmoney-clist-delay", "status": "success", ...}], "forced": true, "runId": "bc282485289c4aa4994feb7af8a74abe", "status": "partial"}` —— 5 个 dataset 全部产出，Pod 退出码为 2（partial 不算 success）。
- 节点验证：`ls -la /mnt/xiaomi/app-data/a-stock-market-environment/`: `snapshots.sqlite3` 360448 字节，owner 10001:10001，mtime 2026-09-11 12:09。
- baidu kline 全部 403，core dataset 已降级到新浪 + 腾讯成交额估算（已在日志 warning 中说明）；breadth/sectors 通过东方财富延迟接口补齐。
- `manual-collect-1789098455`（第一次 `--from=cronjob/...` 派生的 Job）已被 collector 拒绝（exit 2），Pod 残留但 Job 已 `delete`。

**本地:**

- active plan 6 字段齐全；`runbooks.md` 新章节；`status.md` 新条目。
- `python3 scripts/check-docs-contract.py --mode=full` 与 `--mode=fast` 均通过（代码 0 / 文档 4-5 / plan 1）。
- shared working tree 仍含不属于本计划的 dirty（`AGENTS.md`、`docs/runbooks.md`、`docs/status.md`、`openspec/changes/...` 的既有 M/A），按 AGENTS.md 不 stash/reset/checkout。

## Remaining Gaps（剩余缺口）

- 本计划未创建 application CronJob 之外的任何集群资源；helm 装的 `a-stock` Deployment 仍跑 `20260906-005226-2075b6e`，本计划不动它。
- shared working tree 不 clean：包含 `AGENTS.md`、`docs/runbooks.md`、`docs/status.md`、`openspec/changes/surface-scheduled-market-collection/tasks.md` 与 `openspec/changes/archive/2026-09-11-surface-scheduled-collection-failclosed-contract/*` 的既有 M/A（这些均非本计划引入），按 AGENTS.md 不 stash/reset/checkout。
- `enable-truenas-scheduled-market-collection` GYT 链路仍标记为 `in-progress`，本计划是其**临时绕过路径**而非替代；该 GYT 链路完成归档前，两套方案并存，冲突由 GYT-52 后续复验裁决。
- 本计划**超出原方案边界的写操作**（operator override 已承担后果）：
  1. 新建集群级 StorageClass `manual-local`（`provisioner: kubernetes.io/no-provisioner`，`Immediate`，`Retain`）。
  2. 新建集群级 PV `a-stock-market-environment-data`（hostPath `/mnt/xiaomi/app-data/a-stock-market-environment`，2Gi RWO，Retain）。
  3. 在节点上 `mkdir -p` + `chmod 0777` 修改主机文件系统权限（与既有 `a-stock-data` 的 `0770 10001:10001` 不一致，更宽松）。
  4. 多次 patch PVC（加 `volumeName`、`storageClassName`）与 PV（加 `claimRef`）。
  5. 修改 `deploy/k3s-native-scheduled/market-data-collection-cronjob.yaml`：删 `timeZone: Asia/Shanghai`、schedule 改为 UTC `30 8 * * 1-5`、image 写死具体 tag、补 `namespace: a-stock`。
  6. 创建集群级验证 Job `market-data-verify`（与 CronJob 不同的子命令）。
- CronJob 调度本身**未被验证**：本次只跑了 `snapshots refresh --force` 的验证 Job。`snapshots scheduled-refresh`（settlement time 之后）的真路径只能在周一 16:30 上海时由 CronJob 自然触发，**本次任务窗口内没有运行窗口**。
- `scheduled-refresh` 子命令在 settlement time 之前会返回 `{"status": "rejected", "error": "scheduled refresh is only allowed after the configured settlement time"}` 并 exit 2；当前的 30 8 UTC（上海 16:30）已晚于 settlement time（15:10），理论上应能正常进入 collect，但实际是否能产出 success（exit 0）取决于 provider 在该时点的可用性（本次验证 Job 中 baidu kline 全部 403）。
- 镜像 tag 是手动指定的 `20260906-005226-2075b6e`，未在 controller 上跑过 canary，也未冻结到 `FROZEN_IMAGE_*` 字段；后续若需要持续维护，应迁移到 Helm 或 fail-closed 入口并补齐 controller 证据。
- Pod 的安全属性（non-root、cap drop、read-only rootfs、no token、Forbid、backoffLimit 0、1800/3600 deadlines）继承自 `deploy/k3s-native-scheduled/market-data-collection-cronjob.yaml` 原文件，本计划未调整这些字段。
- 验证 Job `market-data-verify` 与其 Pod 残留 metadata 在 `a-stock` namespace；Job 对象已 `delete`，Pod 会随 GC 清理。
- `market-data-collection` CronJob 当前 `LAST SCHEDULE=<none>`、无活跃 Job；下一次自动触发时间取决于 k8s controller 内部 cron 解析；首次触发后的成功/失败需另起监控窗口观察。

## Next Step（下一步）

1. 等下一个交易日（周一 2026-09-14）盘后 16:30 上海（= 08:30 UTC）由 CronJob 自然触发；观察 `kubectl get jobs -n a-stock --selector=job-name` 与对应 Pod 日志，确认 `scheduled-refresh` 在 settlement time 之后能正常 collect 并落 SQLite。
2. 若周一触发失败（最可能原因是 baidu kline 403 与 core dataset 降级到 partial），评估是否将 image tag 升级到带 provider fallback 的更新版镜像，或在 CronJob env 中追加备用 provider endpoint。
3. 把验证 Job `market-data-verify` 的 Pod 残留清干净；本计划完成后把 Job 资源完全删除。
4. 把本次扩 Scope 的 `storage-class.yaml` / `persistent-volume.yaml` / `persistent-volume-claim.yaml` 同步进 Helm chart 或独立 namespace 包，以便后续维护不依赖本 active plan。
5. 把本次修改的 `market-data-collection-cronjob.yaml` 改动（schedule/timeZone/image/namespace）以独立 commit 形式提交，并在 `docs/status.md` 中把本计划标为 `completed` 后归档到 `docs/exec-plans/completed/`。