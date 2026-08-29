# 仓库状态

## 已实现

- harness 骨架：`docs/` 事实源体系、exec-plans 落地位、本地门禁（`.githooks/` + `scripts/check-docs-contract.py` + `scripts/install-hooks.py`）。
  - 事实源：`docs/repository-guide.md`、`docs/architecture.md`、`docs/runbooks.md`
- `搭建交易系统/` 已完成目录归档：11 个章节各自使用唯一章节目录，章节总览和正文不再散落于下载批次子目录。
- `docs/trading-system-directory.md` 已记录交易系统知识库的完整目录和文件清单，并由 `AGENTS.md` 提供入口说明。
- 市场环境分析看板：`src/market_environment/` + `apps/market-environment-dashboard/`。
  - 已接入 5 个指数、MA5/10/20/60、20/60 日区间位置、成交额比值、趋势/量价状态。
  - 已实现 mootdx → 百度 → 腾讯历史降级、腾讯实时交叉校验、30 秒缓存、非交易日回退和错误质量标记。
  - 已覆盖计算、服务层和 API 契约测试，并通过前端生产构建。
  - 已修复上证指数和中证500成交额缺失：新浪指数 K 线按腾讯实时成交额校准，量价状态不再误报“数据不足”。

## 进行中

- `docs/exec-plans/active/define-scope.md`：仓库范围定义计划仍在维护。

## 未实现

- 市场广度（上涨家数、下跌家数、涨跌幅中位数）尚未接入，作为后续独立迭代。
- `docs/product-specs/`（待范围定义后创建）
- CI（无 CI 平台文件；CI gate 见下方缺口）

## 当前风险

- 真实行情源受网络可用性影响；页面会显示降级来源、过期报价和部分失败 warning。
- `openspec/` — OpenSpec 规格（changes/ + specs/ + config.yaml）
- `.codex/`、`.opencode/` — agent 工具会话目录（是否入库待确认）
- 本机无 Python 时本地 gate 退化为警告放行（记录于 `docs/runbooks.md`）。
- `docs/exec-plans/active/define-scope.md` 仍为仓库范围计划，与市场环境切片并行保留。

## 下一步

- 完成 `docs/exec-plans/active/define-scope.md` 的 PRD 阶段。
- 继续维护 `搭建交易系统/` 各章节目录内的编号和文档映射。

## 最后更新

2026-08-29
