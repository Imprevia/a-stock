# 重新激活扶摇版本盘后定时采集

## Stage

生产调度发布与激活

## Status

completed-with-backfill-provider-failure

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
- 2026-09-22 23:27 Asia/Shanghai 通过 NodePort `32001` 对精确日期 `2026-09-22` 逐项补采失败数据集；`manualRefreshEnabled=true`，未修改 CronJob、Pod、PVC 或 Secret。POST/轮询运行分别为：`breadth` `68a1e5ccfea843469493044ccacfc22d`、`activeDirection` `70e30d0e241d4bb6ba43e0dc8ecd6ee4`、`sectors` `98c5ca998d6249ae8a427f6b10a7a94e`、`limits` `be96368b5d7b46a68f2f3853a78e2fc0`。
- 四次补采均已完成并真实落库审计为失败状态：`breadth`/`sectors`/`activeDirection` 分别为 `failed-missing`/`failed-missing`/`failed-retained`，东方财富 `push2`/`push2delay` 请求被远端断开；`limits` 为 `failed-retained`，扶摇返回 5003 后降级东方财富，最终因 exact-date source revision mismatch 被拒绝晋级。`core` 保持原有 `success`（`sina-kline`，带降级 warning）。
- 补采后状态 GET 确认无 active task/lease；PostgreSQL PVC 仍 `Bound`，Dashboard/PostgreSQL Pod 均 `1/1`，没有创建一次性 Job，也没有发生跨日期回填或伪成功写入。
- 2026-09-22 23:41 Asia/Shanghai 通过同一 NodePort 再次针对失败数据集发起的补采，run ID：`breadth` `d2679f5850be414f94f2cd0610d13b88`（`failed-missing`，远端断开 `push2delay.eastmoney.com`）、`activeDirection` `c28f5bca6e7749ea95872209534268f6`（`failed-retained`）、`sectors` `36ae1928f8f6460fa5b9cba248409f9b`（`failed-missing`）、`limits` `ae978032acc34e6c8f4140d728c23479`（`failed-retained`，扶摇 5003 + exact-date revision mismatch）。`/data-collection` 重读确认 `breadth`/`sectors` 仍为 `available=false`，`limits`/`activeDirection` 仍 `available=true` 但 `refreshWarning` 标识降级源；`core` 仍为 `sina-kline` success。
- 2026-09-22 23:48 Asia/Shanghai 通过 SSH 在生产 Pod 内用 stdlib `socket+ssl` 对东方财富域名执行旁路抓包：`push2.eastmoney.com` 443 可完成 TLSv1.3 握手并对 `GET /` 正常返回 `HTTP/1.1 404`（约 155 字节），但对 `/api/qt/clist/get`、`getTopicZTPool`、`push2delay.eastmoney.com` 同一请求反复返回 `Remote end closed connection without response`（HTTP 客户端 `ProtocolError`，raw socket 也未收到字节）；`fuyao.aicubes.cn` 的 `/api/a-share/calendar/trading-days` 在缺失/失效 `X-api-key` 时仍按预期返回 `code=2003`。结论：当前失败源于上游主动断连，不是写入路径或数据库问题，未发现其它可审计替代 provider；不得通过手工 SQL 写入伪造成功快照。

## Remaining Gaps

- `breadth`、`sectors`、`activeDirection` 仍缺少 2026-09-22 的可验证成功快照；需要 Eastmoney 网络恢复或经审阅、已验证的替代 provider 后再定向重试。
- `limits` 仍为 `failed-retained`，需要扶摇返回可接受的 exact-date source revision，或完成独立的 provider 变更审阅；不得用当前降级结果强行晋级。
- 首个自然触发后的 Job、provider 质量和 PostgreSQL collection run 仍待 2026-09-23 16:30 Asia/Shanghai 后观察。

## Next Step

继续保留 2026-09-22 的真实失败证据，不跨日期回填；在 `2026-09-23 16:30 Asia/Shanghai` 后继续观察首个自然 Job、collection run、provider warning/限流和快照质量。任何失败继续保留 `failed-retained`/`insufficient` 证据。当东方财富行情接口或扶摇按 `as_of=2026-09-22` 的真实回执恢复后，仅对 `breadth`、`sectors`、`activeDirection`、`limits` 这四个数据集再次按精确日期定向重试。
