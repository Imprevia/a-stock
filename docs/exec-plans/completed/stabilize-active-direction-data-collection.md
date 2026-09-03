# 稳定容量方向数据采集

## Stage（阶段）

补齐容量方向成交额 Top-N 的主域降级、质量元数据和失败保留验证。

## Status（状态）

`completed` · OpenSpec change `stabilize-active-direction-data-collection` 的 17 项实施任务和全部验收已完成。

## Goal（目标）

确保 `activeDirection` 在东方财富 `push2` 主域经过有界恢复后仍不可用时，能够降级到同口径 `push2delay` 获取经验证的成交额 Top-N 数据，并准确保存 fallback 来源、主域错误和精确日期快照状态。

## Scope（范围）

- 容量方向先请求 `push2`，主域失败后请求 `push2delay`。
- 两个端点统一校验代码、名称、成交额、至少 30 个有效样本和成交额非递增排序。
- 主域成功保持 `eastmoney-clist` / `partial`；延迟域成功标记 `eastmoney-clist-delay` / `fallback` 并保留 warning。
- 两端点失败时继续使用现有 `failed-retained` / `failed-missing`、精确日期隔离和 null 语义。
- 同步产品规格、架构、runbook、状态、OpenSpec tasks、测试和完成证据。

不包含独立供应商备胎、历史容量方向回补、Top-30/Top-10 算法调整、SQLite schema 变更、前端改动或东方财富 limiter/retry 策略调整。

## Work Phases（工作阶段）

- [x] OpenSpec proposal、design、spec 和 tasks 已创建并通过 strict validation。
- [x] active plan 创建并加入索引。
- [x] 产品规格、架构、runbook 和状态文档更新。
- [x] 容量方向主域到延迟域降级与质量元数据实现。
- [x] provider、collection 和 snapshot 精确日期测试完成。
- [x] 聚焦/全量测试、真实数据 smoke、OpenSpec 和 docs-contract 门禁完成。

## Acceptance（验收）

- 主域返回有效 Top-N 时不调用延迟域，来源保持 `eastmoney-clist`。
- 主域有界恢复失败而延迟域有效时保存 30 个观察样本，来源为 `eastmoney-clist-delay`、状态为 `fallback`，warning 包含主域失败原因。
- 主域和延迟域均使用相同的必需字段、最小样本和排序校验；无效延迟载荷不得保存。
- 两个端点都失败时，同日期已有成功值记录 `failed-retained`，无同日期值记录 `failed-missing`，不得跨日期替代。
- Top-30 行业聚集、Top-10 展示、当前市场日限制和公开 API 字段保持兼容。
- focused/full pytest、真实市场日 smoke、OpenSpec strict、docs-contract full 和 whitespace 检查通过。

## Completion Evidence（完成证据）

- Provider 测试覆盖主域成功不请求延迟域、主域失败后接受 keyed 延迟响应、必需字段/最小样本/排序校验和双端点错误组合；collection 测试覆盖同日期 `failed-retained` 与跨日期隔离。
- 聚焦测试：`.venv\\Scripts\\python.exe -m pytest tests/test_market_environment_providers.py tests/test_market_environment_collection.py tests/test_market_environment_service.py tests/test_market_environment_snapshot_store.py -q`，67 passed。
- 全量 Python 测试：`.venv\\Scripts\\python.exe -m pytest -q`，124 passed、3 skipped；仅有既存 Starlette TestClient/httpx 弃用 warning。
- 当前上海市场日真实数据 smoke：`snapshots refresh --as-of 2026-09-03 --dataset activeDirection --force` 成功；`push2` 主域 `RemoteDisconnected` 后降级到 `eastmoney-clist-delay`，保存 30 个观察样本，快照质量为 `fallback`，warning 保留主域错误和降级说明。
- OpenSpec：`openspec validate stabilize-active-direction-data-collection --strict` 通过。
- 文档门禁：`.venv\\Scripts\\python.exe scripts/check-docs-contract.py --mode=full` 通过（代码 15 / 文档 7 / plan 1）。
- Diff 检查：`git diff --check` 通过，仅报告 Windows 行尾转换提示。

## Remaining Gaps（剩余缺口）

- `push2` 与 `push2delay` 同属东方财富，供应商整体不可用时仍会失败；独立供应商备胎另行设计。
- 延迟域盘中数据可能落后于主域，当前已通过 `fallback` 来源和 warning 显式表达。

## Next Step（下一步）

使用 `$openspec-archive-change stabilize-active-direction-data-collection` 归档已完成的 OpenSpec change。
