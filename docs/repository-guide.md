# 仓库指南（repository guide）

## 仓库目的

a-stock：A 股分析与研究工作区。业务范围尚未定义（见 `docs/exec-plans/active/define-scope.md`），当前仓库处于 harness 骨架阶段。

## 顶层目录地图

| 路径 | 用途 | 修改策略 |
|------|------|----------|
| `AGENTS.md` | agent 顶层路由与硬规则 | 改规则须同步 `scripts/check-docs-contract.py` 错误消息 |
| `README.md` | 产品面一页概述 | 低频更新 |
| `docs/` | 事实源（规格 / 架构 / runbook / plan / status） | 高频更新，见下方映射表 |
| `docs/exec-plans/active/` | 活动执行计划（多步工作入口） | 每次多步任务先改这里 |
| `docs/exec-plans/completed/` | 已归档计划 | 只读，完成时移入 |
| `scripts/` | 本地门禁与工具脚本 | 改动须同步 `docs/runbooks.md` |
| `.githooks/` | git hook 薄入口 | 只做转发，规则不写在这里 |
| `.codegraph/` | 代码索引缓存（已 gitignore） | 不手工编辑 |
| `搭建交易系统/` | 交易系统知识库；按 `01`—`11` 章节目录归档，章节总览使用 `0-主题.md`，正文直接位于对应目录 | 维护章节目录内的 Markdown；新增章节时同步更新本表 |
| `src/market_environment/` | 市场环境分析 API、行情适配、指标计算和响应模型 | 修改数据源、计算公式或 API 契约时同步 `docs/architecture.md` 与 `docs/runbooks.md` |
| `apps/market-environment-dashboard/` | Vue 3 + Vite + ECharts 单页分析看板 | 修改页面结构、接口字段或运行命令时同步 `docs/runbooks.md`；构建验证必需 |
| `openspec/` | OpenSpec 规格目录（并发产生，归属待确认） | 勿移动/覆盖；与 docs/exec-plans 的关系待定 |
| `.codex/`、`.opencode/` | agent 工具会话目录 | 是否入库待确认 |

## 主要行为在哪

- 文档契约检查：`scripts/check-docs-contract.py`
- hook 安装：`scripts/install-hooks.py`
- 业务代码：`src/market_environment/` 与 `apps/market-environment-dashboard/`；边界、数据流和降级策略见 `docs/architecture.md`。
- 交易系统知识库：`搭建交易系统/01-如何判断市场环境/` 至 `搭建交易系统/11-量化交易环境下的应对/`；每章目录包含 `0-主题.md` 总览和按 `01.`、`02.` 编号的正文。
- 交易系统目录索引：`docs/trading-system-directory.md`；目录结构变化时与 `AGENTS.md` 一并更新。

## 安全修改区

- `docs/**`：自由修改，保持链接有效。
- `scripts/**`、`.githooks/**`：改动后必须跑 `python scripts/check-docs-contract.py --mode=full` 验证。

## 不安全修改区（改前必须有 active plan）

- `AGENTS.md` 的硬规则块
- `scripts/check-docs-contract.py` 的 gate 逻辑
- `.githooks/*` 的转发目标

## 代码-文档映射

业务代码落地后按下表扩展（映射非空时由 gate 强制执行）：

| 代码区 | 必需文档更新 | 门禁级别 |
|--------|-------------|----------|
| `src/**`（未来） | `docs/architecture.md` | fail |
| `apps/**` | `docs/architecture.md`, `docs/runbooks.md` | fail |
| `docs/product-specs/**` 引用的代码路径 | 对应 spec | fail |
| `scripts/**` | `docs/runbooks.md` | warn |
| `requirements.txt` / `pyproject.toml` | `docs/runbooks.md`, `README.md` | fail |

## 文档映射规则

- 新增顶层目录 → 更新本文件目录地图
- 新增 gate / 检查 → 更新 `AGENTS.md` 硬规则 + `docs/runbooks.md`
- 教训类内容 → `docs/lessons-learned.md`（发生 → 为何重要 → 仓库改了什么）
