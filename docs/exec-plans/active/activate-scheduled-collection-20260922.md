# 重新激活盘后定时采集（2026-09-22）

## Stage（阶段）

生产调度重新激活

## Status（状态）

completed-activation-observation-pending

## Scope（范围）

- 在当前 Helm release `a-stock` / 命名空间 `a-stock` 上重新激活唯一的 `a-stock-data-collection` CronJob。
- 只允许 `spec.suspend: true -> false` 单字段变化；不构建、导入或更换镜像，不创建 canary 或 provider-backed Job。
- 使用 `next-schedule`，让下一次自然工作日 16:30（Asia/Shanghai）触发；本次不追补已过 deadline 的失败运行。

## Acceptance（验收）

- 激活前 live release、CronJob、Deployment、PostgreSQL、PVC、镜像和 Secret 与冻结 packet 一致。
- Helm candidate diff 除 CronJob `spec.suspend` 外无其它变化，写前第二次 activation-window 校验通过。
- 激活后 release 为 deployed，CronJob 为 `suspend=false`，无新 canary/临时 Job，写后 exact resource 读回成功。
- 首个自然触发后的 Job/Pod、五类数据质量、`collection_runs` 和 exact-date API 结果另行观察并保留真实 `partial`/`degraded`/`insufficient` 状态。

## Completion Evidence（完成证据）

- 2026-09-22 00:43（Asia/Shanghai）由本次操作责任人确认并执行；目标为 release `a-stock` / namespace `a-stock`，catch-up 选择 `next-schedule`。
- 当前 live Kubernetes 为 `1.26.6+k3s-6a894050-dirty`；冻结镜像为 `localhost/a-stock-market-environment:20260921-185514-3ac16e8`，containerd manifest digest 为 `sha256:ccf4c654f9f6ee77d1dec1db7167f010167abccaa3d82341113ad183c6d39031`。
- 第一次尝试在 Helm 写入前被 `compare-suspend-only` 安全门禁拒绝，原因是未发布 PostgreSQL annotation 导致候选存在 CronJob 之外的 drift；未发生写入。随后在隔离 clean worktree 中移除该未发布 drift 后重试。
- 第二次受控入口通过 preflight 与 pre-write activation-window 校验：下一触发为 `2026-09-22T16:30:00+08:00`，两次校验均 `allowed=true`，前一触发 deadline 已越过且未执行 catch-up。
- `scripts/deploy-truenas-k3s.sh --activate-schedule` 使用 baseline `values-scheduled-baseline-20260917.yaml` + active overlay `values-scheduled-active.yaml` 完成 atomic Helm upgrade；Helm revision `26` 为 `deployed`。入口确认未构建、导入镜像或创建 canary/provider-backed Job。
- 写后 exact readback：`a-stock-data-collection`，schedule `30 16 * * 1-5`，`suspend=false`，`ACTIVE=<none>`，`LAST SCHEDULE=2026-09-21T08:30:00Z`，镜像与冻结镜像一致。写前后候选差异仅为 CronJob `spec.suspend: true -> false`。
- 写后只读核验：Dashboard Deployment `1/1`、PostgreSQL StatefulSet `1/1`，新 Job 为 0；历史失败 Job `a-stock-data-collection-29828670` 与 `a-stock-data-collection-29832990` 保留，未被本次激活自动重跑。

## Remaining Gaps（剩余缺口）

- 首个自然触发尚未观察；当前历史失败 Job 不因本次激活自动重跑。
- 首次自然触发后的 provider、PostgreSQL collection run、五类 dataset quality 和 exact-date API 证据待补齐。

## Next Step（下一步）

在首个自然工作日 16:30 后观察 Job/Pod、PostgreSQL `collection_runs`、五类 dataset quality 与 exact-date API；失败时保留真实 `partial`/`degraded`/`insufficient` 状态，并按专用回退入口处理。
