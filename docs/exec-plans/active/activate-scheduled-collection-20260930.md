# 激活盘后定时采集（2026-09-30）

## Stage（阶段）

调度 packet 审核、suspended CronJob 发布、激活与首次自然触发观察。

## Status（状态）

activated-observation-complete-with-partial-quality

## Acceptance（验收）

- 使用 reviewed clean HEAD、当前运行的冻结镜像和唯一 baseline/overlay packet；不启用扶摇数据集开关，不创建 canary/provider-backed Job。
- 从 revision 80 的 disabled/absent 状态开始，先创建 `a-stock-data-collection` 的 `suspend=true` CronJob，再通过 `--activate-schedule` 只改变 `spec.suspend: true -> false`。
- 采用 `ACTIVATION_CATCH_UP_MODE=next-schedule`；preflight 和 Helm 写入前均须通过时间窗检查，目标为工作日上海 16:30 自然触发。
- 写后读回 Helm、CronJob、Dashboard、PostgreSQL、PVC 和镜像状态；首次自然触发后核对 Job/Pod、五类数据质量、`collection_runs` 和 exact-date API。

## Completion Evidence（完成证据）

- 2026-09-30 16:15（Asia/Shanghai）操作发起人明确要求“部署定时任务，并激活”，授权目标为现有 `a-stock` release / `a-stock` namespace。
- 只读发现确认 k3s `1.26.6+k3s-6a894050-dirty`、Helm revision `80` 已部署，调度 values 为 `enabled=false / suspend=true`，exact CronJob absent。
- 当前运行镜像为 `localhost/a-stock-market-environment:20260930-115139-40c3498`；目标 containerd manifest digest 使用已验证的 `sha256:53c1219db808acd6860286725fa77ebda7da40f8dbcbf8e66e001056cfe05883`。
- Reviewed HEAD 为 `40c3498c16325ad0962661a841a3efe6d23cb7d2`；chart SHA 为 `3ad82655fee3d42b6527b75608132e805b0238561101c71e6f9d4b31590fd01a`，baseline SHA 为 `d7e6492934ccf56ebaeb77c3a16e6e1e83ef074d306c8d84f0dc8efb5a68e25c`，suspended/active overlay SHA 分别为 `97d0455d7ab5162989eba1c22969225e8c9c810878663755994f308600a7877c` / `cf66bee36cea2a58c77a1e21f688d20642116d9913f857830c7c00c8a5d3f1e8`；离线 manifest packet SHA（去除脚本日志行）分别为 `dbe67dc976d58b3abbad5e7a00add44b294bd92427d29769dd60b20b79555287` / `59ea4a86b100474776481cc3c897b37be85afdc30e53debe3a46960e690d457c`。
- revision `81` 通过 `--release-suspended` 创建 Helm-owned `a-stock-data-collection`，revision `82` 于 16:21:37（Asia/Shanghai）通过 `ACTIVATION_CATCH_UP_MODE=next-schedule --activate-schedule` 只翻转 `spec.suspend=true -> false`；preflight/pre-write 时间窗均允许，目标自然触发为 16:30，未创建 canary 或 provider-backed Job。
- revision `82` 写后读回为 `30 16 * * 1-5`、controller `Asia/Shanghai`、`suspend=false`、`Forbid`、starting/active deadline `1800/3600`；Dashboard `1/1`、PostgreSQL 与两个 PVC 均 Ready/Bound，`/api/health` 返回 HTTP 200。CronJob 与 Dashboard/collector 均使用冻结镜像 tag，未启用扶摇四类数据集开关。
- 首个自然 Job `a-stock-data-collection-29845950` 于 16:30 创建，Pod 运行后以 exit code 2 结束并保留真实 `partial` 结果；`collection_runs.run_id=8a3a60fb61d347d8b3930c9ae7318273`、exact-date API `asOf=2026-09-30` 均已读回。五类任务为：core `success/sina-kline` 5 条、breadth `success/tdx-daily-package` 5564 条、limits `partial/fuyao+eastmoney` 80 条、sectors `failed-missing/none` 0 条、activeDirection `partial/eastmoney-clist` 30 条；失败原因和降级 warning 保留在任务记录与 Job 日志中。

## Remaining Gaps（剩余缺口）

- 行业 sectors 仍为 `failed-missing`（Eastmoney 主/延迟域网络失败，扶摇 sectors 保持关闭）；core、limits、activeDirection 仍带真实降级或 partial warning。CronJob 保持 active，后续盘后观察应继续记录质量，不得将这些状态改写为成功。

## Next Step（下一步）

保持 Helm CronJob active 和扶摇开关关闭；下一次盘后继续核对数据源恢复情况。若需停止调度，必须由责任人另行授权并使用 `--disable-schedule`，禁止裸 `kubectl patch`。
