# 整理市场环境看板设计规范

## Stage（阶段）

现有页面设计语言提炼与文档化

## Status（状态）

`completed`

## Scope（范围）

基于市场环境看板已完成的 01 至 09 页面，整理一份后续页面开发可直接复用的设计规范，覆盖设计原则、页面骨架、字体、颜色、间距、组件、图表、响应式、数据状态、内容写法和验收清单。

## Acceptance（验收）

- 规范中的尺寸、颜色、断点和组件行为与当前 `App.vue`、`styles.css` 一致。
- 明确可复用模式与禁止事项，能够指导新页面设计、实现和评审。
- 覆盖桌面、平板、移动端及数据完整、降级、缺失、失败、加载状态。
- 在市场环境看板产品规格、架构和仓库指南中提供稳定入口。
- docs-contract 完整门禁通过。

## Completion Evidence（完成证据）

- 新增 `docs/product-specs/market-environment-dashboard-design-guidelines.md` 版本 `1.0`，包含 13 个主题章节。
- 规范覆盖设计原则、页面骨架、字体、语义色、图表色、间距、导航、基础组件、数据状态、内容、响应式和禁止事项。
- 01 至 09 页面均有独立组合模板，能够指导同类新页面选择现有组件结构。
- 新页面交付清单包含 18 项设计、实现和验证检查。
- 主产品规格、架构、仓库指南和 runbook 均已增加设计规范入口。
- `.venv\\Scripts\\python.exe scripts/check-docs-contract.py --mode=full` → 通过。
- `git diff --check` → 通过，仅有本机既有 CRLF 转换提示。

## Remaining Gaps（剩余缺口）

- 当前设计 token 仍以规范和现有 CSS 数值为事实源，尚未抽取为 CSS variables 或独立组件库；该工程化改造不在本次文档任务范围内。
- 当前没有独立 Figma 文件或自动化视觉回归基线，页面仍按仓库浏览器 QA 流程验证。

## Next Step（下一步）

后续开发新页面时从本规范选择组合模板，并在需要抽取共享组件或设计 token 时创建独立 active plan。
