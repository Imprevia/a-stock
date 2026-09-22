# 重新激活扶摇版本盘后定时采集

## Stage

生产调度发布与激活

## Status

completed-activation-observation-pending

## Acceptance

- 目标固定为 Helm release `a-stock`、namespace `a-stock`、Kubernetes `1.26.6+k3s-6a894050-dirty`。
- 冻结镜像为 `localhost/a-stock-market-environment:20260922-185527-06c3fd7`，containerd manifest digest 为 `sha256:d6a2ee15de39a78e9caeff69288b661979755f22da7df0ab8560d2d8c465ca8c`。
- 先通过 `--release-suspended` 创建唯一 Helm-owned CronJob，确认 `suspend=true`、无 active Job；再通过 `--activate-schedule` 只切换 `spec.suspend`。
- catch-up 固定为 `next-schedule`；不立即补跑 2026-09-22 已过 deadline 的触发。
- 激活后 CronJob `suspend=false`，schedule 为上海时间工作日 `16:30`，Dashboard/PostgreSQL 保持 Ready，PVC 不变。

## Completion Evidence

- 2026-09-22 用户明确授权“帮我激活定时任务”。
- 激活前只读检查：Helm revision 33 deployed、stored `component=all`、CronJob absent、Dashboard/PostgreSQL Ready。
- 2026-09-22 22:23 Asia/Shanghai 已越过当日 16:30 触发的 1800 秒 deadline，采用 `next-schedule`，预期下一自然触发为 2026-09-23 16:30 Asia/Shanghai。
- 离线 frozen render 校验通过：suspended packet SHA-256 `3006b108ea89fa7b27047b8841a2dac853e0fa071e532336bd944f6917cec6cd`，active packet SHA-256 `a212d38a423650673588c85d65d838769263f0246384a8d7beb27b4f2928cf00`；`compare-suspend-only` 通过。
- 首次 suspended-release 预检发现 k3s CRI 回报同一镜像仓库的旧 tag 别名；校验器已改为同时要求 Deployment/ReplicaSet spec 精确 tag、Pod 状态仓库一致、containerd frozen tag manifest digest 精确匹配。相关部署/调度测试 `303 passed`。
- 生产修复提交 `ab27b1b`：允许 Kubernetes 1.26 读回时省略 desired 空字符串 EnvVar 的等价比较；部署/调度定向测试 `118 passed`，Helm lint 与 docs-contract full 通过。
- `--release-suspended` 于 2026-09-22 22:47 Asia/Shanghai 成功，Helm revision `34`；CronJob `a-stock-data-collection` 为 Helm-owned、`suspend=true`、active Job `0`。
- `--activate-schedule` 于 2026-09-22 22:53 Asia/Shanghai 成功，Helm revision `35`；写后 exact read-back 确认 `suspend=false`、schedule `30 16 * * 1-5`、`startingDeadlineSeconds=1800`、active Job `0`，Dashboard/PostgreSQL 均 `1/1 Ready`，`/api/health` 返回 `{"status":"ok"}`。
- 激活窗口采用 `next-schedule`，脚本证明下一次触发为 `2026-09-23 16:30 Asia/Shanghai`，未创建 canary 或 provider-backed Job。

## Remaining Gaps

- 首次自然触发后的 Job、provider 质量和 PostgreSQL collection run 尚未观察。

## Next Step

在 `2026-09-23 16:30 Asia/Shanghai` 后观察首个 Job、collection run、provider warning/限流和快照质量；若失败按 runbook 保留 `failed-retained`/`insufficient` 证据，不跨日期回填。
