# 开发市场环境分析看板

## Stage（阶段）

业务网页实现与验证

## Status（状态）

`completed`

## Scope（范围）

基于 `搭建交易系统/01-如何判断市场环境/01.指数、趋势位置和成交额.md`，实现真实行情的指数分析看板；包括 5 个指数、均线、20/60 日区间位置、成交额比值、量价/趋势状态和手动日期刷新。市场广度指标留待后续迭代。

## Acceptance（验收）

- 后端提供 `/api/market-environment?as_of=YYYY-MM-DD`，返回固定 JSON 契约。
- 通达信为历史 K 线主源，腾讯行情/HTTP K 线为降级源，并暴露数据源与警告状态。
- 前端展示 5 个指数卡片、指标表格、历史折线图和综合结论，具备加载、空数据、部分失败和全失败状态。
- 公式、非交易日回退、日期校验、缓存和过期报价处理有自动化测试。
- 桌面和移动布局通过浏览器检查，无明显溢出或空白图表。
- `docs/architecture.md`、`docs/runbooks.md`、`docs/repository-guide.md`、`docs/status.md` 与新增目录同步。
- `python scripts/check-docs-contract.py --mode=full` 通过。

## Completion Evidence（完成证据）

- 后端实现：`src/market_environment/` 提供固定响应契约、5 个指数、均线/区间/成交额计算、30 秒缓存、非交易日回退、源降级和数据质量警告。
- 前端实现：`apps/market-environment-dashboard/` 已完成卡片、表格、MA5/10/20/60 价格图、60 日成交额图、结论和错误状态。
- 自动化测试：`.venv\\Scripts\\python -m pytest tests -q` → `12 passed`。
- 前端构建：`npm run build --prefix apps/market-environment-dashboard` → Vite build 成功。
- 浏览器验证：Midscene 桌面截图确认五张指数卡、完整均线图、成交额图、指标表和结论区可见且无明显重叠；Playwright `390x844` 全页截图确认移动端纵向卡片、横向表格和图表无重叠；截图记录于 `midscene_run/report/` 和本地验证产物（已忽略）。
- 文档契约：`python scripts/check-docs-contract.py --mode=full` 已执行。

## Remaining Gaps（剩余缺口）

- 市场广度（上涨/下跌家数及涨跌幅中位数）不在本次范围内。
- 真实数据源可用性依赖本机网络；降级和错误状态必须可见。

## Next Step（下一步）

后续迭代接入市场广度数据，并为独立市场广度模块创建新的 active plan。
