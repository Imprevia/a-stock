## Why

第 01 页的五张指数卡目前整卡点击只用于切换图表，研究者无法快速复制卡片中的指数数值或涨跌幅，抄录盘后结论时需要手工选取文本。顶部日期按 15:00 截止规则计算的是日历日，周末或节假日可能先选中非交易日，虽然后端会回退到有效行情日，日期控件却没有同步反映实际交易日。

## What Changes

- 为五张指数卡增加两个相互独立的复制目标：指数数值（收盘值）与右侧涨跌幅；复制精确的可见格式，不复制指数名称。
- 保留卡片其余区域的指数选择和图表联动行为；复制操作不得改变当前选中指数。
- 增加复制成功、剪贴板不可用和权限拒绝时的可访问反馈，并为非安全 HTTP 运行环境提供可审计的降级处理。
- 保留研究看板既有的 15:00 前后日期计算规则；首次自动加载时，若请求日期不是交易日，则将顶部日期归一为后端返回的实际交易日。用户手动选择日期后不强制改写其选择。
- 补充前端组件测试、桌面/390px 浏览器验收和相关产品规格、架构及运行手册说明。

## Capabilities

### New Capabilities

<!-- No standalone capability is needed; the interaction extends Section 01. -->

### Modified Capabilities

- `index-combination-analysis`: 增加五指数卡的指数数值/涨跌幅独立复制契约，并明确研究页首次默认日期必须落在后端确认的实际交易日。

## Impact

- 前端：`apps/market-environment-dashboard/src/App.vue`、`styles.css`、`app.test.ts` 及日期工具测试；可能新增轻量复制状态/降级辅助逻辑。
- 文档：`docs/product-specs/market-environment-dashboard.md`、`docs/product-specs/market-environment-dashboard-design-guidelines.md`、`docs/architecture.md`、`docs/runbooks.md`。
- API：不新增端点或字段；复用核心响应的 `asOf`（实际交易日）与现有 `requestedAsOf`/质量回退语义。
- 依赖：优先使用浏览器 Clipboard API；HTTP 或权限受限时按设计的 fallback/失败提示执行，不引入第三方依赖。
