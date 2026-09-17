# controllerCanaryVerified 翻转为 true（基于 2026-09-17 canary 证据）

## Stage（阶段）

续接 [`canary-1-26-controller-timezone-20260917.md`](canary-1-26-controller-timezone-20260917.md) 的现场证据：TrueNAS k3s 1.26.6 controller timezone 已通过一次性诊断 Job 现场确认为 `Asia/Shanghai`、`spec.schedule=30 16 * * 1-5` 在 controller 解释下等价于盘后 16:30 Asia/Shanghai，Pod 退出码 0 且命名空间已回到 baseline。本阶段在 **`suspend=true` 不变**的前提下，把 `deploy/truenas/values-scheduled-baseline-20260917.yaml` 的 `marketEnvironment.scheduledCollection.controllerCanaryVerified` 由 `false` 翻转为 `true`，固化本次 canary 证据；本阶段**不**激活 CronJob，**不**调用 `--activate-schedule` 入口。

## Status（状态）

`completed` · 单字段翻转 `false → true` 已 apply；离线 render 与 docs-contract fast 双通过；live 集群零写入。

## Scope（范围）

- 修改 `deploy/truenas/values-scheduled-baseline-20260917.yaml` 第 51 行：`controllerCanaryVerified: false` → `controllerCanaryVerified: true`。
- 单文件、单字段改动；不修改 `values-scheduled-suspended.yaml` / `values-scheduled-active.yaml` / chart default。
- 改完后用 `helm template` 离线 render 校验：保持 `suspend: true`、无 `spec.timeZone`、schedule `30 16 * * 1-5` 不变；并且不再触发 `controller strategy requires controllerCanaryVerified=true before suspend=false` 失败（本次仍然 `suspend=true`，但字段已对齐）。
- 跑 `python scripts/check-docs-contract.py --mode=fast` 通过。
- 同步 `docs/exec-plans/active/_index.md` 登记本 plan。
- 不在范围：apply / patch / upgrade 到 live 集群；`--activate-schedule` 入口；k3s controller 版本与 baseline `--kube-version` 严格相等；`local main` 领先 `origin/main` 9 个 commit；`FROZEN_IMAGE_*` 收紧；`image.digest` chart 字段加固。

## Acceptance（验收）

- 仓库层：`deploy/truenas/values-scheduled-baseline-20260917.yaml` 第 51 行 `controllerCanaryVerified: true`；其余字段（`enabled: true`、`suspend: true`、`timezoneStrategy: controller`、`timeZone: Asia/Shanghai`、`schedule: "30 16 * * 1-5"`、`controllerTimeZone: Asia/Shanghai`、`controllerTimeZoneVerified: true`）未变；`values-scheduled-suspended.yaml` / `values-scheduled-active.yaml` / `deploy/helm/a-stock/values.yaml` 全部未变。
- 渲染层：`helm template a-stock deploy/helm/a-stock -f deploy/truenas/values-scheduled-baseline-20260917.yaml --set component=schedule --kube-version 1.26.6` 成功输出 `a-stock-data-collection`，`spec.suspend=true`、`spec.schedule=30 16 * * 1-5`、**无** `spec.timeZone` 字段；不出现 `controllerCanaryVerified=true before suspend=false` 失败信息。
- 文档门禁：`python scripts/check-docs-contract.py --mode=fast` 通过；`docs/exec-plans/active/_index.md` 新增本 plan 行。
- 集群层：本阶段对 live 集群零写入；命名空间 `a-stock` 内 `CronJob` / `Job` / `Pod` 状态与 [`canary-1-26-controller-timezone-20260917.md`](canary-1-26-controller-timezone-20260917.md) Completion Evidence 中的"清理后"快照等价。
- plan 6 字段齐全；本 plan 的 Completion Evidence 段记录责任人书面确认 + 离线 render 关键输出 + docs-contract 输出。

## Completion Evidence（完成证据）

- 责任人书面确认：**操作发起人**（2026-09-17 Asia/Shanghai）。以 [`canary-1-26-controller-timezone-20260917.md`](canary-1-26-controller-timezone-20260917.md) Completion Evidence 段中的现场证据（Job `a-stock-timezone-canary-20260917` 在 ix-truenas 上 18s 退出码 0；k3s server pid 635145 无 `TZ` env 覆盖、host `/etc/localtime=Asia/Shanghai`、容器内 `printenv TZ=Asia/Shanghai` + `date`/`datetime`/`zoneinfo` 三口径 +08:00 CST）为基础，授权把 `controllerCanaryVerified: false` 翻转为 `true`。

### `git diff`（只显示本次单字段翻转）

```diff
diff --git a/deploy/truenas/values-scheduled-baseline-20260917.yaml b/deploy/truenas/values-scheduled-baseline-20260917.yaml
index d7dd5e9..ca76995 100644
--- a/deploy/truenas/values-scheduled-baseline-20260917.yaml
+++ b/deploy/truenas/values-scheduled-baseline-20260917.yaml
@@ -48,7 +48,7 @@ marketEnvironment:
     schedule: "30 16 * * 1-5"
     controllerTimeZone: Asia/Shanghai
     controllerTimeZoneVerified: true
-    controllerCanaryVerified: false
+    controllerCanaryVerified: true
```

### `helm template` 离线 render 关键行

```
$ helm template a-stock deploy/helm/a-stock \
    -f deploy/truenas/values-scheduled-baseline-20260917.yaml \
    --set component=schedule --kube-version 1.26.6

kind: CronJob
  name: a-stock-data-collection
  schedule: "30 16 * * 1-5"
  suspend: true
spec:                            # 关键：spec 段内只有 schedule / suspend / concurrencyPolicy /
                                 # startingDeadlineSeconds / successfulJobsHistoryLimit /
                                 # failedJobsHistoryLimit / jobTemplate，**无** timeZone 字段
```

`grep -nE 'timeZone:' /tmp/canary-helm-template.yaml` 无输出（controller strategy 生效）。
chart 模板第 80-81 行 `suspend=false && controllerCanaryVerified=false` 的失败信息**未**出现（因 `suspend=true`，该分支不触发；`controllerCanaryVerified: true` 已对齐未来 `suspend=false` 时的 typed 门槛）。

### docs-contract 门禁

```
$ .venv/bin/python scripts/check-docs-contract.py --mode=fast
docs-contract: 模式 fast
docs-contract: 通过（代码 0 / 文档 3 / plan 2）
```

变更范围：`deploy/truenas/values-scheduled-baseline-20260917.yaml`（M）、`docs/exec-plans/active/_index.md`（M）、`docs/exec-plans/active/canary-1-26-controller-timezone-20260917.md`（A）、`docs/exec-plans/active/canary-verified-20260917.md`（A）。

### `_index.md` 状态行

```
| `canary-1-26-controller-timezone-20260917` | 操作发起人 | completed (canary 范围内) | 2026-09-17 |
| `canary-verified-20260917`                 | 操作发起人 | completed (controllerCanaryVerified 翻转为 true) | 2026-09-17 |
```

### live 集群无写入证据

- 本阶段对 live 集群零写入：未 apply、未 upgrade、未 patch、未 kubectl edit。
- 命名空间 `a-stock` 仍保持 `canary-1-26-controller-timezone-20260917.md` Completion Evidence 中"清理后"快照：`a-stock-data-collection` 唯一 CronJob、`SUSPEND=True / LAST SCHEDULE=<none>`、Pod 集合 `{a-stock-postgresql-0, a-stock-7df764f74-rsx6r}` 1/1 Running、Job 集合为空。

## Remaining Gaps（剩余缺口）

- **k3s controller 版本与 baseline `--kube-version` 不严格相等**——live `v1.26.6+k3s-6a894050-dirty`（GitTreeState=dirty），baseline `--kube-version=1.26.6+k3s1`。本次 canary 不阻断，但激活走 `--activate-schedule` 时该项会 fail-closed。激活前必须二选一：(a) 重打 k3s 为非 dirty 的 `v1.26.6+k3s1`；(b) 把 baseline `--kube-version` 改成与 live `/version` 严格相等的字符串。
- **`local main` 领先 `origin/main` 9 个 commit**（`HEAD=a1a0611...`、`@{u}=0ebf5168...`），`REVIEWED_GIT_HEAD = @{u}` 校验仍未满足。
- **本次不证明首个交易日 16:30 自然触发时 `scheduled-refresh` 会成功调 provider 写 PostgreSQL**；该二次验证需激活后首个交易日 16:30 自然触发后采集。
- live 镜像仍为可变 tag `20260917-113516-b5be526`；`FROZEN_IMAGE_*` 与 `image.digest` chart 字段加固都不在本次范围。
- chart 模板第 80-81 行硬门槛 `suspend=false && controllerCanaryVerified=false` 仅校验 `suspend=false` 那一支；本次 baseline 仍 `suspend=true`，typed 校验不会触碰该分支，但 `controllerCanaryVerified: true` 在下次任何 `suspend=false` 写入路径都会被显式要求——这是预期目标。

## Next Step（下一步）

1. 解决 k3s controller 版本与 baseline `--kube-version` 不严格相等（见 Remaining Gaps）。
2. 处理 `local main` 领先 `origin/main` 9 个 commit（push 或拣出）。
3. 走 `--activate-schedule` 入口，`catch-up=next-schedule`（`immediate-catch-up` 已过 deadline window）。
4. 激活后首个交易日 16:30 观察 Job/Pod、`collection_runs`、五个 dataset quality 与 `/api/market-environment?as_of=<交易日>` 响应。
