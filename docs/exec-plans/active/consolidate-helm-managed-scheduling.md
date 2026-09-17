# 把独立 CronJob 合并到 Helm chart

## Stage（阶段）

续接 `repair-and-deploy-market-services-20260915` 的双 owner 现状：删除非 Helm-owned 的 legacy `market-data-collection`，由 Helm release 创建 release-derived `a-stock-data-collection`，统一所有权；同时把 overlay 文件的 schedule 字段对齐到现网（`30 16 * * 1-5` + `Asia/Shanghai` controller 策略），保持 `suspend=true` fail-closed 默认。

## Status（状态）

`in-progress` · PostgreSQL、Dashboard 与 suspended Helm CronJob 已发布；旧 SQLite 数据导入的首次 dry-run 暴露 migration Job 的 `/tmp` emptyDir 缺少 Pod 级 `fsGroup`，当前正在修复并重新验证，CronJob 保持 `suspend=true`。

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
- 集群层（由本次操作责任人在窗口内执行）：legacy `market-data-collection` absent，集群中只有 release-derived `a-stock-data-collection` CronJob，`app.kubernetes.io/managed-by=Helm`，`SUSPEND=True`，schedule `30 16 * * 1-5`，无 `spec.timeZone`（controller 策略）；镜像与上一份 release 一致 `localhost/a-stock-market-environment:20260917-113516-b5be526`；无 `market-environment-data` PVC、`a-stock-market-environment-data` PV；共享 `manual-local` SC 保留且仍用于 `a-stock-data`；`helm list -n a-stock` revision +1；`/api/health` 与首页 200；`/api/snapshots` 返回有效数据；`python scripts/check-docs-contract.py --mode=full`、`pytest -q`、1.26 Helm render 与 `python scripts/render-k3s.py --kube-version 1.27.0` 通过。

## Completion Evidence（完成证据）

**仓库层（2026-09-17）：**

- `deploy/truenas/values-scheduled-suspended.yaml` / `values-scheduled-active.yaml` 已统一为 controller `Asia/Shanghai` + `30 16 * * 1-5`；新建 `values-scheduled-baseline-20260917.yaml`，锁定 live revision 14 镜像 `localhost/a-stock-market-environment:20260917-113516-b5be526`。
- 删除 legacy 独立 CronJob/PVC/PV/SC 模板、operator override 两个脚本及其专测；部署清单测试改为断言 Helm overlay 的 `30 16`。
- `helm lint deploy/helm/a-stock -f deploy/truenas/values-scheduled-baseline-20260917.yaml --set component=schedule --kube-version 1.26.6` 通过；`helm template` 输出 `a-stock-data-collection`、`suspend: true`、`schedule: 30 16 * * 1-5`、无 `spec.timeZone`、镜像 tag 正确。
- `python3 scripts/render-k3s.py --kube-version 1.27.0` 通过并输出 native CronJob `timeZone: Asia/Shanghai` + `30 16 * * 1-5`。原计划中的 `--baseline-values` 不是该脚本支持的参数，1.26 baseline 改由 Helm lint/template 验证。
- focused 部署测试：`295 passed`；全量离线 pytest：`577 passed, 3 skipped, 2 warnings`；`openspec validate --changes --strict`：6 passed / 0 failed；`python3 scripts/check-docs-contract.py --mode=full`：通过（代码 4 / 文档 15 / plan 7）；`git diff --check` 通过。

**集群只读发现（2026-09-17 10:24，Asia/Shanghai）：**

- `bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component schedule --read-only-discovery` 成功连接 `admin@192.168.1.20`，目标为 k3s `1.26.6+k3s-6a894050-dirty`，Helm release `a-stock` revision 14 deployed。
- live Helm values 为 `component: service`、`scheduledCollection.enabled=false / suspend=true`；Deployment/Service 健康，镜像 `localhost/a-stock-market-environment:20260917-113516-b5be526`。
- legacy `market-data-collection` CronJob 已 absent；release-derived `a-stock-data-collection` 也 absent。因此无需执行原计划的 legacy CronJob delete，但 Helm schedule 仍未发布。
- 节点已有目标镜像，containerd digest `sha256:77d4e40015d21ea0c96b8eb6d51651fbdbe9ac4a1d2acf62f0f03c276dbe9a95`。
- `a-stock` namespace **没有** `a-stock-postgresql` Service、StatefulSet 或 Secret；live Dashboard 仍挂载 `a-stock-data` 的 `/data/snapshots.sqlite3`。Helm CronJob 模板强制引用 PostgreSQL Service/Secret，当前不满足发布前置条件，故未执行 `--release-suspended`。
- `market-data-verify` Job 仍存在但状态为 Failed（BackoffLimitExceeded），引用 `market-environment-data` PVC；清理 PVC 前必须先精确删除该 Job。
- `market-environment-data` PVC 与 `a-stock-market-environment-data` PV 仍 Bound；目录 `/mnt/xiaomi/app-data/a-stock-market-environment` 为 `0777 root:root`。
- `manual-local` StorageClass 同时承载 `a-stock-data`（生产 Dashboard）与其它 namespace 的 `manual-postgres-pv`；删除它会破坏现有资源。与用户计划相比，此项已安全收敛为“保留共享 SC，只清理专用 PVC/PV/目录”。

**集群写入证据（待 PostgreSQL 前置完成后回填）：**

- 本地：`pytest` 套件结果（`tests/test_truenas_scheduling_guard.py`、`tests/test_deployment_manifests.py`、`tests/test_scheduling_packet_validator.py`、`tests/test_truenas_operator_override.py`）。
- 本地：`python scripts/render-k3s.py --kube-version 1.26.6` 输出 native/overlay CronJob 渲染。
- 本地：`python scripts/check-docs-contract.py --mode=full` 输出（代码 / 文档 / plan 行数与 Gate 4 检查）。
- 集群（待用户执行后回填）：
  - 写入前 `kubectl get cronjob,pvc,pv,sc,job -n a-stock` 截图与 `/tmp/legacy-cronjob-snapshot.yaml`。
  - 删除独立 CronJob 后 `kubectl get cronjob -n a-stock` 仅剩 Helm-owned `a-stock-data-collection` 一份。
  - `helm list -n a-stock` revision +1；`kubectl get cronjob a-stock-data-collection -n a-stock -o yaml` 含 `helm.sh/release-name: a-stock` 与 `app.kubernetes.io/managed-by: Helm`。
  - 清理后 `kubectl get pvc,pv -A | grep -E "market-environment-data|a-stock-market-environment-data"` 为空；`manual-local` SC 仍存在且 `a-stock-data` 绑定不变。
  - 节点 `ls -la /mnt/xiaomi/app-data/` 截图，权限恢复。
  - `/api/health` 200、首页 200、`/api/snapshots` 返回有效数据。

## Remaining Gaps（剩余缺口）

- 2026-09-17 首次生产 SQLite import dry-run 失败：容器以 UID 10001 运行，但 migration Job 未应用 chart 的 `podSecurityContext`，root-owned `emptyDir /tmp` 无法创建 before-image，CLI 返回 `unable to open database file`。需为 Job 补齐 Pod 级 `fsGroup`、增加渲染回归断言，并在重新 dry-run 通过后才允许 `--apply`。
- 集群侧操作未执行：当前目标不满足 Helm CronJob 的 PostgreSQL 前置条件（缺少 `a-stock-postgresql` Service/StatefulSet/Secret）。必须先按 `migrate-sqlite-to-postgresql` runbook 完成 database component、schema migration 与 service cutover，验证 Dashboard 已通过 PostgreSQL 工作，再单独执行本计划的 `--release-suspended`。
- `scripts/deploy-truenas-k3s.sh` 对 `--release-suspended` 强制 clean worktree；当前仓库包含本计划及前序 Gate A/B/C 清理的未提交改动，需先审阅并提交，再执行生产写入。不得用临时绕过方式禁用该保护。
- 2026-09-17 生产发布中发现冻结镜像校验把 CRI `status.imageID`（image config digest）错误等同于 containerd named image Target.digest（manifest digest）；docker archive 导入时两者分别为 `sha256:f2b301...` 与 `sha256:ace2e9...`。validator 已修为：Pod/Deployment 精确 tag + Pod Ready + 合法 CRI imageID，containerd 单独校验 tag→reviewed manifest digest，不再比较不同语义的 digest。
- legacy CronJob 当前已 absent，无需删除。迁移后的写入顺序调整为：数据库前置验证 → `--release-suspended` → 验证 `a-stock-data-collection` Helm ownership → 删除 Failed `market-data-verify` Job → 删除专用 PVC/PV → 删除 exact 主机目录。共享 `manual-local` SC 必须保留。
- 镜像 tag `20260917-113516-b5be526` 是按 `tagPattern: "%Y%m%d-%H%M%S-%h"` 生成的可变 tag，本次仍按既有流程锁定 tag（不强制 digest）。进一步加固 digest 锁定不在本计划范围。
- 主机 `/mnt/xiaomi/app-data` 原权限如非默认，需要在删除子目录后同步恢复（操作前先记录现权限）。
- 既有 dirty 工作树（来自前序 Gate A/B/C 清理与归档）按 AGENTS.md 不 stash/reset/checkout；本计划合并前对 overlay 的字段更新会与这些 dirty 共存。

## Next Step（下一步）

1. 先按 `migrate-sqlite-to-postgresql` runbook 发布 `database` component、创建/验证 `a-stock-postgresql` Secret、执行 schema migration，并完成 Dashboard service cutover；该步骤不属于本次 schedule ownership 合并的授权范围。
2. PostgreSQL 前置完成后，在 16:30 之外用已冻结的镜像三元组执行 `--release-suspended`，验证 Helm-owned `a-stock-data-collection`。
3. 只在新 CronJob 精确读回后，删除 Failed `market-data-verify` Job、专用 PVC/PV 与 exact 主机目录；保留共享 `manual-local` SC。
4. 观察下一交易日 CronJob 实际状态；保持 `suspend=true` fail-closed 直至专门通过 `--activate-schedule` 入口激活。
