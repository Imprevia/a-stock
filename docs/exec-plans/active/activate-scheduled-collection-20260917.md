# 激活 scheduled collection（2026-09-17 patch through --activate-schedule）

## Stage（阶段）

续接 [`canary-verified-20260917.md`](canary-verified-20260917.md) + [`canary-1-26-controller-timezone-20260917.md`](canary-1-26-controller-timezone-20260917.md)：TrueNAS k3s 上 `a-stock-data-collection` 仍 `suspend=true`，但 `controllerCanaryVerified: true` 已写入 baseline 并推到 `origin/main`，controller timezone canary 已现场确认 `Asia/Shanghai`。本阶段在 live 集群上把 `suspend` 翻转为 `false`，**不**改任何其它字段，**不**创建新 CronJob 模板，**不**修改镜像，**不**走 schema migration；只通过受控的 `--activate-schedule` 入口做 release-level `suspend: true → false` 单字段切换。

## Status（状态）

`in-progress` · read-only-discovery 已跑、识别出"两步激活"要求；待计算 SHA + frozen image 证据；待本次操作责任人独立"go --release-suspended"与"go --activate-schedule"。

## Scope（范围）

激活必须分**两步**，原因：read-only-discovery 显示 live release stored values 的 `controllerCanaryVerified=false`，而 `78421e0` baseline 已把它翻为 `true`，两次变化不能在同一次 `helm upgrade` 中合并（`--activate-schedule` 入口的 `compare-suspend-only` 校验只允许 `suspend: true → false` 单字段变化）：

- **Step 1 · `--release-suspended`**：把 baseline 写进 release，单字段 `controllerCanaryVerified: false → true`；仍 `suspend=true`。
- **Step 2 · `--activate-schedule`**：把 baseline + active overlay 写进 release，单字段 `suspend: true → false`；`catch-up=next-schedule`。

### 准备动作（read-only-discovery 与 SHA + frozen image 计算）

- 跑 `bash scripts/deploy-truenas-k3s.sh --read-only-discovery` 抓 live `helm history` / `helm get values` / live `deployment,service,cronjob,job,pvc,pv` 状态。✅ 已跑（2026-09-17 Asia/Shanghai），见 Completion Evidence 段。
- 计算 4 个 SHA（`REVIEWED_CHART_SHA256` / `REVIEWED_BASELINE_SHA256` / `REVIEWED_OVERLAY_SHA256` / `REVIEWED_RENDER_SHA256`）+ frozen image 三元组（`FROZEN_IMAGE_REPOSITORY` / `FROZEN_IMAGE_TAG` / `FROZEN_IMAGE_DIGEST`）。⏳ 待算（见 Completion Evidence 占位）。
- Step 1 由本次操作责任人书面"go"后跑 `bash scripts/deploy-truenas-k3s.sh --release-suspended --baseline-values deploy/truenas/values-scheduled-baseline-20260917.yaml --scheduling-overlay deploy/truenas/values-scheduled-suspended.yaml --kube-version 1.26.6+k3s-6a894050-dirty`。
- Step 1 写后读取 live release `helm get values` / `kubectl -n a-stock get cronjob a-stock-data-collection -o wide`，证明 `controllerCanaryVerified=true`、仍 `suspend=true`、镜像 / Database Secret / PVC claim 与原值一致。
- Step 2 由本次操作责任人**单独**书面"go"后跑 `bash scripts/deploy-truenas-k3s.sh --activate-schedule --baseline-values deploy/truenas/values-scheduled-baseline-20260917.yaml --scheduling-overlay deploy/truenas/values-scheduled-active.yaml --kube-version 1.26.6+k3s-6a894050-dirty --catch-up-mode next-schedule`。
- Step 2 写前第二次时间窗校验（`validate_activation_window pre-helm-write`）；Step 2 写后读取 live CronJob，校验 `spec.suspend=false`、`LAST SCHEDULE` 已写入下一个交易日 16:30 Asia/Shanghai、其它字段不变。
- 不在范围：解除 `values-secure-manual-collection.yaml` 的 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1` 绑定；改镜像；改 chart；走 schema migration；跑任何"裸 `kubectl patch`/apply/edit"绕过入口。

## Acceptance（验收）

- 仓库层：`docs/exec-plans/active/_index.md` 登记本 plan；本 plan 6 字段齐全。
- 只读发现：live `helm history a-stock -n a-stock` 显示最近一次成功 release 与本次 baseline 镜像一致；`helm get values a-stock -n a-stock` 与 `values-scheduled-baseline-20260917.yaml` 渲染前输入等价（`enabled=true / suspend=true / controllerCanaryVerified=true` 不漂移）；live `cronjob` 仍 `SUSPEND=True / LAST SCHEDULE=<none>`；live `CronJob` 镜像为 `localhost/a-stock-market-environment:20260917-113516-b5be526`。
- SHA 与 frozen image：4 个 SHA 与 frozen image digest 写入本 plan 的 Completion Evidence 段；`--activate-schedule` 入口在 preflight + 写前第二次校验时一致。
- 集群层（写后）：`kubectl -n a-stock get cronjob a-stock-data-collection -o wide` 显示 `SUSPEND=False / LAST SCHEDULE=<已排好下个交易日 16:30 Asia/Shanghai>`；`/spec` 仅 `suspend: true → false` 单字段变化；image、PVC、Service、PostgreSQL Secret 均未变。
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

### §C · Step 1（`--release-suspended`）写后证据（待本次操作责任人"go"后回填）

- 责任人书面确认（操作发起人，2026-09-17 Asia/Shanghai）：
- 完整命令：
- preflight / pre-helm-write 校验输出：
- `helm history` 出现的 revision 21 状态：
- `helm get values` 关键字段（特别 `controllerCanaryVerified: true`，其它字段不变）：
- `kubectl -n a-stock get cronjob a-stock-data-collection -o wide`（`SUSPEND` 必须仍 `True`）：
- `kubectl -n a-stock get pod`（必须仍 `{a-stock-postgresql-0, a-stock-7df764f74-rsx6r}` 1/1 Running，无新对象）：

### §D · Step 2（`--activate-schedule`）写后证据（待本次操作责任人"go"后回填）

- 责任人书面确认（操作发起人，2026-09-17 Asia/Shanghai）：
- 完整命令（含 `--catch-up-mode next-schedule`）：
- preflight 时间窗校验输出（`validate_activation_window preflight`）：
- 写前第二次时间窗校验输出（`validate_activation_window pre-helm-write`）：
- `helm history` revision 22 状态：
- `helm get values` 关键字段（`suspend: false`，其它字段不变）：
- `kubectl -n a-stock get cronjob a-stock-data-collection -o wide`（`SUSPEND=False / LAST SCHEDULE=<下个交易日 16:30 Asia/Shanghai>`）：
- 失败兜底：若 pre-helm-write 第二次校验或 Helm write 失败，入口应执行 `suspend_after_uncertain_activation` 把 `suspend=true` 写回，并把 abort 原因记到本段。
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

- **本次激活不证明首个交易日 16:30 自然触发时 `scheduled-refresh` 会成功调 provider 写 PostgreSQL**；该二次验证需在激活后首个交易日 16:30 自然触发后采集（Job/Pod、`collection_runs`、五个 dataset quality 与 `/api/market-environment?as_of=<交易日>` 响应）。
- live 镜像仍为可变 tag `20260917-113516-b5be526`；`FROZEN_IMAGE_DIGEST` 收紧为 chart 字段不在本次范围。
- `local main` 不领先 `origin/main` 9 个 commit（`HEAD=1c29794 == @{u}=1c29794`，worktree clean）。
- `/etc/timezone=Etc/UTC` 与 `/etc/localtime=Asia/Shanghai` 不一致；k3s server 进程读 `/etc/localtime`（Go runtime），所以本次激活不会受影响；其他 systemd service 若读 `/etc/timezone` 仍可能按 UTC 解释，建议后续同步 `/etc/timezone=Asia/Shanghai`，不在本 plan 范围。

## Next Step（下一步）

1. 本次操作责任人书面"go"激活后，由本会话内一次性执行 `--activate-schedule` 入口并写后 live 比对。
2. 激活后首个交易日 16:30 观察 Job/Pod、PostgreSQL `collection_runs`、五个 dataset quality 与 `/api/market-environment?as_of=<交易日>` 响应；如失败，按 `--disable-schedule` 入口回退。
3. 单独 plan 中把可变 tag 改为 `FROZEN_IMAGE_DIGEST` 收紧；并把 `/etc/timezone` 同步为 `Asia/Shanghai`。
