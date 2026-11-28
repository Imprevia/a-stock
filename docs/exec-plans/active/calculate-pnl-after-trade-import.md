# 截图入账后计算盘后盈亏

## Stage

本地验收与规格归档（2026-11-28）。对应 [OpenSpec 归档任务](../../../openspec/changes/archive/2026-11-28-calculate-pnl-after-trade-import/tasks.md)。

## Status

本地完成，11/11 项。2026-11-28 用户确认自动取得可核验的 Fuyao 证据，未知公司行动保留缺项，通过本地证据导入补齐后重算。

## Acceptance

- 截图入账与盘后计算独立提交，范围由新增成交和最近已结算交易日确定，可恢复和重试。
- 自动复用并补齐可验证的交易日历、不复权收盘和公司行动证据。流水缺口沿持仓传播，月历与明细使用一致的正式、估算及缺项状态。
- 在隔离 PostgreSQL 与固定上游响应下验证新旧流程，并完成前端测试、构建、桌面和移动布局检查以及文档门禁。

## Completion Evidence

- 已读取 OpenSpec 提案、设计、规格和任务，确认实施状态为 `ready`。
- 已索引本计划并同步产品规格、架构、仓库指南和运行手册。`python3 scripts/check-docs-contract.py --mode=full` 和 `openspec validate calculate-pnl-after-trade-import --strict` 通过。
- Fuyao 单股 REST 契约明确 `thscode`、上海零点除权除息日、税前每股现金分红及每股送股比例。官方响应结构未提供股权登记日、配股字段或可用于断言指定证券和日期数据完整的覆盖证明。[单股除复权契约](https://fuyao.aicubes.cn/docs/api-reference/corporate-actions/)
- 全市场转储增加配股价格和比例，公开契约仍未说明如何核验指定证券至指定日期的完整发布覆盖，既有隔离探测也未取得所需的 SHA-256。[转储契约](https://fuyao.aicubes.cn/docs/api-reference/market-dumps/) [既有探测记录](add-fuyao-ths-sector-datasets.md)
- Tushare 分红送股提供登记日、除权日、派息日及红股上市日，文档给出单次 2,000 行限制。该接口的公开契约未证明覆盖所有公司行动或空响应的完整性。[分红送股接口](https://tushare.pro/document/2?doc_id=103)
- Fuyao 的 MCP 对应同一个 REST 端点，公开的返回结构也只有 `thscode`、`ticker` 和事件列表。日期筛选参数只能界定所请求的窗口。[MCP 工具契约](https://fuyao.aicubes.cn/docs/mcp/tools/get_a_share_corporate_actions_adjustment_factors/)

- 现有转储读取器校验文件 SHA-256、列结构、行日期在清单区间内及 `(证券, 日期)` 唯一性。清单只有全文件起止日，无法据此得出某只证券在某日确实无事件。[转储读取器](../../../src/market_environment/infrastructure/providers/fuyao/ths_dump.py) 的[现有固定样本测试](../../../tests/test_market_environment_fuyao_ths_dump.py) 全部通过（10 项），覆盖事件字段、校验和、缺列和重复键。
- 台账本地导入可保存逐证券逐日的公司行动确认及来源，行情证据与公司行动证据独立合并。该入口可复用已有人工核验证据，其输入仍需来自具备相应事实的来源。[台账证据结构](../../../src/market_environment/domain/models/trading_pnl.py) [台账证据合并](../../../src/market_environment/infrastructure/persistence/postgres/trading_pnl.py)

任务 1.2 的固定响应场景（8 个测试已通过）：

| 场景 | 样例 | 预期判定 |
| --- | --- | --- |
| 有效原始事件 | REST 文档中的 2015-07-17 样例，税前每股 4.374 元，每股送股 0.1 | 按正确证券、日期、单位和来源保存原始事件。 |
| 覆盖未知 | 以 REST 文档的响应结构构造 `code: 0`，指定证券相符，`item: []` | 公司行动待核验。 |
| 响应不完整 | 同一结构缺 `item`，或者返回证券与目标冲突 | 该响应不可用于写入证据，已有合格证据继续可用。 |
| 权利无法核验 | REST 文档中的 2025-12-19 分红样例，税前每股 23.957 元，缺股权登记日 | 保留公开事件事实，权益金额待核验。 |

- 隔离 PostgreSQL 16.4 通过新增迁移与旧数据兼容性验证。隔离 HTTP 流程用合成 PNG、Tesseract 中文 OCR 与固定上游响应验证入账、计算、月历和日期明细。覆盖跨月日期选择、周末、尚未结算、全部跳过、并发复用、版本冲突重试、公司行动缺项、历史卖清及本地证据重算。
- 前端 Vitest 25 个文件共 181 项通过，Vite 生产构建通过，保留主包体积提示。Chromium 使用合成 API 验证 390px 与 1440px 的导入结果、月历、估算明细和缺项明细，最小可见字号为 14px，页面无横向溢出。
- `check_market_environment_architecture.py` 通过，Alembic 单一 head 为 `0010_pnl_calculation`。OpenSpec 严格校验、`docs-contract full` 与 `git diff --check` 通过。

- 使用隔离 PostgreSQL 16.4 和中文 Tesseract 的台账、估算及架构定向 pytest 共 43 项通过，零跳过。

## Remaining Gaps

- Fuyao 当前缺完整覆盖声明和登记字段。覆盖未知及权益待核验按修订规格标记，经本地证据补齐后重算。
- 验收使用固定上游响应。实时 Fuyao、全量后端测试及生产部署未运行。

## Next Step

本地实现和验收完成。增量已同步至[盈亏日历主规格](../../../openspec/specs/trading-pnl-calendar/spec.md)，OpenSpec 变更已归档。
