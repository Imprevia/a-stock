# 恢复扶摇版本 TrueNAS k3s 部署

## Stage

生产恢复与受控发布

## Status

in-progress

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

- 待补充。

## Remaining Gaps

- 当前 release 因分组件 Helm upgrade 缺少 PostgreSQL StatefulSet/Service，Dashboard 为 `CrashLoopBackOff`。
- 定时任务虽保持 `suspend=true`，但仍使用旧镜像。

## Next Step

离线渲染完整暂停 packet，核对资源/PVC/Secret/镜像后执行一次原子 Helm 恢复，再修复部署脚本并完成回归验证。
