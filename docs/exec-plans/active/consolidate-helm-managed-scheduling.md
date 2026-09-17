# 把独立 CronJob 合并到 Helm chart

## Stage（阶段）

续接 `repair-and-deploy-market-services-20260915` 的双 owner 现状：删除非 Helm-owned 的 legacy `market-data-collection`，由 Helm release 创建 release-derived `a-stock-data-collection`，统一所有权；同时把 overlay 文件的 schedule 字段对齐到现网（`30 16 * * 1-5` + `Asia/Shanghai` controller 策略），保持 `suspend=true` fail-closed 默认。

## Status（状态）

`completed` · PostgreSQL、Dashboard、历史数据迁移与 suspended Helm CronJob 已在 TrueNAS k3s 发布并通过运行时核对；全量测试与文档门禁通过，CronJob 按计划保持 `suspend=true`。

## Scope（范围）

- 修订 `deploy/truenas/values-scheduled-suspended.yaml` 与 `deploy/truenas/values-scheduled-active.yaml`：把 `schedule` 改为 `30 16 * * 1-5`、`controllerTimeZone: Asia/Shanghai`，与现网 live 一致；chart 校验逻辑（controller strategy → schedule 与 controllerTimeZone 匹配）已能通过。
- 新建 `deploy/truenas/values-scheduled-baseline-20260917.yaml`：合并 `values-secure-manual-collection.yaml`（service 段）与修订后的 schedule overlay，锁定 `image.repository: localhost/a-stock-market-environment`、`image.tag: 20260917-113516-b5be526`、`image.pullPolicy: IfNotPresent`、`database.enabled: true`、`database.existingSecret: a-stock-postgresql`、`persistence.existingClaim: a-stock-data`、`marketEnvironment.scheduledCollection.enabled: true / suspend: true / controllerTimeZoneVerified: true / controllerCanaryVerified: false`。
- 删除独立 CronJob 与专用存储资源模板：`deploy/k3s/persistent-volume-claim.yaml`（legacy `market-environment-data` PVC）、`deploy/k3s-native-scheduled/persistent-volume.yaml`、`persistent-volume-claim.yaml`、`storage-class.yaml`、`deploy/truenas/market-data-collection-cronjob-1.26-controller-shanghai.yaml`。共享 `manual-local` StorageClass 实际承载 `a-stock-data` 与其他 namespace 的 PV，保留不删。
- 在 `tests/fixtures/truenas_component_baseline.yaml` 顶部说明 `a-stock-data` PVC 实际使用 `local-path` SC，baseline 字段仅作 fixture 协议占位，不约束 `storageClass`。
- 同步 `docs/runbooks.md`、`docs/status.md`、`docs/exec-plans/active/_index.md`。
- 归档 `enable-scheduled-collection-direct-apply.md` 与 `enable-truenas-scheduled-market-collection.md` 到 `docs/exec-plans/completed/`，并保留 evidence 链接。
- 不在范围：dashboard 业务改动、PostgreSQL 迁移、SQLite 缓存路径改造、`FROZEN_IMAGE_*` digest 进一步加固。

## Acceptance（验收）

- 仓库层：`deploy/truenas/values-scheduled-suspended.yaml` / `values-scheduled-active.yaml` 的 `schedule` 均为 `30 16 * * 1-5`、`controllerTimeZone: Asia/Shanghai`；`values-scheduled-baseline-20260917.yaml` 锁定的镜像 tag、database secret、persistence existingClaim 与 baseline 一致；旧 PVC/PV/CronJob 模板已删除，**共享 `manual-local` StorageClass 保留**；`docs/runbooks.md` 新增 `### Helm schedule 组件（合并所有权）` 章节；active plan 6 字段齐全；`enable-scheduled-collection-direct-apply.md` 与 `enable-truenas-scheduled-market-collection.md` 已归档到 `docs/exec-plans/completed/`。
- 集群层：legacy `market-data-collection` absent，集群中只有 release-derived `a-stock-data-collection` CronJob，`app.kubernetes.io/managed-by=Helm`，`SUSPEND=True`，schedule `30 16 * * 1-5`，无 `spec.timeZone`（controller 策略）；镜像与上一份 release 一致 `localhost/a-stock-market-environment:20260917-113516-b5be526`；无 `market-environment-data` PVC、`a-stock-market-environment-data` PV；共享 `manual-local` SC 保留且仍用于 `a-stock-data`；Helm revision 20 deployed；`/api/health`、首页以及 `/api/market-environment?as_of=2026-09-16` 均返回 200 和有效数据。

## Completion Evidence（完成证据）

**仓库层（2026-09-17）：**

- `deploy/truenas/values-scheduled-suspended.yaml` / `values-scheduled-active.yaml` 已统一为 controller `Asia/Shanghai` + `30 16 * * 1-5`；新建 `values-scheduled-baseline-20260917.yaml`，锁定 live revision 14 镜像 `localhost/a-stock-market-environment:20260917-113516-b5be526`。
- 删除 legacy 独立 CronJob/PVC/PV/SC 模板、operator override 两个脚本及其专测；部署清单测试改为断言 Helm overlay 的 `30 16`。
- `helm lint deploy/helm/a-stock -f deploy/truenas/values-scheduled-baseline-20260917.yaml --set component=schedule --kube-version 1.26.6` 通过；`helm template` 输出 `a-stock-data-collection`、`suspend: true`、`schedule: 30 16 * * 1-5`、无 `spec.timeZone`、镜像 tag 正确。
- `python3 scripts/render-k3s.py --kube-version 1.27.0` 通过并输出 native CronJob `timeZone: Asia/Shanghai` + `30 16 * * 1-5`。原计划中的 `--baseline-values` 不是该脚本支持的参数，1.26 baseline 改由 Helm lint/template 验证。
- 最终全量 pytest：`581 passed, 3 skipped, 2 warnings`；隔离 PostgreSQL 16.4 集成测试：`11 passed`；`python3 scripts/check-docs-contract.py --mode=full`：通过（代码 8 / 文档 17 / plan 7）；1.26 Helm lint/template、`python3 scripts/render-k3s.py --kube-version 1.27.0` 与 `git diff --check` 均通过。

**集群写入与运行时证据（2026-09-17，Asia/Shanghai）：**

- Helm revision 19 完成 PostgreSQL + Dashboard 切换；revision 20 通过 `--release-suspended` 创建唯一的 `a-stock-data-collection`。stored manifest 含 1 个 CronJob，live 读回为 Helm-owned、`suspend=true`、`30 16 * * 1-5`、无 `spec.timeZone`、`Forbid`、deadlines 1800/3600，镜像为 baseline tag。
- PostgreSQL 16.4 StatefulSet 与 Dashboard Deployment 均为 `1/1 Ready`；`a-stock-postgresql-data` 为 5Gi Retain RWO Bound PVC，`a-stock-data` 仅保留为旧 SQLite 迁移输入。schema migration 为 `0001_postgresql_initial`。
- SQLite source SHA-256 `c7375ffef7b668f20d4be48f19a94a23dcbdffbfaf038031a699eee31eafde84`，`quick_check=ok`。导入最终状态 `applied`，`snapshot_entries=46`、`core_index_results=65`、`materialized_market_environment=10`、`collection_runs=31`，所有有数据表 `verified=true`，active lease 为 0。
- 生产 dry-run 暴露并修复三项问题：migration Pod 缺少 `fsGroup=10001`；只读 WAL 源需在停写和哈希固定后使用 `immutable=1`；revision trigger 与通用 `DO NOTHING` 冲突。隔离 PostgreSQL 16.4 集成测试 `11 passed`，正式导入第一次校验失败时完整回滚，第二次通过。
- `market-data-verify`、`market-environment-data` PVC、`a-stock-market-environment-data` PV 与 exact 主机旧目录已清理；共享 `manual-local` 因仍承载 `a-stock-data` 和 `multica/manual-postgres-pv` 保留。
- `/api/health` 与首页返回 200；`/api/market-environment?as_of=2026-09-16`、`/api/market-environment/core?as_of=2026-09-16` 均返回 200，包含 5 个指数且 `dataGaps=0`。盘中默认 2026-09-17 请求按 exact-date 契约返回 503，不回退旧日期。

## Remaining Gaps（剩余缺口）

- CronJob 按计划保持 `suspend=true`，尚未执行 controller timezone canary，也未验证首次自然 16:30 触发；这不是本次 suspended release 的失败。激活必须另行取得授权并走 `--activate-schedule`。
- 应用与 CronJob 仍锁定 `20260917-113516-b5be526` 可变 tag；迁移修复镜像 `20260917-124501-31c3ea2` 仅用于一次性 Job。后续可扩 chart 的 `image.digest` contract，但不在本计划范围。
- PostgreSQL chart 仍声明官方 `postgres:16.4` digest，而离线导入后依赖本地 containerd alias。运行日志已确认 PostgreSQL 16.4；后续应改为可审计 mirror repository + 实际 manifest digest。

## Next Step（下一步）

1. 保持 `suspend=true`，在单独变更中完成 controller timezone canary、catch-up 决策与书面授权后，才允许通过 `--activate-schedule` 激活。
2. 激活后的首个交易日 16:30 观察 Job/Pod、PostgreSQL collection run、五个 dataset quality 与 API exact-date 响应。
3. 单独加固 PostgreSQL 离线镜像的 repository/digest 证据，不改变现有 PVC 或已导入历史数据。
