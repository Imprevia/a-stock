# 1.26 controller timezone + 16:30 上海映射 canary

## Stage（阶段）

续接 [`consolidate-helm-managed-scheduling.md`](consolidate-helm-managed-scheduling.md) 的 Remaining Gaps：TrueNAS k3s 1.26.6 上 `a-stock-data-collection` 仍以 `suspend=true` 部署，chart 已校验 `timezoneStrategy=controller` + `schedule=30 16 * * 1-5` + `controllerTimeZone=Asia/Shanghai` + `controllerTimeZoneVerified=true`，但**运行时 canary 证据**仍缺失。本阶段在不解除 `suspend`、不调用 provider、不写入 PostgreSQL 的前提下，通过一次性只读诊断 Job 现场核对 controller timezone 解释与 CronJob `spec.schedule` 字段。

## Status（状态）

`completed` · 一次性诊断 Job `a-stock-timezone-canary-20260917` 已 apply、完成、清理；`a-stock-data-collection` 仍 `SUSPEND=True / LAST SCHEDULE=<none>`；现场证据已回填至本 plan。

## Scope（范围）

- 一次性诊断 Job `name=a-stock-timezone-canary-20260917`、命名空间 `a-stock`、image 沿用 live `localhost/a-stock-market-environment:20260917-113516-b5be526`，与 CronJob 共享 secret/env/uid 10001。
- Job `command` 仅做只读诊断（`printenv TZ` + `date` + `python -c` 输出 `datetime.now()` / `zoneinfo.ZoneInfo('Asia/Shanghai')`），**不**调用 `src.market_environment.cli`、**不**连 PostgreSQL、**不**触发 provider、**不**改写 CronJob。
- 落地 kubectl 现场输出（Pod events、container logs、controller `/version`、CronJob `spec.schedule` 与 `spec.suspend`）到本 plan 的 Completion Evidence 段。
- 完成后立即 `kubectl delete job` 清理资源，避免在 `a-stock` 命名空间留下任何新对象。
- 不在范围：解除 `suspend`、跑 `scheduled-refresh` 实际采集、补 chart 的 `image.digest` contract、激活 CronJob 走 `--activate-schedule` 入口。

- 不在范围：解除 `suspend`、跑 `scheduled-refresh` 实际采集、补 chart 的 `image.digest` contract、激活 CronJob 走 `--activate-schedule` 入口。

### Job 资源（待本次操作责任人书面确认后 apply）

- **name**: `a-stock-timezone-canary-20260917`
- **namespace**: `a-stock`
- **image**: `localhost/a-stock-market-environment:20260917-113516-b5be526`（与 live CronJob 一致）
- **imagePullPolicy**: `IfNotPresent`
- **restartPolicy**: `Never`
- **backoffLimit**: `0`
- **activeDeadlineSeconds**: `300`
- **securityContext**: 与 CronJob collector 对齐（`runAsNonRoot: true`、`runAsUser: 10001`、`runAsGroup: 10001`、`fsGroup: 10001`、`seccompProfile.type: RuntimeDefault`）
- **automountServiceAccountToken**: `false`
- **env**: `TZ=Asia/Shanghai`；**不**注入 `MARKET_ENVIRONMENT_DATABASE_*`（只读诊断，不需要 DB 连接，避免被误识为 provider-backed Job）
- **command**:
  ```sh
  sh -c '
    echo "==== canary start $(date -Iseconds) ====";
    echo "---- printenv TZ ----"; printenv TZ;
    echo "---- date ----"; date;
    echo "---- python datetime ----";
    python -c "import os, datetime, zoneinfo;       print(\"TZ_ENV=\", os.environ.get(\"TZ\"));       print(\"UTC_NOW=\", datetime.datetime.now(datetime.timezone.utc).isoformat());       print(\"LOCAL_NOW=\", datetime.datetime.now().isoformat());       print(\"ASTIMEZONE=\", datetime.datetime.now().astimezone().isoformat());       print(\"TZINFO=\", datetime.datetime.now().astimezone().tzinfo);       print(\"SHANGHAI=\", datetime.datetime.now(zoneinfo.ZoneInfo(\"Asia/Shanghai\")).isoformat())";
    echo "==== canary end $(date -Iseconds) ===="
  '
  ```
- **预期退出码**: `0`
- **清理**: Job 完成后 `kubectl delete job a-stock-timezone-canary-20260917 -n a-stock`（不保留任何对象）

## Acceptance（验收）

- 集群层：Job 退出码 0，`Active=False`、`Succeeded=1`、`Failed=0`；Pod 启动时间与 `kubectl get nodes` 上 controller 节点时间差在秒级。
- 运行时证据：容器内 `printenv TZ` 输出 `Asia/Shanghai`；`date` 输出带 `CST-8` 时区标识；`python -c` 输出的 `datetime.now().astimezone().tzinfo` 与 `ZoneInfo('Asia/Shanghai')` 的偏移相同，且与 `printenv TZ` 解释一致。
- controller 证据：`kubectl version` server 段为 `v1.26.6+k3s1`（与 baseline `--kube-version` 严格相等）；CronJob `a-stock-data-collection` 的 `spec.schedule=30 16 * * 1-5`、`spec.suspend=true`、**无** `spec.timeZone` 字段。
- 命名空间：canary 执行前后 `kubectl -n a-stock get cronjob,job,pod,svc` 与 baseline 等价；`a-stock-data-collection` 仍 `SUSPEND=True / LAST SCHEDULE=<none>`；遗留 Job/Pod 已删除。
- 文档层：本 plan 的 Completion Evidence 段含 Pod 名/起停时间/logs 关键行/责任人确认；`docs/exec-plans/active/_index.md` 补登记。

## Completion Evidence（完成证据）

- 责任人书面确认：**操作发起人**（2026-09-17 Asia/Shanghai，apply `a-stock-timezone-canary-20260917`；本次操作在 turn-by-turn 对话中获得显式书面确认）。本 canary 范围限定在 controller timezone 解释 + CronJob 字段等价核对，**不**包括解除 `suspend` 或实际跑 `scheduled-refresh`。

### Job / Pod 现场

- Job 名称 / 命名空间：`a-stock-timezone-canary-20260917` / `a-stock`
- Pod 名：`a-stock-timezone-canary-20260917-qxlnq`
- Pod 节点：`ix-truenas`（172.16.91.159）
- 启动（UTC / Asia/Shanghai）：`2026-09-17T10:53:41Z` / `2026-09-17T18:53:41+08:00`
- 完成（UTC / Asia/Shanghai）：`2026-09-17T10:53:52Z` / `2026-09-17T18:53:52+08:00`
- 退出码：`0` · `Active=0/1 → 0/0`、`Succeeded=1`、`Failed=0`
- Pod 事件（`kubectl -n a-stock get events --sort-by=.lastTimestamp`）：`Scheduled` → `SuccessfulCreate` → `Pulled (already present)` → `Created` → `Started` → `Job completed`；`Restart=0`；无 Warning。
- Job `status` 摘要：
  ```
  completionTime: 2026-09-17T10:53:52Z
  startTime:      2026-09-17T10:53:41Z
  succeeded:      1
  conditions: [{type: Complete, status: True}]
  ```

### 容器内 timezone 输出（`kubectl logs pod/a-stock-timezone-canary-20260917-qxlnz --all-containers`，保留原样）

```
==== canary start 2026-09-17T18:53:43+08:00 ====
---- printenv TZ ----
Asia/Shanghai
---- date ----
Thu Sep 17 18:53:44 CST 2026
---- date -u ----
Thu Sep 17 10:53:44 UTC 2026
---- /etc/localtime ----
/usr/share/zoneinfo/Etc/UTC
---- python datetime ----
TZ_ENV= Asia/Shanghai
UTC_NOW= 2026-09-17T10:53:44.582572+00:00
NAIVE_NOW= 2026-09-17T18:53:44.582588
ASTIMEZONE= 2026-09-17T18:53:44.582609+08:00
TZINFO= CST
SHANGHAI_NOW= 2026-09-17T18:53:44.582825+08:00
==== canary end 2026-09-17T18:53:44+08:00 ====
```

### controller 端 timezone 证据（这是 controller strategy 的真正依据）

- 主机 `/etc/localtime` → `/usr/share/zoneinfo/Asia/Shanghai`
- 主机 `/etc/timezone`（过时文件，未必被 systemd-timedatectl 信任）= `Etc/UTC`
- 主机 `timedatectl show -p Timezone --value` = `Asia/Shanghai`
- 主机 `date` = `2026-09-17T18:54:07+08:00`
- k3s server 进程 pid `635145`，`/proc/635145/environ` 中 **没有 `TZ=` 覆盖**；Go runtime 因此读 `/etc/localtime`，解释为 `Asia/Shanghai`。
- 推导：k3s controller-manager 把 CronJob `spec.schedule=30 16 * * 1-5` 在 host timezone（Asia/Shanghai）下解释，下一个自然触发点 = 下个交易日 16:30 Asia/Shanghai（即 UTC 08:30）。

### CronJob `a-stock-data-collection` spec（live，post-canary，kubectl jsonpath）

- `spec.schedule = 30 16 * * 1-5`
- `spec.suspend = true`
- `spec.concurrencyPolicy = Forbid`
- `spec.startingDeadlineSeconds = 1800` · `spec.successfulJobsHistoryLimit = 3` · `spec.failedJobsHistoryLimit = 3`
- `spec.jobTemplate.spec.backoffLimit = 0` · `spec.jobTemplate.spec.activeDeadlineSeconds = 3600`
- `spec.timeZone` 字段**不存在**（controller strategy）
- 容器 `image = localhost/a-stock-market-environment:20260917-113516-b5be526` · `imagePullPolicy = IfNotPresent`
- 容器 `env.TZ = Asia/Shanghai`、`env.MARKET_ENVIRONMENT_SETTLEMENT_TIME = 15:10`
- 容器 `securityContext`：uid/gid 10001、runAsNonRoot、readOnlyRootFilesystem、capabilities drop ALL、seccompProfile RuntimeDefault
- `status` 为空对象（`{ }`）：`lastScheduleTime / lastSuccessfulTime` 均为 null

### controller `/version`

- Server Version: `v1.26.6+k3s-6a894050-dirty`（`GitCommit=6a8940508aa84f4521c4292d6a4f0c22ff6703c6` · `BuildDate=2024-07-08T15:50:17Z` · `GitTreeState=dirty`）
- Client Version: 同上（TrueNAS 上 k3s 自带 client）。
- ⚠️ 与 baseline `--kube-version=1.26.6+k3s1` **不**严格相等（差异：build 标记 `dirty`、build tag 非 `k3s1`）。**canary 范围内不阻断**，但激活走 `--activate-schedule` 时该项会被 fail-closed 拦截，必须先做版本对齐或在 baseline 改为与 live 严格相等的 `--kube-version`（见 Remaining Gaps）。

### 验证结论

- ✅ `controllerTimeZone=Asia/Shanghai`（k3s server 进程无 `TZ` env 覆盖 + host `/etc/localtime=Asia/Shanghai` 双重确认）。
- ✅ CronJob `spec.schedule=30 16 * * 1-5` 在 controller 解释下等价于盘后 16:30 Asia/Shanghai。
- ✅ 容器内 `TZ=Asia/Shanghai` env 与 `MARKET_ENVIRONMENT_SETTLEMENT_TIME=15:10` 一致，`date` / `datetime` / `zoneinfo` 三个口径都给出 +08:00 CST。
- ✅ 清理后 `kubectl -n a-stock get job` 为空；`kubectl -n a-stock get pod` 仅 `a-stock-postgresql-0` 与 `a-stock-7df764f74-rsx6r` 两个 1/1 Running；`kubectl -n a-stock get cronjob a-stock-data-collection` 仍 `SUSPEND=True / LAST SCHEDULE=<none>`。
- ⚠️ 不证明首个交易日 16:30 自然触发时 `scheduled-refresh` 会成功调 provider 写 PostgreSQL；该二次验证需激活后首个交易日 16:30 自然触发后采集。

## Remaining Gaps（剩余缺口）

- 本次只验证 controller timezone 解释与 CronJob 字段等价，**不**证明首个交易日 16:30 自然触发时 `scheduled-refresh` 会成功调用 provider 并写入 PostgreSQL；该二次验证需在激活后首个交易日 16:30 自然触发后采集。
- **`controllerCanaryVerified` 翻转决策仍待书面授权**：本 canary 已现场证明 `controllerTimeZone=Asia/Shanghai` 与 `30 16 * * 1-5` 等价，但要写入 `values-scheduled-baseline-20260917.yaml` 之前必须由本次操作责任人**单独**书面确认；runbook 第 346 / 524 行强调 typed 翻转不能替代运行时证据，但运行时证据本身仍需责任人二次确认才允许作为 baseline 字段固化。
- **k3s controller 版本与 baseline `--kube-version` 不严格相等**：live `Server Version = v1.26.6+k3s-6a894050-dirty`，baseline `--kube-version = 1.26.6+k3s1`。`--activate-schedule` 入口会做严格相等校验，激活前必须二选一：(a) 在 TrueNAS 上把 k3s 升级或重打为 `v1.26.6+k3s1` 非 dirty build；(b) 把 baseline `--kube-version` 改为与 live `/version` 严格相等的字符串。
- **`/etc/timezone` 与 `/etc/localtime` 不一致**：host `/etc/timezone=Etc/UTC`、`/etc/localtime=Asia/Shanghai`。当前 k3s server 进程读 `/etc/localtime`（Go runtime 行为），所以本次 canary 通过；但其他 systemd 服务若读 `/etc/timezone` 仍会按 UTC 解释，存在被踩坑的可能。建议把 `/etc/timezone` 同步为 `Asia/Shanghai`，不在本 plan 范围。
- `local main` 仍领先 `origin/main` 9 个 commit（`HEAD=a1a0611...`、`@{u}=0ebf5168...`）；激活前置的 `REVIEWED_GIT_HEAD = @{u}` 校验仍未满足。
- live 镜像仍为可变 tag `20260917-113516-b5be526`；`FROZEN_IMAGE_*` 收紧与 `image.digest` chart 字段加固都不在本次范围。

## Next Step（下一步）

1. 本次操作责任人书面确认后，apply canary Job、抓 logs、清理 Job、回填 Completion Evidence。
2. 单独 plan 中把 `controllerCanaryVerified: true` 写进 baseline，并把 live 状态证据引用到本次的 Completion Evidence 段。
3. 处理 `local main` 领先 `origin/main` 9 个 commit（push 或选定 reviewed HEAD）后再激活。
4. 激活走 `--activate-schedule` 入口，`catch-up=next-schedule`（`immediate-catch-up` 已过 deadline window）。
5. 激活后首个交易日 16:30 观察 Job/Pod、PostgreSQL `collection_runs`、五个 dataset quality 与 `/api/market-environment?as_of=<交易日>` 响应。
