# 指数卡复制与默认交易日归一

## Stage

Implementation

## Status

completed

## Acceptance

- 第 01 页五张指数卡的指数数值和涨跌幅可分别复制，且不改变指数选择。
- 剪贴板成功、不可用和权限拒绝均有明确可访问反馈，不误报成功。
- 研究页保留 15:00 默认规则；首次请求遇到非交易日时，顶部日期同步为后端实际交易日，手动选择不被覆盖。
- 前端测试、生产构建、文档契约门禁和 `git diff --check` 通过。

## Completion Evidence

- `npm test --prefix apps/market-environment-dashboard`：7 个测试文件、38 项通过，覆盖独立复制、剪贴板失败和初始/手动日期行为。
- `npm run build --prefix apps/market-environment-dashboard`：Vite 生产构建通过（保留既有 chunk 大小提示）。
- 固定 API 路由的 Chromium 390px 检查：渲染 5 张指数卡、5 个指数值复制控件和 5 个涨跌幅复制控件，`scrollWidth=390` 与视口一致，无页面级横向溢出。
- `python3 scripts/check-docs-contract.py --mode=full`：通过（代码 7 / 文档 5 / plan 1）。`python` 命令在环境中不存在，已使用等价 `python3`。
- `git diff --check`：通过。

## Remaining Gaps

- 未在真实生产 NodePort 环境执行剪贴板权限验证；实现保留 API 失败时的受控 fallback/失败提示。

## Next Step

- 进入代码审查；确认无误后归档本计划并按 OpenSpec 流程归档变更。
