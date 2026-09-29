# 激活盘后定时采集（2026-09-29）

## Stage（阶段）

调度 packet 审核、suspended CronJob 发布、激活与首个自然触发观察。

## Status（状态）

activated-observation-pending（revision 70 已激活；等待首个自然触发后的采集质量观察）

## Acceptance（验收）

- 使用 reviewed clean HEAD、冻结镜像和唯一 baseline/overlay packet；不启用扶摇行业开关，不创建 canary/provider-backed Job。
- 先创建 `a-stock-data-collection` 的 `suspend=true` CronJob，再通过 `--activate-schedule` 只改变 `spec.suspend: true -> false`。
- `next-schedule` 时间窗在 preflight 和 Helm 写入前均通过；写后 Helm、CronJob、Dashboard、PostgreSQL、PVC 和镜像状态可读回并与 packet 一致。
- 激活后由后续观察记录首个自然触发的 Job/Pod、五类数据质量、`collection_runs` 和 exact-date API 结果；失败保留真实 `partial`/`degraded`/`insufficient` 状态。

## Completion Evidence（完成证据）

- 2026-09-29 11:50（Asia/Shanghai）操作发起人明确授权激活定时任务；只读发现确认 k3s `1.26.6+k3s-6a894050-dirty`、release `a-stock`/namespace `a-stock` 为 Helm revision `61`，当前调度 disabled 且 CronJob absent。
- 当前运行镜像为 `localhost/a-stock-market-environment:20260929-112653-c833a02`；containerd manifest digest 为 `sha256:923b17bf8fbdcb787ec695a0f9e8e11f6c780bfa886cf7ff48ae2ffdf2f9f82d`，运行时 imageID 为 `sha256:aac8dc0fea4e91837ec5d9d80cb7ad7629357e91f3a2720574aaabf0393632aa`。
- clean reviewed packet 使用 chart SHA `696bd24855ada88be75ca902126b3a364a4f4844ac50635ba68ef17dc069de29`、baseline SHA `2d52fd6b798f6128b39f4ec5e0cd36ddc59b03fef41e425e0cccbd15ba1c9994`、suspended overlay SHA `97d0455d7ab5162989eba1c22969225e8c9c810878663755994f308600a7877c`、active overlay SHA `cf66bee36cea2a58c77a1e21f688d20642116d9913f857830c7c00c8a5d3f1e8`；full suspended/active render SHA 分别为 `821d15f5643f53aeb9c513baae27f69e95000397d857c38b2e273088b87d0be1` 和 `c84c3fc411d9ac9b738d534b1e8f3582bb8fbf368f1f377c14be5f04f4a0af1a`。
- revision `68` 先恢复 database + service 的完整 Helm ownership 且保持 schedule absent；revision `69` 通过 `--release-suspended` 添加 `suspend=true` CronJob；revision `70` 于 2026-09-29 12:18:34（Asia/Shanghai）通过 `ACTIVATION_CATCH_UP_MODE=next-schedule --activate-schedule` 仅解除暂停。preflight/pre-write 均确认下一自然触发为 2026-09-29 16:30（Asia/Shanghai），未创建 catch-up、canary 或 provider-backed Job。
- revision `70` 的 stored manifest 包含 PostgreSQL PVC/Service/StatefulSet、Dashboard Service/Deployment 和 `a-stock-data-collection` CronJob。CronJob 为 `30 16 * * 1-5`、`suspend=false`、`concurrencyPolicy=Forbid`、starting/active deadline `1800/3600`，当前无 active/last schedule 且 namespace 内无 Job。
- Dashboard 与 PostgreSQL 均 `1/1 Ready`，`a-stock-data` 和 `a-stock-postgresql-data` 均 `Bound`，`GET /api/health` 返回 `{"status":"ok"}`。Deployment 与 CronJob 的 `MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED` 均为 `0`，本次激活未启用扶摇行业 fallback。

## Remaining Gaps（剩余缺口）

- 首个自然触发后的 provider、PostgreSQL `collection_runs`、五类 dataset quality 和 exact-date API 尚未观察。

## Next Step（下一步）

在 2026-09-29 16:30（Asia/Shanghai）首个自然触发完成后，只读核对 Job/Pod、`collection_runs`、五类 dataset quality 与 exact-date API；保持扶摇行业 fallback 关闭，失败按真实 `partial` / `degraded` / `insufficient` 状态记录。
