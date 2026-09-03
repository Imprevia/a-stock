# 稳定行业板块数据采集

## Stage（阶段）

修复数据采集页日期初始化、东方财富请求稳定性和行业字段契约。

## Status（状态）

`completed` · OpenSpec change `stabilize-sector-data-collection` 的 13 项实施任务和全部验收已完成。

## Goal（目标）

确保行业板块在上海市场当天可直接采集，东方财富主域瞬态失败时能够串行重试并降级到兼容端点，同时保持精确日期隔离、失败保留和可审计质量状态。

## Scope（范围）

- 数据采集页首次状态请求由后端返回上海市场日期，研究页继续使用 15:00 结算截止默认值。
- 进程内东方财富请求全局串行，瞬态连接/读取错误、429 和 5xx 有界重试，403 不重试。
- 行业排名从 `push2` 主域降级到 `push2delay`，并保留来源和主域失败 warning。
- 行业领涨股使用真实名称字段 `f128`，缺失时保持 `null`。
- 同步产品规格、架构、runbook、状态、测试和 OpenSpec 证据。

不包含历史行业榜回补、行业层级筛选、独立供应商备胎、分布式限流或 SQLite schema 变更。

## Work Phases（工作阶段）

- [x] OpenSpec proposal、design、spec 和 tasks 完成并通过 strict validation。
- [x] active plan 创建并加入索引。
- [x] 产品规格、架构和 runbook 更新。
- [x] 东方财富串行请求边界、有限重试及测试完成。
- [x] 行业主域降级、字段修正及测试完成。
- [x] 采集页服务端日期初始化及前端测试完成。
- [x] 全量验证、真实数据 smoke test 和文档门禁完成。

## Acceptance（验收）

- 15:00 前首次打开 `/data-collection` 时默认选择后端上海市场当天，latest-only 数据集不因研究页默认日期而禁用。
- 两个后台 worker 不能并发发起东方财富 HTTP 请求，并遵守最小间隔与抖动。
- 瞬态连接/读取失败、429 和 5xx 在有界次数内恢复；403 立即失败且不盲目重试。
- 行业主域失败而延迟域成功时保存有效快照，并标记 fallback source 与 warning。
- 两个行业端点都失败时继续使用 `failed-retained` / `failed-missing`，不得跨日期回填。
- 行业 `leader` 返回 `f128` 名称，不把 `f140` 证券代码显示为名称。
- focused/full pytest、前端测试/build、真实数据 smoke、OpenSpec strict 和 docs-contract full 全部通过。

## Completion Evidence（完成证据）

- 聚焦后端测试：`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_providers.py tests/test_market_environment_collection.py tests/test_trading_rule_platform.py -q`，45 passed。
- 全量 Python 测试：`.venv\\Scripts\\python.exe -m pytest -q`，107 passed，1 个 Starlette TestClient 依赖弃用 warning。
- 前端测试：`npm test`，2 files / 11 tests passed。
- 前端生产构建：`npm run build` 成功；Vite 报告既有的大 chunk 非阻塞警告。
- 当前上海市场日行业真实数据 smoke：`snapshots refresh --as-of 2026-09-03 --dataset sectors --force` 成功；主域断连后降级到 `eastmoney-clist-delay`，100 条记录，批次 `success`，耗时 3543.66 ms。
- OpenSpec：`openspec validate stabilize-sector-data-collection --strict` 通过。
- 文档门禁：`.venv\\Scripts\\python.exe scripts/check-docs-contract.py --mode=full` 通过（代码 15 / 文档 6 / plan 1）。
- Diff 检查：`git diff --check` 通过，仅报告 Windows 行尾转换提示。

## Remaining Gaps（剩余缺口）

- `push2` 与 `push2delay` 属于同一供应商，独立供应商备胎不在本次范围。
- 东方财富当前返回多层级行业板块；层级筛选需另行定义产品口径。

## Next Step（下一步）

使用 `$openspec-archive-change stabilize-sector-data-collection` 归档已完成的 OpenSpec change。
