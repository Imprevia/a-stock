# 移除 Gate A/B/C 部署授权校验（2026-09-17）

## Stage（阶段）

把"将项目部署到 k3s 上"任务中残留的 Gate A/B/C 授权需求（未完成且脚本里强制校验）从仓库事实源中彻底移除，让后续运维/部署走"专用调度入口 + 操作责任人书面确认 + FROZEN_IMAGE_* 三元组"即可，不再依赖 Gate A/B/C 环境变量和 reviewed-source SHA256 绑定。

## Status（状态）

`completed-without-production-write` · 代码、脚本、模板、fixture、测试、文档与 openspec 变更已闭环清理；未执行正式 Helm 发布、远程 SSH、生产写入或 CronJob 切换。

## Acceptance（验收）

- `scripts/deploy-truenas-k3s.sh` 不再加载、读取或校验 `SERVER_DRY_RUN_AUTHORIZED` / `SUSPENDED_RELEASE_AUTHORIZED` / `SCHEDULE_ACTIVATION_AUTHORIZED` / `SCHEDULE_ROLLBACK_AUTHORIZED` / `GATE_B_AUTHORIZATION_REF` / `GATE_C_AUTHORIZATION_REF` / `SCHEDULE_ROLLBACK_AUTHORIZATION_REF` / `REVIEWED_GIT_HEAD` / `REVIEWED_CHART_SHA256` / `REVIEWED_BASELINE_SHA256` / `REVIEWED_OVERLAY_SHA256` / `REVIEWED_RENDER_SHA256`。
- `deploy/truenas/deploy.env.example` 不再列出上述环境变量；保留 `ACTIVATION_CATCH_UP_MODE` 与 `FROZEN_IMAGE_*`。
- `tests/fixtures/truenas_component_baseline.yaml` 不再包含 `authorization` 块与 Gate A/B/C 注释；脚本对 fixture 的 schema 校验不再强制 `authorization.releaseSuspended / activateSchedule / disableSchedule`。
- `tests/test_truenas_scheduling_guard.py` 中已删除的 5 个 Gate 授权/绑定测试不再保留孤儿 `parametrize` 块；新增的 51 用例全部通过。
- `openspec/changes/enable-truenas-scheduled-market-collection/` 与 `openspec/changes/surface-scheduled-market-collection/` 已归档到 `openspec/changes/archive/2026-09-16-...`。
- docs/runbooks.md / docs/architecture.md / docs/status.md / docs/product-specs / docs/truenas-scale-24.04-podman-k3s-deployment.md / 5 个 active plan / componentized-truenas-k3s-deployment openspec change 中 Gate A/B/C 字面提及已收敛为"专用调度入口 + 操作责任人书面确认"，不再引用 `GATE_*_AUTHORIZATION_REF` 等环境变量。
- fail-closed 默认（`enabled=false / suspend=true`）、`FROZEN_IMAGE_*` 三元组校验、`ACTIVATION_CATCH_UP_MODE`（`next-schedule` / `immediate-catch-up`）校验保留。
- `bash -n scripts/deploy-truenas-k3s.sh`、`python3 scripts/check-docs-contract.py --mode=full`、`openspec validate --changes --strict` 与 focused 测试套件（`tests/test_truenas_scheduling_guard.py` + `tests/test_deployment_manifests.py` + `tests/test_scheduling_packet_validator.py` + `tests/test_truenas_operator_override.py`）全部通过。

## Completion Evidence（完成证据）

- `scripts/deploy-truenas-k3s.sh` 中 `verify_reviewed_sources` / `verify_rollback_authorization_ref` / `rollback_binding_payload` 等函数已移除；新增 `assert_clean_worktree`；`--activate-schedule` 仍校验 `ACTIVATION_CATCH_UP_MODE` 与 `FROZEN_IMAGE_*`；`--release-suspended` / `--disable-schedule` 仍校验 `FROZEN_IMAGE_*`。`bash -n` 通过；`bash scripts/deploy-truenas-k3s.sh --help` 正常；`bash scripts/deploy-truenas-k3s.sh --read-only-discovery` 实测输出 `Kubernetes 1.26.6+k3s-6a894050-dirty` 与现有 release history。
- `deploy/truenas/deploy.env.example`：移除 Gate A/B/C 字段 48 行；保留 `ACTIVATION_CATCH_UP_MODE` 与 `FROZEN_IMAGE_*` 三元组。
- `tests/fixtures/truenas_component_baseline.yaml`：移除尾部 `authorization` 块（`releaseSuspended` / `activateSchedule` / `disableSchedule`）及注释。
- `scripts/deploy-truenas-k3s.sh` 中 `load_component_baseline` 的 schema 校验：删除 `authorization = data.get("authorization") or {}` 与对应循环；fixture 不再被强制要求含 `authorization` 块。
- `tests/test_truenas_scheduling_guard.py`：删除 5 个 Gate 校验/绑定测试函数与对应 parametrize 块；删除 `test_server_dry_run_submits_only_exact_suspended_cronjob` 中 7 行无效 env 写入（`SERVER_DRY_RUN_AUTHORIZED=true` / `GATE_B_AUTHORIZATION_REF=reviewed-gate-b-packet` / `REVIEWED_GIT_HEAD=...` / `REVIEWED_CHART_SHA256=...` / `REVIEWED_BASELINE_SHA256=...` / `REVIEWED_OVERLAY_SHA256=...` / `REVIEWED_RENDER_SHA256=...`）。
- `scripts/validate-scheduling-packet.py`：fail 消息中 "Gate C" 字面替换为中性描述（"active release contains drift outside the suspended resource set" / "suspended release contains drift outside CronJob spec.suspend"）。
- README.md：行 65 / 行 89 的 Gate B/Gate C 提及替换为"专用调度入口 `--release-suspended` / `--activate-schedule` / `--disable-schedule`"。
- `deploy/truenas/values-scheduled-suspended.yaml` / `values-scheduled-active.yaml`：注释中 "Gate B" / "Gate C" 替换为对应专用入口名。
- `docs/runbooks.md` / `docs/status.md` / `docs/exec-plans/active/enable-scheduled-collection-direct-apply.md` / `docs/exec-plans/active/fix-scheduled-collection-stability-and-override.md`：移除"仓库内离线 Gate A 授权已记录"等历史性提及（已不再构成生产 CronJob 激活或回退的执行授权说明）。
- `openspec/changes/componentized-truenas-k3s-deployment/{design,proposal,specs/...,tasks}.md`：清理 Gate A/B/C 引用，保留 fail-closed 默认与专用入口说明。
- `openspec/changes/enable-truenas-scheduled-market-collection/` 与 `openspec/changes/surface-scheduled-market-collection/` 已移动到 `openspec/changes/archive/2026-09-16-...`。
- 验证：`bash -n scripts/deploy-truenas-k3s.sh` 通过；`python3 scripts/check-docs-contract.py --mode=full` 通过（代码 2 / 文档 11 / plan 5）；`openspec validate --changes --strict` 通过（6 passed / 0 failed）；focused 测试 312 passed（51 / 261）。
- `git grep -n "GATE_A\|GATE_B\|GATE_C\|gate-a\|gate-b\|gate-c\|Gate A\|Gate B\|Gate C"` 在 `scripts/ deploy/ tests/ docs/ README.md` 中已无匹配（archive 与 `.omo/` 为预期保留）。

## Remaining Gaps（剩余缺口）

- 真实 k3s 部署需要本次操作责任人书面确认，并在 plan 的 Completion Evidence 中记录 release/namespace/镜像 digest 与 catch-up 行为后再调用专用调度入口（`--release-suspended` / `--activate-schedule` / `--disable-schedule`）。
- `FROZEN_IMAGE_*` 三元组尚未在 `deploy/truenas/deploy.env`（私有环境文件，未触碰）中落地；普通 service 部署（`--component service`）无需该三元组。
- 生产定时采集的图像/数据采集未实际触发过；下一次窗口需先以 `bash scripts/deploy-truenas-k3s.sh --read-only-discovery` 复核 cluster state，再用专用入口执行迁移。
- 本次清理未修改 `deploy/truenas/deploy.env`（私有环境文件）。

## Next Step（下一步）

按本次操作责任人的书面确认调用 `scripts/deploy-truenas-k3s.sh` 的专用调度入口或普通 service 入口；如需进一步推进，把 enable-truenas-scheduled-market-collection / enable-scheduled-collection-direct-apply / fix-scheduled-collection-stability-and-override / repair-and-deploy-market-services-20260915 中与 Gate A/B/C 相关的 active plan 同步移入 `docs/exec-plans/completed/`。
