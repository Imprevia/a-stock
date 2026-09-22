# 恢复扶摇版本 TrueNAS k3s 部署

## Stage

生产恢复与受控发布

## Status

completed-with-production-write

## Scope

- 保留 `a-stock-data` 与 `a-stock-postgresql-data` PVC，不删除、不替换、不扩容。
- 使用完整 Helm release packet 同时恢复 PostgreSQL、Dashboard 和暂停状态的 CronJob。
- Dashboard 使用已导入的扶摇版本镜像；CronJob 创建后保持 `suspend=true`，不触发采集 Job。
- 修复同一 Helm release 下分组件升级会删除兄弟资源的问题，避免再次出现数据库 Service 被移除。

## Acceptance

- PostgreSQL StatefulSet、ClusterIP Service 与原 PVC 恢复并 Ready，PVC UID 与恢复前一致。
- Dashboard Deployment 使用目标镜像并 Ready，`/api/health` 和 NodePort 首页返回成功。
- `a-stock-data-collection` 由 Helm 管理、镜像与 Dashboard 一致、扶摇 Secret 已注入且 `suspend=true`、active Job 为 0。
- Helm manifest 同时包含 database、service 与 schedule，release 状态为 deployed。
- 部署脚本回归测试、Helm lint/template、docs-contract 通过。

## Completion Evidence

- 只读预检确认 TrueNAS k3s `1.26.6+k3s-6a894050-dirty` 可达；PostgreSQL StatefulSet、Deployment、PVC、NodePort 与扶摇 Secret 均存在且健康。
- 线上 Helm revision 26 的 `a-stock-data-collection` 为 active，最近 Job 失败；扶摇 Secret 已注入，失败主要来自旧数据源缺失/拒绝。
- 使用与线上镜像匹配的旧 Chart packet 执行受控 `--disable-schedule`，Helm revision 27 已部署，stored manifest 已无 CronJob；由于 `helm.sh/resource-policy: keep`，live exact CronJob 被失败安全补偿为 `suspend=true` 并保留，当前等待入口级 retained-resource 清理。
- 新增入口校验：仅接受目标 release 所有、typed suspended 的 retained CronJob，通过受控删除并 server-observed absent；`bash -n` 与 `.venv/bin/pytest tests/test_truenas_scheduling_guard.py -q`（51 passed）通过。
- `--component all` 增加最终完整 Helm manifest consolidation，避免 database/service 分阶段写入后 release stored values 停留在 `component=service`；部署相关回归 `238 passed`。
- 2026-09-22 完成 TrueNAS k3s 受控发布：retained CronJob 已通过 `--disable-schedule` 删除并证明 absent；普通 `--component all` 构建并导入镜像 `localhost/a-stock-market-environment:20260922-185527-06c3fd7`，containerd digest 为 `sha256:d6a2ee15de39a78e9caeff69288b661979755f22da7df0ab8560d2d8c465ca8c`，Helm revision 33 deployed，最终 stored `component=all` 且调度 disabled/absent。
- 写后验收：Dashboard 与 PostgreSQL Pod 均 `1/1 Running`，两个 PVC 保持 Bound，NodePort `32001` 的 `/api/health` 返回 `{"status":"ok"}`，首页返回成功；扶摇 Secret 仍通过 `a-stock-market-provider/MARKET_ENVIRONMENT_FUYAO_API_KEY` 引用，未回显值。

## Remaining Gaps

- 采集任务失败原因和扶摇四类非 limits 数据集的可替换性仍保持 `degraded`/`unverified`，不得借部署结果宣称替换完成。
- 当前仅保留历史失败 Job 记录；没有 active Job，CronJob 未创建。后续如需启用调度，必须走单独的 `--release-suspended`/`--activate-schedule` 审批流程。

## Next Step

保持当前 disabled/absent 状态；若要启用盘后采集，先完成独立 canary、镜像 digest 与 catch-up 授权，再使用专用调度入口。
