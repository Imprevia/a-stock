# AGENTS.md — a-stock 仓库规则

本仓库是 agent-first 工程系统：`docs/` 是事实源，plan / status / evidence 有固定落地位，本地 gate 强制执行。

## 按任务类型路由

| 任务类型 | 先读 | 再做 |
|----------|------|------|
| 任何多步 / 跨目录实现 | `docs/exec-plans/active/_index.md` → 对应 plan | 无 plan 则先创建 plan |
| 新功能 / 产品范围 | `docs/product-specs/`（或 PRD） | 先写规格再实现 |
| 架构 / 边界 / 数据流 | `docs/architecture.md` | 先更新架构再动代码 |
| 部署 / 环境 / 验证 | `docs/runbooks.md` | 同步 runbook |
| 找代码在哪 / 安全边界 | `docs/repository-guide.md` | 按映射表更新文档 |
| 接手未完成任务 | `docs/status.md` → active plan 的 `Next Step` | 从记录的下一步继续 |

### 交易系统知识库目录

`搭建交易系统/` 的完整目录和文件清单以 [`docs/trading-system-directory.md`](docs/trading-system-directory.md) 为准；一对一量化重写版 `搭建交易系统-量化版/` 以 [`docs/trading-system-quantified-directory.md`](docs/trading-system-quantified-directory.md) 为准。两个目录都保留 `00-搭建交易系统.md` 总入口，并按 `01`—`11` 章节归档；每章总览命名为 `0-主题.md`，正文使用 `01.`、`02.` 等两位数字编号。

原版负责观点来源，量化版负责数据口径、公式、阈值、评分、否决和校准状态。整理、新增、删除或重命名交易系统文档时，先更新对应目录索引并保持两个目录相对路径一致；禁止重新建立按飞书下载批次拆分的同主题子目录，也不要把章节正文散落到两个知识库根目录。量化版已有规则 ID 不得因文字调整而重排。

`搭建交易系统-量化版/` 是人读说明层；`trading-rules/` 是机器执行事实源。规则变更必须同步 YAML、量化文档、覆盖清单、测试和证据引用。PR 规则验证只能使用固定快照离线运行；真实数据获取只允许在盘后或显式本地命令中执行，数据源失败必须输出 `degraded` 或 `insufficient`。

## 硬规则（gate 强制，非建议）

1. `docs/` 是事实源。代码与文档冲突：先修文档，再继续实现。
2. 代码改动前必须更新或创建 `docs/exec-plans/active/*.md`（多步工作必须以 plan 起手）。
3. 跨目录 / 多模块实现禁止无 active plan 启动。
4. 代码改动必须同步更新对应文档（见 `docs/repository-guide.md` 的代码-文档映射表）。
5. 架构边界变更必须更新 `docs/architecture.md`。
6. 产品范围 / 角色 / 流程变更必须更新 `docs/product-specs/*.md`（该目录存在或应当存在时）。
7. 运维 / 环境 / 验证路径变更必须更新 `docs/runbooks.md`。
8. 阶段未完成直到 plan 的 `Status` / `Completion Evidence` / `Remaining Gaps` 更新。
9. 本地 docs-contract gate 未过或未显式记录阻塞 → 任务未完成。

## 逃生口（显式且可审计）

- commit message 含 `[skip-plan]` 或环境变量 `SKIP_PLAN_GATE=1` → 跳过 plan 要求（Gate 2/3）
- commit message 含 `[docs-only]` / `[no-docs]` 并说明理由 → 跳过 docs 要求（Gate 1）
- 单文件 < 20 行且不跨目录 → 自动跳过 Gate 2/3
- `SKIP_DOCS_CONTRACT=1` 仅应急

## 本地门禁

- 提交前自动跑：`.githooks/pre-commit` → `python scripts/check-docs-contract.py --mode=fast`
- 推送前自动跑：`.githooks/pre-push` → `python scripts/check-docs-contract.py --mode=full`
- 手动验证：`python scripts/check-docs-contract.py --mode=full`
- hook 重连：`python scripts/install-hooks.py`

注意：本机未安装 Python 时 hook 会警告并放行（见 `docs/runbooks.md`）。

## active plan 必需字段（Gate 4 检查，标题中英任一即可）

`Stage`（阶段）、`Status`（状态）、`Acceptance`（验收）、`Completion Evidence`（完成证据）、`Remaining Gaps`（剩余缺口）、`Next Step`（下一步）。模板见 `docs/exec-plans/active/define-scope.md`。

## 技术约定

- 运行时：Python 优先（数据 / 分析栈）。
- 平台：Windows / macOS / Linux 均为一等公民；脚本禁止绑定单一平台路径与命令。
- CI：暂无（见 `docs/status.md` 的缺口清单）。

## 当前业务模块

- 市场环境分析 API：`src/market_environment/`；负责五大指数行情适配、指标计算、数据质量和 FastAPI 契约。
- 市场环境分析网页：`apps/market-environment-dashboard/`；Vue 3 + Vite + TypeScript + ECharts 单页看板，开发时通过 Vite 将 `/api` 代理到 8000 端口。
- 交易规则平台：`src/trading_system/` + `trading-rules/`；负责规则 schema、快照、确定性 evaluator、证据、回测和 CI 契约。
- 修改上述代码时必须同步 `docs/architecture.md`、`docs/runbooks.md` 和 active plan；市场广度数据（上涨/下跌家数及涨跌幅中位数）暂不属于当前范围。
