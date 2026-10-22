# 重构大成交额主动进攻方向研究工作台

## Stage

实施阶段：先完成文档契约，再实现 Top-30 兼容、provider-free 工作台读模型、V2 资源和 `/dashboard/06` 五视图页面。

## Status

evidence-module-repair-complete-with-explicit-source-gaps（34/34）

## Acceptance

- `/dashboard/06` 保留原路由和导航标题，呈现方向总览、Top-30 资金地图、核心辨识、候选模式、基本面与次日验证五个视图。
- active-direction 保留旧 Top-10 `topStocks`，新增有界且可追溯的 `researchRows`；旧快照仍可读。
- 工作台读取严格 provider-free、精确日期、revision-pinned，不采集、不回填、不跨日期替代、不写入数据库。
- QTS-04 规则继续为 `documented-only` / `needs-backtest`，不生成自动角色或买卖建议；缺失数据显式为 `missing` / `insufficient`。
- 桌面及 390px 视口无页面级横向溢出，所有可见文字、控件、图例、坐标和 tooltip 至少 14px。

## Completion Evidence

- active-direction primary/delayed/TDX 派生路径保留验证过的 Top-30 `researchRows`，旧 `topStocks` 保持前 10 行兼容；`PYTHONPATH=. uv run pytest tests/test_market_environment_active_direction_acquisition.py tests/test_market_environment_v2_resources.py -q`：23 passed。
- 新增 typed workbench composer、aggregate `activeDirectionWorkbench`、PostgreSQL/compatibility provider-free read、`/api/v2/market-environment/{as_of}/active-direction/workbench`、ETag/revision 复用和旧快照 missing envelope。
- 前端五视图、Pinia workbench resource、旧 Top-10 fallback、键盘可操作选择和 390px scoped 样式已落地；`npm run test`：24 files / 172 passed；`npm run build`：通过（仅已有 chunk size warning）。
- 证据模块修复：active-direction 同日快照保留 PE/PB、市值、换手率和阶段涨跌幅；workbench fundamentals 从 `missing` 改为有事实时 `partial`，并逐项列出利润/成长/现金流/杠杆缺口。limits 的 promoted/security details 已投影到一进二锚点和盘中封板观察，集合竞价单独显示 `pending`，不再与盘中事实混淆。
- 证据修复测试：`PYTHONPATH=. uv run pytest tests/test_active_direction_workbench_evidence.py tests/test_market_environment_active_direction_acquisition.py -q`：15 passed；`npm exec vitest run --run src/pages/dashboard/Document06ActiveDirectionPage.test.ts --pool=forks --maxWorkers=1 --minWorkers=1`：2 passed；Vite build 通过。
- 规则门禁：`PYTHONPATH=. uv run python -m src.trading_system.cli rules validate`（49 rules）、`rules coverage`（documented 330 / executable 49）、`docs sync-check` 均通过；`openspec validate refactor-active-direction-research-workbench --strict` 通过。
- 全量 pytest 最终为 1574 passed / 20 skipped；一次 timing-sensitive cache 性能断言在并发运行环境下失败，单独重跑该测试通过。`python3 scripts/check-docs-contract.py --mode=full` 通过（代码 37 / 文档 8 / plan 2）。

## Remaining Gaps

- 尚未在真实浏览器中完成桌面与 390px 的截图/overflow 检查；组件已提供 14px 最小字号、内部宽表滚动和移动 tab/evidence stacking，需在发布前补充浏览器证据。
- 竞价没有已批准的本地事实表，财务利润/成长/现金流/杠杆也没有已批准的财务报表事实；本轮不伪造这些数据，而是接入已有估值快照和涨停盘中事实，并把剩余缺口细分到字段级。
- k3s 生产部署尚未执行：目标集群只读预检已确认 `ix-truenas` / Kubernetes `v1.26.6`、`a-stock` release revision 146、无 CronJob/Job；受控发布脚本随后因当前工作树有未提交修改而拒绝 `all/service` 发布。脚本要求 clean reviewed commit，不能用参数绕过，也未擅自提交或暂存用户改动。

## Next Step

补做一次授权的桌面/390px 浏览器可读性检查，并在取得 clean reviewed checkout 后重新运行 k3s 发布；若无新增问题，再使用 `openspec-archive-change` 归档。本变更仍不包含真实 provider smoke 或历史回填。
