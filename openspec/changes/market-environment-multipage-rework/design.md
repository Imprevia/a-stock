## Context

看板的核心数据已经按交易日快照提供，但前端主要围绕单指数字段组织，跨指数和跨日证据无法直接复盘。实现必须保持旧响应字段、旧 URL/hash 和既有 provider/cache 边界不变。

## Decisions

### 市场级证据模型

在计算层从五项指数和市场广度快照生成七项证据：方向模式及涨跌数量、MA20 上方数量/有效数量、五指数 5 日成交额中位比值、放量上涨/下跌数量、全 A 上涨占比、全 A 涨跌幅中位数，以及风险提示/数据缺口。每个值保留 `status`、`reason` 和可选 warning，缺失使用 `数据不足`，不以 0 代替。

### 句式输出

新增结构化 `ReviewSentence`，包含有序 `segments` 和 `fullSentence`。每个 `ReviewSentenceSegment` 包含稳定 key、显示 label、value、质量状态和缺失原因。模板由市场级证据拼接，不再从第一个指数抽取 MA20、区间位置或量价状态；复制仅复制服务端返回的完整句，不保存编辑内容。

### 下一交易日解析

服务层先校验 `as_of`，从 `SnapshotStore.list_trading_sessions()` 选择严格大于当前日期的最小真实交易日，再读取该日期的核心指数和广度 materialized aggregate。缺少交易日、核心快照或聚合时分别返回 `pending`/`insufficient`，绝不触发 provider 或跨日期回退。返回当前/下一日期、七项原值、变化值和 warning。

### 前端分层

App 保留九个页面入口，但将页面内容拆成可读的章节组件/配置，避免在单一模板中继续堆叠所有分支。第 01 页按“事实元数据 → 五指数 → 图表 → 七项证据 → 句式 → 下一日 → 再学矩阵”排列；第 02–08 页按“事实 → 判断 → 质量边界”；第 09 页只呈现唯一环境结论、跨页证据锚点、风险否决/缺口和下一日影响摘要。

### 兼容与响应式

旧 `summarySentence`、`syncPattern`、`synchronizationAssessment`、指数/组合矩阵字段继续返回。新增字段为 additive。页面宽度 390px 时使用可换行卡片和图表容器，禁止页面级横向溢出；可见文字、图例、坐标轴和 tooltip 最小 14px。

## Risks and Mitigations

- 快照聚合缺失：以 `pending` 或 `insufficient` 展示并保留 warning，不伪造趋势。
- 旧消费者契约回归：保留字段并新增兼容测试。
- 前端重构引入 hash 回归：增加 01–09 独立访问和旧 hash 恢复测试。
- 移动端图表为空或溢出：在 Vitest/浏览器走查中覆盖 ECharts 生命周期和 390px 布局。
