# 提升市场环境看板最小字号

## Stage（阶段）

前端可读性调整与响应式验证

## Status（状态）

`completed`

## Scope（范围）

调整 `apps/market-environment-dashboard/` 的全局与响应式样式，使全部页面中的可见文字字号不低于 `14px`，并同步修正导航、指标卡、表格、状态标签和移动端布局所需的尺寸与间距。

## Acceptance（验收）

- 全部显式 `font-size` 规则均不低于 `14px`，屏幕阅读器专用隐藏文本不受影响。
- 01 至 09 页面沿用现有信息层级，标题与关键数字仍明显大于辅助文字。
- 桌面与移动视口没有页面级横向溢出、文字重叠或控件截断。
- 前端生产构建通过，浏览器验证覆盖桌面和移动视口。
- `docs/architecture.md`、`docs/runbooks.md` 与本计划同步更新，docs-contract 完整门禁通过。

## Completion Evidence（完成证据）

- CSS 与 ECharts 显式字号已统一到最小 `14px`；静态扫描未发现低于 `14px` 的 `font-size` / `fontSize`。
- 导航行、证据条、指标行、状态标签和信号卡同步增加高度或内边距，避免放大后挤压。
- 成交额图高度提升到 `120px`，纵轴减少为 3 个分段并启用标签重叠隐藏。
- 前端生产构建：`npm run build` → Vite build 成功；保留现有大 chunk warning。
- 浏览器验证：01 至 09 页面在 `1440x900` 与 `390x844` 视口下最小计算字号均为 `14px`，页面级横向溢出均为 0；移动端图表、卡片、抽屉和宽表通过视觉检查。
- 浏览器控制台错误检查为空。
- Docs contract：计划仍处于 active 时运行 `.venv\\Scripts\\python.exe scripts/check-docs-contract.py --mode=full` → 通过。
- 计划归档后复核：`SKIP_PLAN_GATE=1 .venv\\Scripts\\python.exe scripts/check-docs-contract.py --mode=full` → 通过；仅因已完成计划按约定移出 `active/` 而跳过 plan 检查。

## Remaining Gaps（剩余缺口）

- 前端当前没有 Vitest 测试文件，`npm run test` 会以“未找到测试文件”退出；本次以生产构建、静态字号扫描和浏览器 QA 覆盖。
- Vite 仍提示主 JS chunk 超过 500 kB，与本次字号调整无关。

## Next Step（下一步）

后续新增页面或图表时继续遵循可见文字最小 `14px` 的基线，并补充前端视觉或组件测试。
