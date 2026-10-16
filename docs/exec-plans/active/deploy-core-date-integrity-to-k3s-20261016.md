# 部署跨日期完整性修复到 TrueNAS k3s（2026-10-16）

## Stage（阶段）

生产发布与发布后只读验证已完成。

## Status（状态）

completed-with-production-write

## Scope（范围）

- 将已推送并审阅的 `main` commit `31a8f9099af697e71763546afef25d668dbb42c2` 通过仓库受支持的 TrueNAS k3s 普通发布入口部署到 `a-stock` namespace / Helm release。
- 使用洁净 detached worktree 和 `--component all`，按 database → schema migration → service → full-release convergence 顺序发布不可变镜像。
- 保持现有 live values、Secret/PVC identity、NodePort、单副本拓扑、manual/automation 开关与调度所有权不变。
- 不调用 provider，不触发 collection，不执行 PostgreSQL 数据修复，不创建或激活 Kubernetes CronJob，不删除 Secret、PVC/PV，不使用 `helm uninstall` 或历史 revision 回滚。

## Acceptance（验收）

- 发布候选 commit 与 `origin/main` 一致，部署源 worktree 洁净且 `REVIEWED_GIT_HEAD` 精确绑定。
- Helm lint、k3s 1.26.6 离线 render、部署相关测试与 docs-contract 通过，render 不含 application CronJob。
- 只读生产预检证明节点、Dashboard/PostgreSQL、PVC、Secret、当前 Helm release、两个历史 CronJob identity 和 namespace Job 满足 fail-closed 合同。
- 受控入口完成镜像构建、smoke、传输、containerd 导入和 Helm 收敛；Deployment rollout 成功且 Ready Pod 的 tag/imageID 与冻结 digest 一致。
- 发布后 `/api/health`、首页、一个已知合法历史日期 v2 overview、effective-date v2 overview 与 legacy core 均符合 200、404/missing 或稳定 503 `snapshot_integrity_error`，不得出现 500 或跨日期成功响应。
- provider、collection run/task、PostgreSQL 数据修复、Secret/PVC、CronJob/Job 与调度状态不因本次发布发生未授权变化。

## Completion Evidence（完成证据）

- 发布候选为 clean detached commit `31a8f9099af697e71763546afef25d668dbb42c2`，与执行时 `origin/main` 一致；现有未跟踪嵌套仓库和并行 OpenSpec change 均未进入候选或镜像。
- 离线门禁通过：部署脚本 `bash -n`、docs-contract full、Helm strict lint、k3s 1.26.6 render、live manifest 非 hook 语义对比均为 exit 0，render 不含 CronJob；`tests/test_deployment_manifests.py` 与 `tests/test_truenas_scheduling_guard.py` 合计 `196 passed`。
- 发布前只读基线为 Helm revision 123、Dashboard/PostgreSQL `1/1`、两个 PVC Bound、两个历史 CronJob identity 和 namespace Job absent。冻结 live values SHA-256 为 `9a5a1d18abd8f0bd436c70cd41d4f69c9754d68b25d8764b3591b21d598f8000`，保留 `manual=1`、`automation=1`、THS writer 与 Fuyao sectors 既有开启状态；预发布 smoke 复现问题日期 v2 overview 500、legacy core 503。
- 2026-10-16 18:48–18:57 Asia/Shanghai 使用 `scripts/deploy-truenas-k3s.sh --component all` 完成受控发布。镜像为 `localhost/a-stock-market-environment:20261016-184821-31a8f90`，archive SHA-256 `aff17fcd72d22ccc713c89e115c5f831fced6bd90c5570ac13e6eb45a8b02741`，containerd manifest digest `sha256:9dbfa29ee2b9f62776517fb59b23cd447adf5469eee08ea4baaf43b6aee2c4cb`。
- database/service/final convergence 分别完成 revisions 124/125/126；schema hook 只在 database 阶段执行一次并成功清理，最终 schema/Alembic 仍为 `11 / 0008_collection_idempotency`，namespace CronJob/Job absent。
- Deployment `a-stock` 为 `1/1`，Pod `a-stock-75f648db67-6q5tl` Ready、0 restart，运行时 imageID `sha256:63c6ddb82d4d628466e010a134489d8d7f66f39de6414af05197809c2ca3e066`；PostgreSQL `1/1`、0 restart。两个 PVC UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe` / `6c426fc5-10e2-4e88-b534-b258c70869c4` 与两个 Secret UID `81b9d039-7d77-44bc-9c4f-41b9ce2e19b2` / `653a79bf-a881-43de-8623-2d9f69e9aa0f` 均未变化。
- revision 126 的 live values 相比 revision 123 仅 `image.tag` 从 `20261016-150003-d5e00c2` 变为 `20261016-184821-31a8f90`；`manual=1`、`automation=1`、NodePort `32001`、Secret/PVC、单副本拓扑、provider/THS/Fuyao gate 与调度状态均保持既有合同。
- 发布后 `/api/health`、首页、`2026-10-15` v2 overview 分别为 200/200/200；`2026-10-16` v2 overview 与 legacy core 均为 503，响应稳定 code `snapshot_integrity_error`，不再出现 v2 500 或跨日期 200。
- 发布后业务 GET 前后 `snapshot_entries=129`、`materialized_market_environment=31`、`collection_runs=108`、`collection_tasks=263`、`core_index_results=190`、`collection_idempotency_bindings=2` 的内容指纹逐项一致；未调用 provider、未触发 collection、未写生产数据、未创建 CronJob/Job。

## Remaining Gaps（剩余缺口）

- 生产中既有 `2026-10-16` 错位记录仍保留并由新版本稳定拒绝；本次发布未执行数据修复。任何前向修复仍需独立 active plan、writer freeze、可恢复备份、目标行审阅和明确授权。

## Next Step（下一步）

维持只读健康观察；若用户授权修复既有错位记录，严格按 runbook 新建修复计划，不得自动 relabel、跨日期 copy、直接编辑 payload/checksum 或删除 PVC。
