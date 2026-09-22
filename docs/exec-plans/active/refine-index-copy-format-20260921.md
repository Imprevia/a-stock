# 优化指数涨跌幅复制格式

## Stage（阶段）

前端交互、文档契约与离线回归验证。

## Status（状态）

`completed`

## Acceptance（验收）

- 第 01 页指数卡继续以带百分号的格式显示涨跌幅，例如 `+0.62%`。
- 点击指数卡涨跌幅复制按钮时，剪贴板内容去掉百分号但保留正负号和两位小数，例如 `+0.62`。
- 指数收盘值复制、卡片选中状态、复制成功/失败反馈和键盘操作保持现有行为。
- 前端测试、生产构建和 docs contract 通过。

## Completion Evidence（完成证据）

- `npm test --prefix apps/market-environment-dashboard`：20 个测试文件、121 项通过；`index card copy controls` 两个用例覆盖新的 `formatCopyPct` 行为。
- `npm run build --prefix apps/market-environment-dashboard`：Vite 生产构建通过（`dist/index.html` 0.47 kB / `index-Czrpq3e1.css` 50.67 kB / `index-CapelSLz.js` 1,280.01 kB）。
- `python3 scripts/check-docs-contract.py --mode=fast`：通过（代码 0 / 文档 0 / plan 0）。
- `python3 scripts/check-docs-contract.py --mode=full`：通过（代码 31 / 文档 10 / plan 2）。

## Remaining Gaps（剩余缺口）

- 未在真实浏览器剪贴板权限下做手工验证；现有断言覆盖 `navigator.clipboard.writeText` 调用与页面可见文本。

## Next Step（下一步）

- 后续归档本计划到 `docs/exec-plans/completed/` 并在桌面 + 390px 浏览器 QA 中人工确认复制交互。
