# 恢复行业板块独立 Provider 回退

## Stage

Stage 1 — 扶摇同花顺行业指数契约、能力门禁、采集回退和前端日期归一。

## Status

implementation-complete-with-controlled-service-rollout-observed（23/23 OpenSpec tasks complete；扶摇行业正式开关与定时采集保持关闭）

## Scope

- 将扶摇行业适配器从未公开的行业 ranking 路径改为交易日历、同花顺行业目录和批量行情快照组合。
- 仅在东方财富主域与延迟域均失败、开关开启、能力报告为 `eligible` 且批准 revision 完全匹配时启用扶摇 fallback。
- 保留 `SectorRow` 兼容结构；扶摇不提供的资金流、涨跌家数和领涨股字段保持 `null`，并输出降级 warning。
- 保持精确上海交易日、同日期失败留存、provider-free 读取和 shadow 可观测边界。
- 修复核心日期被服务端归一后，前端 lazy `sectors` 请求仍使用原始周末/节假日的问题。

## Acceptance

- 目录和快照契约验证 320 条行业覆盖、唯一身份、稳定排序、批次时间一致性和精确交易日；不完整或日期不可证明时 fail-closed。
- 扶摇 fallback 的来源、批准 revision、前序 Eastmoney warning、缺失字段 warning 和失败留存可从任务/快照/status 读取；GET/status 不触发 provider 请求。
- 默认部署开关保持关闭，Secret 只通过 existingSecret 注入，不进入 values、日志、报告或 API payload。
- 后端 focused pytest、前端 Vitest/build、docs sync-check、docs-contract full 和 OpenSpec strict validate 通过。
- 真实 probe/shadow 仅在显式授权隔离环境执行且只形成脱敏 evidence，不写正式快照；生产 Helm 开关与 PostgreSQL 写入仍保持关闭。

## Completion Evidence

- 规划证据：`openspec validate restore-sector-data-via-independent-provider --strict` 已通过；扶摇目录 320 条、行情快照 320/320 的只读探针已确认可提供代码、名称、涨跌幅和成交额。
- 当前 Eastmoney 行业主域与延迟域断连证据沿用数据采集 status/collection 审计；扶摇缺少主力净流入、主力净流入比例、上涨/下跌家数和领涨股字段，必须以 `null` + warning 表达。
- 文档/部署边界已同步：`docs/architecture.md`、`docs/runbooks.md`、`docs/product-specs/market-environment-dashboard.md` 和 `docs/status.md` 已记录 THS 三 endpoint、exact-date/字段降级、默认关闭、approved revision、Secret 注入、provider-free 读取与回滚步骤；`tests/test_deployment_manifests.py` 覆盖 sectors 默认关闭、revision/env 显式注入和 Secret 不渲染。
- 部署 manifest focused suite：`.venv/bin/python -m pytest tests/test_deployment_manifests.py -q`（188 passed）；`openspec validate restore-sector-data-via-independent-provider --strict` 通过。
- 2026-09-29 在显式盘后授权环境执行 sectors 只读 real probe（不写正式快照）：`/tmp/fuyao-sectors-capability-2026-09-29.json`。交易日历命中 `2026-09-29`，行业目录 320、快照 320/320、覆盖率 1.0、4 批时间一致；脱敏报告 revision `fuyao-market-v1` 为 `eligible`，API key 未出现在报告。扶摇仅提供代码/名称/涨跌幅/成交额，5 个可选字段保持缺失证据。
- 2026-09-29 受控隔离采集使用临时 SQLite：正常 Eastmoney 路径记录 `source=eastmoney-clist`、`status=partial`；在注入已批准报告并模拟 Eastmoney 双端点失败后，扶摇采集记录 `source=fuyao`、`status=partial`、`observations=10`、`asOf=2026-09-29`、`capabilityRevision=fuyao-market-v1`，并保留 Eastmoney 失败与 `mainNet/mainNetPct/upCount/downCount/leader` 缺失 warning。证据目录为 `/tmp/fuyao-sectors-fallback2.xu1Wm8`，未写正式快照或 PostgreSQL。
- 同一隔离 store 的 provider-free `/api/market-environment/data-collection?as_of=2026-09-29` 和 `/api/market-environment/collection-runs/c67290c0c5cd4a5e961843319ee54198` 返回 200，返回 source、revision、quality、warning 和 exact-date；关闭扶摇开关后再次采集得到 `failed-retained`，快照仍为同日期 `source=fuyao/status=fallback`。只含 sectors 的临时 store 缺少 core 聚合，因此 `chapter-01` 不作为完整页面成功证据。
- 受控过程中修复了 `fuyao real-probe` CLI 分支不可达问题，并将 collection task `timings` API 契约扩展为可携带数值计时与字符串来源/失败元数据；API/扶摇集成 focused suite 为 27 passed + 11 passed。
- 2026-09-29 完成受控 service 发布验收：Helm release `a-stock` revision `61`，镜像 `localhost/a-stock-market-environment:20260929-112653-c833a02`，containerd digest `sha256:aac8dc0fea4e91837ec5d9d80cb7ad7629357e91f3a2720574aaabf0393632aa`，packet digest `c19095b773efe7eb39549a74417fa00f6075d3f0fd78e32038b905b5b56a0645`；`/api/health` 返回 200/`status=ok`，Dashboard Deployment/Pod、PostgreSQL StatefulSet 和两个 PVC 均 Ready/Bound 且无重启，CronJob 列表为空。OpenAPI 的 `CollectionAttemptSummary`/`CollectionTaskResponse` 已暴露 `timings`。
- 全库验证：`.venv/bin/python -m pytest tests -q`（717 passed, 3 skipped）；前端 `npm run test -- --run`（126 passed）和 `npm run build` 通过；`docs sync-check`、`docs-contract --mode=full`、OpenSpec strict 均通过。

## Remaining Gaps

- 本次行业 fallback 观察仍使用隔离 SQLite，采集发生在结算前且任务 `settled=false`，不构成盘后生产 sectors 快照；本次 service 发布未启用扶摇行业开关，也未创建或切换定时 CronJob。
- 正式行业生产启用仍需单独受审的盘后窗口、批准 revision、数据库写入授权和调度 packet；失败时沿用本次已验证的关闭开关与同日期留存回滚路径。
- 代码全量门禁已通过；390px 视口由前端 Vitest 覆盖，部署 manifest focused suite 已通过。

## Next Step

OpenSpec change 已完成并具备归档条件；service 发布已通过健康与持久化验收。行业 fallback 仍需另行按 runbook 进行盘后审批和受控采集观察，`MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED=0`、`MARKET_ENVIRONMENT_FUYAO_SECTORS_SHADOW_ENABLED=0` 与 `suspend=true` 保持不变。
