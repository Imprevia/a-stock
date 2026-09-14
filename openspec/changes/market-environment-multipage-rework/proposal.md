## Why

现有市场环境看板虽然保留了指数与章节数据，但第 01 页的句式模板只引用单个指数，且缺少可验证的下一交易日后验对照，无法支持“先做再学”的盘后复盘。页面还混杂了未接入模块、复盘记录和训练进度，增加了误读风险。

## What Changes

- 保留 01–09 独立路由、hash、按需加载和第 01 页五项指数及两张 ECharts 图表。
- 为第 01 页增加市场级七项证据、结构化句式填充模板、完整句复制和精确下一交易日只读对照。
- 为第 09 页增加综合结论的下一交易日后验变化摘要，并复用同一 provider-free 接口。
- 将 02–08 页重排为“事实 → 判断 → 质量边界”，对 03、04、07 的缺失或未核实数据保留明确状态。
- 新增 `ReviewSentence`、`ReviewSentenceSegment`、`NextSessionComparison` schema 和 `/api/market-environment/next-session` GET 接口。
- 移除保存复盘记录、用户输入持久化和 20 日训练进度相关界面与状态；不新增 SQLite 表或写接口。
- 下一交易日仅从本地真实交易日、精确快照和 materialized aggregate 读取，不使用自然日回退、不联网补齐。

## Capabilities

### New Capabilities

- `review-sentence`: 基于市场级证据生成可审计句式槽位和完整句。
- `next-session-comparison`: 基于精确交易日快照提供 provider-free 的下一交易日对照。

### Modified Capabilities

- `index-combination-analysis`: 第 01 页新增市场级复盘证据与句式模板，组合矩阵移入“再学”区域并保留原字段。
- `index-synchronization-assessment`: 复盘证据和下一交易日变化需与既有同步判断保持兼容。

## Impact

- 后端：`calculations.py`、`schemas.py`、`service.py`、`api.py`、快照读取接口及相关测试。
- 前端：Vue 页面组件、类型、样式、路由/章节渲染和测试；保留 ECharts 生命周期与移动端行为。
- 文档：产品规格、设计规范、架构、runbook、status 和本 change 的设计/任务清单。
- 数据库：只读复用现有 `trading_sessions`、核心/广度快照和 materialized aggregate，不升级 schema。
