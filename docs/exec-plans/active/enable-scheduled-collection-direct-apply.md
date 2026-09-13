# Native CronJob 直接 apply 部署市场数据采集

## Stage（阶段）

续接已部署的 operator override，修正 TrueNAS k3s 1.26 controller 时区映射，用独立裸 YAML 将市场数据采集 CronJob 固定到上海工作日 16:30，并验证周末无 provider 冒烟与下一交易日自然触发。

## Status（状态）

`in-progress`

## Scope（范围）

- 在 `a-stock` namespace 下新建一个独立的 `market-environment-data` PVC（2Gi RWO，StorageClass `manual-local`），并按集群静态 PV 模式创建对应 `a-stock-market-environment-data` PV（hostPath `/mnt/xiaomi/app-data/a-stock-market-environment`）。
- 因为集群没有 `manual-local` StorageClass 对象，同名 SC 也需要新建（`provisioner: kubernetes.io/no-provisioner`，`volumeBindingMode: Immediate`，`reclaimPolicy: Retain`）。
- `deploy/k3s-native-scheduled/` 继续只承担 Kubernetes 1.27+ native timezone overlay；不再把其 CronJob 清单改造成 TrueNAS 1.26 专用资源。
- 在 `deploy/truenas/` 增加独立的 k3s 1.26 controller-timezone override 清单：省略 `spec.timeZone`，使用目标 controller 已验证的 `Asia/Shanghai` 本地 schedule `30 16 * * 1-5`，镜像固定为 `localhost/a-stock-market-environment:20260906-005226-2075b6e`。
- 通过 `scripts/apply-truenas-operator-override.sh` 执行 fail-closed 校验：只允许修正已存在且非 Helm-owned 的 exact CronJob；先验证主机/controller 时区、独立 PVC Bound、冻结镜像和安全上下文，再执行 server-side dry-run、可选显式 apply 与 exact readback，不创建/删除/patch PVC/PV/Deployment/Service。
- 通过专用脚本对单文件执行 server-side dry-run 和显式 apply，**不走** `scripts/deploy-truenas-k3s.sh` 的 Helm 发布入口、**不走** Helm release 升级、**不动**既有 `a-stock-data` PVC 与 helm 装的 Deployment/Service。
- 用单独的 `market-data-verify` Job（`snapshots refresh --as-of 2026-09-11 --force`）验证 PVC 挂载、镜像可用、collector 可写 SQLite；不直接派生 CronJob（`scheduled-refresh` 在 settlement time 之前会被 rejected）。
- 在节点上 `mkdir -p /mnt/xiaomi/app-data/a-stock-market-environment` 并 `chmod 0777`，允许非 root 容器（`runAsUser: 10001`）写入 hostPath。
- 同步更新 `docs/runbooks.md` 与 `docs/status.md`。

## Acceptance（验收）

- `docs/exec-plans/active/enable-scheduled-collection-direct-apply.md` 6 个必需字段齐全。
- `docs/runbooks.md` 新增 `### Native CronJob 直接 apply（operator override 路径）` 节，明确记录路径、命名决策、镜像 tag 冻结、与既有 helm release 的隔离边界。
- operator override 必须通过专用脚本完成：默认只读 + server-side dry-run，`--apply` 才允许写入；脚本拒绝缺失 exact CronJob、Helm ownership、时区/PVC/镜像/安全上下文漂移，并在写后 exact readback。
- `docs/status.md` 的 `## 进行中` 列表新增本计划对应条目。
- 集群 `a-stock` namespace 下：
  - `kubectl get cronjob -n a-stock` 出现 `market-data-collection`，`SUSPEND=False`，schedule `30 16 * * 1-5`（controller `Asia/Shanghai`），无 `timeZone` 字段。
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

**时区复核（2026-09-13 09:19 / Asia/Shanghai，修正写入前）:**

- live server 为 k3s `v1.26.6+k3s-6a894050-dirty`；主机 `timedatectl` 与 `/etc/localtime` 均为 `Asia/Shanghai`，k3s systemd 环境没有 `TZ` 覆盖，controller 使用上海本地时区解释无 `spec.timeZone` 的 CronJob。
- live CronJob 仍为 `schedule=30 8 * * 1-5`、`suspend=false`、冻结镜像 digest `sha256:8fc74dcf37f5e6303e42f78811ef9de16759cb6e045aa57648e027cd1449754b`，但创建 45 小时后 `lastScheduleTime` 仍为空，也没有 controller 派生 Job；因此 `30 8` 在本目标实际表示上海 08:30，原“UTC=上海 16:30”假设已被 live 证据否定。
- `market-environment-data` PVC 与 `a-stock-market-environment-data` PV 仍为 `Bound`；节点仍存在冻结镜像。正式 Helm/Gate B/Gate C 链路未被调用，本次只修正既有 override 的 schedule。

**schedule 修正与周末 smoke（2026-09-13 09:24 / Asia/Shanghai）:**

- 新增 `deploy/truenas/market-data-collection-cronjob-1.26-controller-shanghai.yaml`；离线部署清单测试 `179 passed`，YAML 解析确认 `schedule=30 16 * * 1-5`、无 `spec.timeZone`、冻结镜像与独立 PVC 不变。
- server-side dry-run 通过；`kubectl diff` 只包含 generation 与 `spec.schedule: 30 8 * * 1-5 -> 30 16 * * 1-5`。apply 后 live generation 为 2，`suspend=false`、无 `spec.timeZone`，镜像仍为 `localhost/a-stock-market-environment:20260906-005226-2075b6e`。
- PVC UID `ad1d0f69-f64e-4d95-827a-b341f123007c`、PV UID `3f1b6e86-f320-4448-9052-8aa84879adbb` 与绑定关系均未变化；未修改 Helm release、Deployment、Service、Ingress、PVC/PV 或 StorageClass。
- 临时 Job `market-data-weekend-smoke-20260913` 从更新后的 CronJob 派生并完成：Pod `Succeeded`、exit code 0，日志为 `{"asOf":"2026-09-13","datasets":[],"reason":"weekend","status":"skipped","trigger":"scheduled"}`。SQLite 在前后均为 360448 字节、mtime epoch `1789099798`，证明周末路径未写数据；记录证据后已按 exact Job 名称删除。
- 最终 live 读回：CronJob generation 2、`schedule=30 16 * * 1-5`、`suspend=false`、`Forbid`、deadlines `1800/3600`、`backoffLimit=0`、冻结镜像与 `market-environment-data` PVC 均符合清单；传输到目标 `/tmp` 的清单副本已删除。
- 本地验证：`tests/test_deployment_manifests.py` 为 `179 passed`，`python scripts/render-k3s.py --kube-version 1.27.0` 仍输出 native `30 16` + `Asia/Shanghai`，`git diff --check` 与 `python scripts/check-docs-contract.py --mode=full` 均通过。
- 修复前全量离线 pytest 曾为 `576 passed, 1 failed, 2 warnings`；唯一失败是既有 materialized local read 的 0.5 秒性能阈值，现已由独立稳定性计划修复并 supersede。最新全量离线结果为 `592 passed, 2 warnings`。
- 新增 `tests/test_truenas_operator_override.py`，以 fake timedatectl/systemctl/kubectl 覆盖成功 dry-run/apply/readback、缺失/Helm-owned CronJob、时区/PVC/manifest/live 漂移及 apply 后置条件；当前专测结果 `14 passed`。

**本地:**

- active plan 6 字段齐全；`runbooks.md` 新章节；`status.md` 新条目。
- `python3 scripts/check-docs-contract.py --mode=full` 与 `--mode=fast` 均通过（代码 0 / 文档 4-5 / plan 1）。
- shared working tree 仍含不属于本计划的 dirty（`AGENTS.md`、`docs/runbooks.md`、`docs/status.md`、`openspec/changes/...` 的既有 M/A），按 AGENTS.md 不 stash/reset/checkout。

## Remaining Gaps（剩余缺口）

- 本计划未创建 application CronJob 之外的任何集群资源；helm 装的 `a-stock` Deployment 仍跑 `20260906-005226-2075b6e`，本计划不动它。
- shared working tree 不 clean：包含 `AGENTS.md`、`docs/runbooks.md`、`docs/status.md`、`openspec/changes/surface-scheduled-market-collection/tasks.md` 与 `openspec/changes/archive/2026-09-11-surface-scheduled-collection-failclosed-contract/*` 的既有 M/A（这些均非本计划引入），按 AGENTS.md 不 stash/reset/checkout。
- `enable-truenas-scheduled-market-collection` 已取得 GYT-52 Gate A GO，但 Gate B/Gate C 仍需独立 exact action/operation authorization；本计划只是**临时 operator override 路径**而非正式 Helm 发布替代。两套方案通过非 Helm ownership 隔离并存，operator override 也不得绕过专用脚本的 fail-closed 校验。
- 本计划**超出原方案边界的写操作**（operator override 已承担后果）：
  1. 新建集群级 StorageClass `manual-local`（`provisioner: kubernetes.io/no-provisioner`，`Immediate`，`Retain`）。
  2. 新建集群级 PV `a-stock-market-environment-data`（hostPath `/mnt/xiaomi/app-data/a-stock-market-environment`，2Gi RWO，Retain）。
  3. 在节点上 `mkdir -p` + `chmod 0777` 修改主机文件系统权限（与既有 `a-stock-data` 的 `0770 10001:10001` 不一致，更宽松）。
  4. 多次 patch PVC（加 `volumeName`、`storageClassName`）与 PV（加 `claimRef`）。
  5. 早期曾把 Kubernetes 1.27+ native 清单临时改造成 1.26 资源；本阶段改为 `deploy/truenas/` 独立清单，避免两种版本语义继续互相覆盖。
  6. 创建集群级验证 Job `market-data-verify`（与 CronJob 不同的子命令）。
- CronJob 的上海 16:30 自然触发仍**未被验证**：live schedule 已修为 `30 16`，需等待 9 月 14 日自然触发。
- 周末派生 Job 已证明 `scheduled-refresh` 返回 `skipped`、exit 0 且 SQLite 不变，但不能替代交易日 16:30 的 provider-backed 验证。
- 镜像 tag 是手动指定的 `20260906-005226-2075b6e`，未在 controller 上跑过 canary，也未冻结到 `FROZEN_IMAGE_*` 字段；后续若需要持续维护，应迁移到 Helm 或 fail-closed 入口并补齐 controller 证据。
- Pod 的安全属性（non-root、cap drop、read-only rootfs、no token、Forbid、backoffLimit 0、1800/3600 deadlines）继承自 `deploy/k3s-native-scheduled/market-data-collection-cronjob.yaml` 原文件，本计划未调整这些字段。
- 验证 Job `market-data-verify` 与其 Pod 残留 metadata 在 `a-stock` namespace；Job 对象已 `delete`，Pod 会随 GC 清理。
- `market-data-collection` CronJob 当前 `LAST SCHEDULE=<none>`、无活跃 Job；下一次自动触发时间取决于 k8s controller 内部 cron 解析；首次触发后的成功/失败需另起监控窗口观察。

## Next Step（下一步）

1. 等下一个交易日（周一 2026-09-14）16:30 上海由 CronJob 自然触发；观察 Job、Pod 日志和 SQLite mtime，确认真实 collect。
2. 若周一触发失败，保留 partial/failed 证据并评估不可变镜像升级；不得把 `latest` 应用于现有 override。
3. 后续清理既有 `market-data-verify` 残留，并把 override 迁回完成 Gate B/Gate C 的受控 Helm 链路后再归档本计划。
