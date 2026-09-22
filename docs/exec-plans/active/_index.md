# 活动执行计划

## 主计划

- [`document-truenas-podman-k3s-deployment.md`](document-truenas-podman-k3s-deployment.md) — TrueNAS Podman 到 k3s 部署教程
- [`consolidate-helm-managed-scheduling.md`](consolidate-helm-managed-scheduling.md) — 将独立 CronJob 合并到 Helm chart

## 活动计划

| 计划 | 负责人 | 状态 | 最后更新 |
|------|--------|------|----------|
| `restore-truenas-nodeport-direct-access` | 资深后端工程师 | in-progress | 2026-09-05 |
| `deploy-to-truenas-k3s-192-168-1-20` | 资深运维专家 | completed | 2026-09-05 |
| `one-click-truenas-k3s-deployment` | Codex | completed | 2026-09-06 |
| `document-truenas-podman-k3s-deployment` | Codex | in-progress | 2026-09-02 |
| `index-combination-rework` | Codex | completed | 2026-09-04 |
| `enable-manual-market-data-collection-by-default` | Codex | completed | 2026-09-03 |
| `local-development-port-8001` | Codex | completed | 2026-09-04 |
| `consolidate-helm-managed-scheduling` | Codex | completed | 2026-09-17 |
| `canary-1-26-controller-timezone-20260917` | 操作发起人 | completed (canary 范围内) | 2026-09-17 |
| `canary-verified-20260917` | 操作发起人 | completed (controllerCanaryVerified 翻转为 true) | 2026-09-17 |
| `activate-scheduled-collection-20260917` | 操作发起人 | completed (--activate-schedule 成功, rev 21) | 2026-09-17 |
| `fix-scheduled-collection-stability-and-override` | Codex | completed-without-production-write | 2026-09-13 |
| `componentized-truenas-k3s-deployment` | Mika | completed | 2026-09-12 |
| `unified-local-timezone-dashboard` | 资深前端工程师 | in-progress | 2026-09-12 |
| `copy-index-values-and-normalize-default-date` | Codex | completed | 2026-09-13 |
| `restore-limit-ecosystem-data-availability` | Codex | completed-with-insufficient-provider-evidence | 2026-09-21 |
| `recover-fuyao-k3s-deployment-20260921` | Codex | completed-with-production-write | 2026-09-22 |
| `activate-scheduled-collection-20260922` | 操作发起人 | completed-activation-observation-pending | 2026-09-22 |
| `reactivate-fuyao-scheduled-collection-20260922` | Codex | in-progress | 2026-09-22 |
| `deploy-project-and-startup` | 资深后端工程师 | completed | 2026-09-15 |
| `fix-market-collection-effective-date-and-timezone` | Codex | completed-with-production-write-code-deploy-pending | 2026-09-15 |
| `fix-limit-and-active-direction-collection` | Codex | completed-without-real-provider-smoke | 2026-09-15 |
| `repair-and-deploy-market-services-20260915` | Codex | in-progress | 2026-09-15 |
| `migrate-sqlite-to-postgresql` | Codex | completed-without-production-write | 2026-09-16 |
| `remove-gate-abc-deployment-checks-20260917` | Codex | completed-without-production-write | 2026-09-17 |
| `refine-index-copy-format-20260921` | Codex | in-progress | 2026-09-21 |
| `evaluate-fuyao-market-data-provider` | Codex | in-progress | 2026-09-22 |

## 说明

- 完成计划及时归档到 `docs/exec-plans/completed/`
- 索引与 `active/` 实际文件保持一致
- 每个计划必须含字段：`Stage` / `Status` / `Acceptance` / `Completion Evidence` / `Remaining Gaps` / `Next Step`（标题中英任一即可，Gate 4 检查）
