# 激活 scheduled collection（2026-09-17 patch through --activate-schedule）

## Stage（阶段）

续接 [`canary-verified-20260917.md`](canary-verified-20260917.md) + [`canary-1-26-controller-timezone-20260917.md`](canary-1-26-controller-timezone-20260917.md)：TrueNAS k3s 上 `a-stock-data-collection` 仍 `suspend=true`，但 `controllerCanaryVerified: true` 已写入 baseline 并推到 `origin/main`，controller timezone canary 已现场确认 `Asia/Shanghai`。本阶段在 live 集群上把 `suspend` 翻转为 `false`，**不**改任何其它字段，**不**创建新 CronJob 模板，**不**修改镜像，**不**走 schema migration；只通过受控的 `--activate-schedule` 入口做 release-level `suspend: true → false` 单字段切换。

## Status（状态）

`completed` · `--activate-schedule` 单步激活成功：rev 21 `deployed`、`SUSPEND=False / ACTIVE=0 / LAST SCHEDULE=<none>`、CronJob spec 仅 `suspend: true → false` 单字段变化、其它字段与 rev 20 等价、Pod 集合不变、Job 集合空。

## Scope（范围）

激活走**单步 `--activate-schedule`**，原因：read-only-discovery + dry-run `compare-suspend-only` 显示 live release stored manifest（rev 20）与 baseline + active overlay 渲染产物的差异**仅**为 CronJob `spec.suspend: true → false`：

- `a-stock` Helm release 已在 rev 20（`Mon Sep 17 12:12:24 2026 deployed`，合并所有权 plan 写入）含 suspended CronJob `a-stock-data-collection`。
- `controllerCanaryVerified` 在 chart 模板 `market-data-collection-cronjob.yaml` 中**只作 fail-gate**（行 19-20、63-64、80-81），**不渲染进 CronJob spec**。所以 live stored manifest（`controllerCanaryVerified=false`）与 desired render packet（`controllerCanaryVerified=true`，但**不在 spec 内**）的 CronJob spec 在 `compare-suspend-only` 视角下**完全相同**（除 `suspend` 字段）。
- `compare-add-suspended`（`--release-suspended` 入口用）要求 current 列表无 CronJob——但 rev 20 已有，所以 `--release-suspended` fail closed（"suspended release requires the application CronJob to be absent"）。这条路被堵。
- dry-run 证据：`python scripts/validate-scheduling-packet.py compare-suspend-only --release-name a-stock --namespace a-stock --current /tmp/current.yaml --desired /tmp/desired.yaml` exit 0（2026-09-17 Asia/Shanghai，由操作发起人跑）；`current.yaml` = `helm get manifest a-stock -n a-stock`（406 行，6 资源）、`desired.yaml` = `helm template a-stock deploy/helm/a-stock -f .../baseline-20260917.yaml -f .../active.yaml --kube-version 1.26.6 --namespace a-stock`（118 行，6 资源 + 1 helm hook Job）。

### 准备动作（已完成，证据见 §A / §B / §C）

- ✅ 跑 `bash scripts/deploy-truenas-k3s.sh --read-only-discovery`（2026-09-17 Asia/Shanghai）—— 见 §A。
- ✅ 计算 4 个 SHA + frozen image 三元组 —— 见 §B。
- ✅ 跑 dry-run `compare-suspend-only` 确认 single-step 路径合法 —— 见 §A。
- ✅ 跑 `bash scripts/deploy-truenas-k3s.sh --release-suspended` 探针（2026-09-17 Asia/Shanghai）—— fail closed，与上面分析一致；已记入 §C。
- ⏳ 由本次操作责任人**单次书面"go"**后跑 `bash scripts/deploy-truenas-k3s.sh --activate-schedule --baseline-values deploy/truenas/values-scheduled-baseline-20260917.yaml --scheduling-overlay deploy/truenas/values-scheduled-active.yaml --kube-version 1.26.6+k3s-6a894050-dirty`（env `ACTIVATION_CATCH_UP_MODE=next-schedule`、`FROZEN_IMAGE_REPOSITORY/TAG/DIGEST` 走命令前 env 注入，不污染 `deploy/truenas/deploy.env`）。
- 写前第二次时间窗校验（`validate_activation_window pre-helm-write`）。
- 写后读取 live CronJob，校验 `spec.suspend=false`、`LAST SCHEDULE` 已写入下一个交易日 16:30 Asia/Shanghai、其它字段不变；写后 `helm get values a-stock -n a-stock` 中 `controllerCanaryVerified: true`（被 baseline 写进 stored values）、`suspend: false`。
- 不在范围：解除 `values-secure-manual-collection.yaml` 的 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1` 绑定；改镜像；改 chart；走 schema migration；跑任何"裸 `kubectl patch`/apply/edit`"绕过入口。

## Acceptance（验收）

- 仓库层：`docs/exec-plans/active/_index.md` 登记本 plan；本 plan 6 字段齐全。
- 只读发现：live `helm history a-stock -n a-stock` 显示最近一次成功 release 与本次 baseline 镜像一致；`helm get values a-stock -n a-stock` 与 `values-scheduled-baseline-20260917.yaml` 渲染前输入等价（`enabled=true / suspend=true / controllerCanaryVerified=true` 不漂移）；live `cronjob` 仍 `SUSPEND=True / LAST SCHEDULE=<none>`；live `CronJob` 镜像为 `localhost/a-stock-market-environment:20260917-113516-b5be526`。
- SHA 与 frozen image：4 个 SHA 与 frozen image digest 写入本 plan 的 Completion Evidence 段；`--activate-schedule` 入口在 preflight + 写前第二次校验时一致。
- 集群层（写后）：`kubectl -n a-stock get cronjob a-stock-data-collection -o wide` 显示 `SUSPEND=False / ACTIVE=0 / LAST SCHEDULE=<none>`（下个交易日 16:30 触发前）；`/spec` 仅 `suspend: true → false` 单字段变化；image、PVC、Service、PostgreSQL Secret 均未变。✅ 已验证（见 §D）。
- 命名空间层：live `a-stock` 内仍只有 `a-stock-data-collection` 一个 CronJob，PostgreSQL `1/1`，Dashboard `1/1`；无新 Job / Pod 残留（激活后首个交易日 16:30 才会自然触发）。
- 文档门禁：`python scripts/check-docs-contract.py --mode=fast` 通过。
- 沟通：本次操作责任人书面确认时间与确认范围写进本 plan 的 Completion Evidence 段；激活后首个交易日 16:30 观察清单在 Next Step 列出。

## Completion Evidence（完成证据）

> Step 1 / Step 2 写后回填（写前只读发现已抓齐，见下方 §A）。

### §A · read-only-discovery（写前只读发现，runbook 第 41 行硬要求）

- 责任人书面确认（操作发起人，2026-09-17 Asia/Shanghai）：授权 `--read-only-discovery` 入口（只读、不写、不需额外授权）。
- 调用：`bash scripts/deploy-truenas-k3s.sh --read-only-discovery`（exit 0）
- 脚本首行日志：`[a-stock-deploy] read-only discovery: Kubernetes 1.26.6+k3s-6a894050-dirty`（与 live `kubectl version` Server Version 字串严格相等）
- `helm history a-stock -n a-stock` 最近 5 行：
  | REVISION | UPDATED                  | STATUS     | CHART       | DESCRIPTION |
  | 16       | Thu Sep 17 11:20:02 2026 | failed     | a-stock-0.1.1 | Rollback "a-stock" failed: no Service with the name "a-stock" found |
  | 17       | Thu Sep 17 11:21:02 2026 | failed     | a-stock-0.1.1 | Upgrade "a-stock" failed: context deadline exceeded |
  | 18       | Thu Sep 17 11:26:03 2026 | failed     | a-stock-0.1.1 | Release "a-stock" failed: context deadline exceeded |
  | 19       | Thu Sep 17 11:48:17 2026 | superseded | a-stock-0.1.1 | Upgrade complete |
  | 20       | Thu Sep 17 12:12:24 2026 | **deployed** | a-stock-0.1.1 | **Upgrade complete** |
- `helm get values a-stock -n a-stock --all` 关键字段（**live stored values 仍为 `controllerCanaryVerified: false`**，这正是要分两步激活的原因）：
  - `image.repository = localhost/a-stock-market-environment`
  - `image.tag = 20260917-113516-b5be526`
  - `image.pullPolicy = IfNotPresent`
  - `database.enabled = true`、`database.existingSecret = a-stock-postgresql`、`database.image.digest = sha256:9a70e4d1c03a5066080292db2dd95ee3965d3651316e21989fa0935afb8ce8ca`（postgres 16.4）
  - `database.persistence.storageClass = local-path`、`database.persistence.size = 5Gi`、`database.persistence.accessModes[0] = ReadWriteOnce`
  - `persistence.existingClaim = a-stock-data`、`persistence.storageClass = local-path`、`persistence.size = 2Gi`
  - `marketEnvironment.scheduledCollection.enabled = true`、`suspend = true`、`schedule = 30 16 * * 1-5`、`controllerTimeZone = Asia/Shanghai`、`controllerTimeZoneVerified = true`、`controllerCanaryVerified = false`、`activeDeadlineSeconds = 3600`、`startingDeadlineSeconds = 1800`
  - `marketEnvironment.timezone = Asia/Shanghai`、`settlementTime = "15:10"`
  - `extraEnv = [{name: MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED, value: "1"}]`
  - `service.type = NodePort`、`service.nodePort = 32001`、`service.port = 80`、`ingress.enabled = false`
- live `kubectl -n a-stock get cronjob,job,pod,svc,pvc` 摘要（与 canary-1-26 plan Completion Evidence 一致）：`a-stock-data-collection` 唯一 CronJob，`SUSPEND=True / LAST SCHEDULE=<none>`，镜像 `localhost/a-stock-market-environment:20260917-113516-b5be526`；Pod 集合 `{a-stock-postgresql-0, a-stock-7df764f74-rsx6r}` 均 1/1 Running；PVC 集合 `{a-stock-data, a-stock-postgresql-data}` 均 Bound；Job 集合空。
- **新发现（影响激活路径）**：`controllerCanaryVerified` 在 chart 模板 `market-data-collection-cronjob.yaml` 中**只作 fail-gate 使用**（行 19-20、63-64、80-81 处的 `fail` 调用），**不渲染进 CronJob spec**。所以 live stored manifest 与 desired render packet 的 CronJob spec 在 `controllerCanaryVerified` 字段上**没有差异**——`compare-suspend-only` 校验只看 `suspend` 字段变化（除该字段外 spec 完全相同），通过。
- **新发现（影响计划步骤）**：`--release-suspended` 入口的 `compare-add-suspended` 校验 `current` 列表**不能含 CronJob**，而 `a-stock` release rev 20 已经含 suspended CronJob（合并所有权 plan 通过 `--release-suspended` 入口在 2026-09-17 12:12 创建的），所以 `suspended release requires the application CronJob to be absent` fail closed。激活路径从原计划"先 `--release-suspended` 后 `--activate-schedule`"修正为**单步 `--activate-schedule`**，因为：
  - stored manifest 已含 suspended CronJob；
  - `controllerCanaryVerified` 不在 CronJob spec；
  - dry-run `python scripts/validate-scheduling-packet.py compare-suspend-only --release-name a-stock --namespace a-stock --current helm-get-manifest --desired baseline+active-overlay-render` exit 0（2026-09-17 Asia/Shanghai，由操作发起人跑）。
- 完整 191 行日志已留存到 `/tmp/a-stock-canary/ro-disc-output.log`（留在本地，reboot 清；不提交）。

### §B · SHA + frozen image 证据（2026-09-17 Asia/Shanghai，由操作发起人算）

- `REVIEWED_CHART_SHA256 = a53435d50378e9dbda4c82786d7dd5bf254f3ab8beba0358a8eb5c56bb3e27c3`（= `git ls-files -z -- deploy/helm/a-stock | sort -z | xargs -0 sha256sum | sha256sum`，与脚本内置 `chart_sha256()` 同样口径）
- `REVIEWED_BASELINE_SHA256 = 5536e681b3384bf7e1524aa6fb1662f2c9980d626f614dc2375888f9037c65c7`（= `sha256sum deploy/truenas/values-scheduled-baseline-20260917.yaml`，对应 `--baseline-values` 输入）
- Step 1 overlay sha：`REVIEWED_OVERLAY_SHA256 = 97d0455d7ab5162989eba1c22969225e8c9c810878663755994f308600a7877c`（= `sha256sum deploy/truenas/values-scheduled-suspended.yaml`，对应 Step 1 `--release-suspended --scheduling-overlay` 输入）
- Step 2 overlay sha：`REVIEWED_OVERLAY_SHA256 = cf66bee36cea2a58c77a1e21f688d20642116d9913f857830c7c00c8a5d3f1e8`（= `sha256sum deploy/truenas/values-scheduled-active.yaml`，对应 Step 2 `--activate-schedule --scheduling-overlay` 输入）
- Step 1 render sha：`REVIEWED_RENDER_SHA256 = 8c543892a76b554fd1434dc8270df2bdf44162d96d8442c45dcc372c4e7e4b61`（= `helm template a-stock deploy/helm/a-stock -f .../baseline-...yaml -f .../suspended.yaml --set component=schedule --kube-version 1.26.6 | sha256sum`，对应 `compare-add-suspended` 期望 packet）
- Step 2 render sha：`REVIEWED_RENDER_SHA256 = 3170ee5df80d65f368e7c4850549b676f43906c839890ab2bbbe53c871e6d68b`（= 同上但用 active overlay，对应 `compare-suspend-only` 期望 packet）
- `FROZEN_IMAGE_REPOSITORY = localhost/a-stock-market-environment`
- `FROZEN_IMAGE_TAG = 20260917-113516-b5be526`
- `FROZEN_IMAGE_DIGEST = sha256:ace2e93c0075d2397845a0ad346171558c0ff1f307409d04c7fec2eb931416e2`（= live `k3s ctr -n k8s.io images ls` 第 3 列 = manifest digest，与 chart 模板 `verify-containerd-image` 期望口径一致；满足 `^sha256:[0-9a-f]{64}$`）

### §C · 探针（`--release-suspended`）结果（2026-09-17 Asia/Shanghai）

- 责任人书面确认（操作发起人，2026-09-17 Asia/Shanghai）：授权跑 `--release-suspended` 探针以验证"两步"假设。
- 完整命令：
  ```bash
  FROZEN_IMAGE_REPOSITORY=localhost/a-stock-market-environment \
  FROZEN_IMAGE_TAG=20260917-113516-b5be526 \
  FROZEN_IMAGE_DIGEST=sha256:ace2e93c0075d2397845a0ad346171558c0ff1f307409d04c7fec2eb931416e2 \
  bash scripts/deploy-truenas-k3s.sh --release-suspended \
    --baseline-values deploy/truenas/values-scheduled-baseline-20260917.yaml \
    --scheduling-overlay deploy/truenas/values-scheduled-suspended.yaml \
    --kube-version 1.26.6+k3s-6a894050-dirty
  ```
- 入口退出码：`0`（脚本顶层 `exit 0`），但 fail-gate 提前 die：
  ```
  [a-stock-deploy] scheduling packet: state=suspended strategy=controller controllerTimeZone=Asia/Shanghai cron=30 16 * * 1-5 effectiveShanghai=16:30 weekdays
  ...
  [a-stock-deploy] checking target k3s capabilities
  suspended release requires the application CronJob to be absent
  ```
- 原因：live release rev 20 已含 `a-stock-data-collection`（合并所有权 plan 通过 `--release-suspended` 入口写入），`compare-add-suspended` 校验 `current` 列表不能含 CronJob。脚本未写任何 live state（fail-closed 在 `compare-add-suspended` 调用前，line 875 `current_cronjobs="$(...)"`，line 878 `assert_cronjob_creation_allowed`）。
- 完整 80 行日志已留存到 `/tmp/a-stock-canary/step1.log`（留在本地，reboot 清；不提交）。
- 结论：激活路径修正为 single-step `--activate-schedule`（见 §A / §Scope）。

### §D · `--activate-schedule` 写后证据（2026-09-17 19:10:51–19:10:54 Asia/Shanghai）

- 责任人书面确认：**操作发起人**（2026-09-17 Asia/Shanghai，turn-by-turn 对话中获显式"go"）。本步属单次授权两步中的第二步。
- 完整命令（含 env 注入）：
  ```bash
  FROZEN_IMAGE_REPOSITORY=localhost/a-stock-market-environment \
  FROZEN_IMAGE_TAG=20260917-113516-b5be526 \
  FROZEN_IMAGE_DIGEST=sha256:ace2e93c0075d2397845a0ad346171558c0ff1f307409d04c7fec2eb931416e2 \
  ACTIVATION_CATCH_UP_MODE=next-schedule \
  bash scripts/deploy-truenas-k3s.sh --activate-schedule \
    --baseline-values deploy/truenas/values-scheduled-baseline-20260917.yaml \
    --scheduling-overlay deploy/truenas/values-scheduled-active.yaml \
    --kube-version 1.26.6+k3s-6a894050-dirty
  ```
- preflight 时间窗校验输出（`validate_activation_window preflight`，nowUtc=2026-09-17T11:10:51Z）：
  ```json
  {"allowed":true,"decision":"allowed","mode":"next-schedule",
   "nextTriggerShanghai":"2026-09-18T16:30:00+08:00",
   "nextTriggerUtc":"2026-09-18T08:30:00Z",
   "nowUtc":"2026-09-17T11:10:51Z",
   "previousDeadlineUtc":"2026-09-17T09:00:00Z",
   "previousTriggerShanghai":"2026-09-17T16:30:00+08:00",
   "previousTriggerUtc":"2026-09-17T08:30:00Z",
   "safetyBufferSeconds":300,
   "schedule":"30 16 * * 1-5",
   "schedulerTimeZone":"Asia/Shanghai",
   "secondsAfterPreviousTrigger":9651,
   "secondsUntilNextTrigger":76749,
   "startingDeadlineSeconds":1800}
  ```
- 写前第二次时间窗校验输出（`validate_activation_window pre-helm-write`，nowUtc=2026-09-17T11:10:53Z）：与 preflight 一致，`allowed=true`，`mode=next-schedule`。
- **retry 痕迹**：入口在第一次建 SSH 隧道时遇到 `bind [127.0.0.1]:16443: Address already in use`（前一次 read-only-discovery 留下的隧道未关），脚本自动 retry，第二次 `checking target k3s capabilities` 成功，本次 `activating...` 完成。`activate-schedule completed; no canary or provider-backed Job was created`。
- `helm history a-stock -n a-stock` 末三行：
  | REVISION | UPDATED                  | STATUS     | DESCRIPTION |
  | 19       | Thu Sep 17 11:48:17 2026 | superseded | Upgrade complete |
  | 20       | Thu Sep 17 12:12:24 2026 | superseded | Upgrade complete |
  | 21       | Thu Sep 17 19:10:54 2026 | **deployed** | **Upgrade complete** |
- helm upgrade 输出：
  ```
  Release "a-stock" has been upgraded. Happy Helming!
  NAME: a-stock
  LAST DEPLOYED: Thu Sep 17 19:10:54 2026
  NAMESPACE: a-stock
  STATUS: deployed
  REVISION: 21
  ```
- `helm get values a-stock -n a-stock` 关键字段：
  - `image.repository = localhost/a-stock-market-environment`
  - `image.tag = 20260917-113516-b5be526`
  - `database.existingSecret = a-stock-postgresql`
  - `persistence.existingClaim = a-stock-data`
  - `marketEnvironment.scheduledCollection.enabled = true`
  - `marketEnvironment.scheduledCollection.suspend = **false**`（← 由 `true` 翻为 `false`）
  - `marketEnvironment.scheduledCollection.controllerCanaryVerified = **true**`（← 由 `false` 翻为 `true`，被 baseline 写进 stored values）
  - `marketEnvironment.scheduledCollection.controllerTimeZoneVerified = true`
  - `marketEnvironment.scheduledCollection.schedule = 30 16 * * 1-5`
  - `marketEnvironment.scheduledCollection.controllerTimeZone = Asia/Shanghai`
- `kubectl -n a-stock get cronjob a-stock-data-collection -o wide`：
  ```
  NAME                      SCHEDULE        SUSPEND   ACTIVE   LAST SCHEDULE   AGE   CONTAINERS   IMAGES
  a-stock-data-collection   30 16 * * 1-5   False     0        <none>          6h59m collector   localhost/a-stock-market-environment:20260917-113516-b5be526
  ```
  - `SUSPEND=False`、`ACTIVE=0`、`LAST SCHEDULE=<none>`（下个交易日 16:30 触发前）
- `kubectl -n a-stock get cronjob a-stock-data-collection -o jsonpath='{.spec}'` 完整 spec（仅 `suspend` 字段变化，其它与 rev 20 等价）：
  ```
  30 16 * * 1-5|false|Forbid|1800|3|3|0|3600|localhost/a-stock-market-environment:20260917-113516-b5be526|IfNotPresent
  ```
- `kubectl -n a-stock get cronjob a-stock-data-collection -o jsonpath='{.spec.timeZone}'` 输出空（absent，符合 controller strategy 校验 `1.26 只能省略 timeZone`）。
- 写后 `kubectl -n a-stock get pod -o wide`：
  ```
  NAME                      READY   STATUS    RESTARTS   AGE     IP              NODE         NOMINATED NODE   READINESS GATES
  a-stock-postgresql-0      1/1     Running   0          7h38m   172.16.91.148   ix-truenas   <none>           <none>
  a-stock-7df764f74-rsx6r   1/1     Running   0          7h23m   172.16.91.149   ix-truenas   <none>           <none>
  ```
  （Pod 集合与 rev 20 完全等价，无新对象；`suspend_after_uncertain_activation` 兜底未触发）
- 写后 `kubectl -n a-stock get pvc`：`{a-stock-data, a-stock-postgresql-data}` 均 Bound，与 rev 20 等价。
- 写后 `kubectl -n a-stock get job`：空（激活不创建 Job，符合 runbook 第 365 行"激活或回退失败会先对 exact CronJob 补偿设置 `suspend=true`"的"激活成功不建 canary"原则）。
- 完整 187 行日志已留存到 `/tmp/a-stock-canary/step2.log`（留在本地，reboot 清；不提交）。
- 4 个 SHA：
  - `REVIEWED_CHART_SHA256 = sha256(chart dir) = …`
  - `REVIEWED_BASELINE_SHA256 = sha256(deploy/truenas/values-scheduled-baseline-20260917.yaml) = …`
  - `REVIEWED_OVERLAY_SHA256 = sha256(deploy/truenas/values-scheduled-active.yaml) = …`
  - `REVIEWED_RENDER_SHA256 = sha256(helm template …) = …`
- frozen image 三元组：
  - `FROZEN_IMAGE_REPOSITORY = localhost/a-stock-market-environment`
  - `FROZEN_IMAGE_TAG = 20260917-113516-b5be526`
  - `FROZEN_IMAGE_DIGEST = sha256@…`（来自 live containerd `k3s ctr -n k8s.io images ls` 或 Helm stored manifest 的 imageID）
- preflight 时间窗校验输出（`validate_activation_window preflight`）：
- 写前第二次时间窗校验输出（`validate_activation_window pre-helm-write`）：
- `--activate-schedule` 命令完整记录（含 catch-up 模式）：
- 写后 live 比对（`kubectl -n a-stock get cronjob a-stock-data-collection -o wide` + `kubectl -n a-stock get cronjob a-stock-data-collection -o jsonpath='{.spec}'`）：
- 失败兜底：若 pre-helm-write 第二次校验或 Helm write 失败，入口应执行 `suspend_after_uncertain_activation` 把 `suspend=true` 写回，并把 abort 原因记到本段。

## Remaining Gaps（剩余缺口）

- **首次交易日 16:30 自然触发观察清单**（runbook 第 571 行）：下个交易日 2026-09-18（周五）Asia/Shanghai 16:30 后，采集 `kubectl -n a-stock get cronjob,job,pod`、PostgreSQL `collection_runs` 行（`SELECT as_of, dataset, quality_status, completed_at FROM collection_runs ORDER BY started_at DESC LIMIT 50;`）、五个 dataset 快照（`api/market-environment?as_of=2026-09-18`）与 `/api/market-environment/core?as_of=2026-09-18` 响应；provider 失败应保留 `partial` / `degraded` / `insufficient`，不得伪造 success。本 plan 不覆盖此观察任务，由 `Next Step` 把它移交给后续 plan。
- live 镜像仍为可变 tag `20260917-113516-b5be526`；`FROZEN_IMAGE_DIGEST` 收紧为 chart 字段不在本次范围。
- `local main` 不领先 `origin/main` 9 个 commit（`HEAD=1c29794 == @{u}=1c29794`，worktree clean）。
- `/etc/timezone=Etc/UTC` 与 `/etc/localtime=Asia/Shanghai` 不一致；k3s server 进程读 `/etc/localtime`（Go runtime），所以本次激活不会受影响；其他 systemd service 若读 `/etc/timezone` 仍可能按 UTC 解释，建议后续同步 `/etc/timezone=Asia/Shanghai`，不在本 plan 范围。

## Next Step（下一步）

1. 本次操作责任人书面"go"激活后，由本会话内一次性执行 `--activate-schedule` 入口并写后 live 比对。
2. 激活后首个交易日 16:30 观察 Job/Pod、PostgreSQL `collection_runs`、五个 dataset quality 与 `/api/market-environment?as_of=<交易日>` 响应；如失败，按 `--disable-schedule` 入口回退。
3. 单独 plan 中把可变 tag 改为 `FROZEN_IMAGE_DIGEST` 收紧；并把 `/etc/timezone` 同步为 `Asia/Shanghai`。
