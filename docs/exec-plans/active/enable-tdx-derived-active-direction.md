# 启用 TDX 派生容量方向

## Stage

实现、离线验证与受控生产发布

## Status

production-deployed-first-natural-job-pending

## Acceptance

- Eastmoney 主域和延迟域均失败后，独立开关开启时才使用精确日期 TDX 包派生 `activeDirection`。
- 派生结果使用 `tdx-daily-package-derived` / `fallback-derived`，记录本地排序、TDX revision、行业映射覆盖率和前序 warning；默认关闭且不改变 breadth 开关。
- TDX 派生结果可写入精确日期快照，但 collection task 和父 run 为 `partial`；失败保持 `failed-retained` / `failed-missing`，不跨日期回填。
- 普通市场 GET、数据采集状态 GET 和 real probe 不触发 provider-free 之外的写入；real probe 只在 `--allow-real` 下运行并输出脱敏报告。
- 前端显示本地派生质量、来源、排序和行业映射边界，Top-10 字段保持兼容。

## Completion Evidence

- 已完成 provider/config/Helm 链路改造、版本化行业映射边界、`fallback-derived` 快照与 collection `partial` 映射。
- 已补齐后端和前端的派生质量契约测试源码，并通过 `python3 -m compileall -q src tests`。
- 已补齐 TDX real probe 的显式授权和脱敏报告字段；2026-09-23 隔离 probe 成功，报告写入 `/tmp`，未写快照或数据库：包日期一致，沪 `27383` / 深 `24160` / 北 `378`，总行数/有效行数 `51921`，名称覆盖 `1.0`，排序方法为 `local-turnover-desc-identity-asc`，行业映射覆盖 `0.0`，最终质量 `fallback-derived`。
- 离线验证已通过：`.venv/bin/python -m pytest tests -q` 为 `680 passed, 3 skipped, 2 warnings`；Dashboard Vitest 为 `122 passed`；Vite build、Helm lint/render、`python scripts/check-docs-contract.py --mode=full`、OpenSpec strict、docs sync-check、rules validate/coverage 均通过。
- 2026-09-24 受控生产发布完成：旧 active CronJob 先经 revision 51/52 停用并删除；修复后的服务镜像 `20260924-000048-188a2d9`、manifest digest `sha256:c615af6199b53c42df4abd3350dfc7347f39dba8e9220c2e499e28f3aa9cbbb1` 在 revision 55 完成 Dashboard rollout，revision 56 创建暂停 CronJob，revision 57 按 `next-schedule` 激活。
- 生产写后只读验收通过：Deployment/CronJob 均 `1/1`、新开关为 `1`、CronJob 为 `30 16 * * 1-5` 且 `suspend=false`、PostgreSQL/PVC 为 Ready/Bound、`/api/health` 为 `ok`；`/api/market-environment?as_of=2026-09-23` 返回 `activeDirection.source=tdx-daily-package-derived`、`quality.status=fallback-derived`、文档 06 为 `partial`，数据状态接口不再出现 fallback-derived 枚举校验错误。

## Remaining Gaps

- real probe 证明目标包可以派生 Top-30，但行业映射覆盖为 `0.0`，因此生产看板只能显示股票榜，方向聚集保持 `unverified`，不能宣称已形成行业方向结论。
- 最终镜像激活后首个自然盘后 Job 尚未到触发时间；下一次触发为 `2026-09-24 16:30 Asia/Shanghai`。在该 Job 完成前，OpenSpec 任务 `5.4` 保持未勾选，不把已有旧镜像/手工采集结果冒充为新 CronJob 的自然触发证据。

## Next Step

部署和激活已完成。下一步在 `2026-09-24 16:30 Asia/Shanghai` 后读取首个自然 Job 的 run/task 状态，确认 `activeDirection` 为 `fallback-derived` 或精确的 `failed-retained`/`failed-missing`；回滚仅关闭 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED`，不改变 breadth 开关。
