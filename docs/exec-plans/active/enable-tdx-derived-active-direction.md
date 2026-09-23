# 启用 TDX 派生容量方向

## Stage

实现、离线验证与受控发布准备

## Status

offline-complete-awaiting-production-authorization

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

## Remaining Gaps

- 未执行生产 Deployment/CronJob 写操作；新开关保持默认关闭，不能把本地实现当作生产部署成功。
- real probe 证明目标包可以派生 Top-30，但行业映射覆盖为 `0.0`，因此生产看板只能显示股票榜，方向聚集保持 `unverified`，不能宣称已形成行业方向结论。

## Next Step

所有离线门禁和 real probe 已完成。下一步只有在取得单独生产写授权后，才通过受控 deployment/schedule 入口将新开关独立设为 `1` 并观察一个盘后 Job；回滚仅关闭 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED`，不改变 breadth 开关。
