# AGENTS.md — a-stock 仓库规则

本仓库是面向盘后研究的 agent-first 工程系统：后端提供市场环境分析与交易规则执行能力，前端提供可解释的市场看板，`docs/`、`trading-rules/` 和 `evidence/` 分别承担文档、机器规则和验证证据的事实职责。

## 仓库地图

- `src/market_environment/`：FastAPI 市场环境 API、provider 降级、指标计算、数据质量、快照与采集任务。
- `apps/market-environment-dashboard/`：Vue 3 + Vite + TypeScript + ECharts 看板；开发时由 Vite 将 `/api` 代理到后端。
- `src/trading_system/` + `trading-rules/`：规则 schema、快照、确定性 evaluator、证据、回测和 CLI。
- `deploy/`：Kustomize/Helm 部署包；`scripts/`：渲染、部署和文档门禁脚本。
- `tests/`：后端、规则平台、部署清单和安全护栏测试；`docs/`：架构、规格、运行手册、计划和状态记录。

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

`搭建交易系统-量化版/` 是人读说明层；`trading-rules/` 是机器执行事实源。规则 ID、覆盖清单和相对路径是稳定接口，不得因文字调整而重排。规则变更必须同步 YAML、量化文档、覆盖清单、测试和证据引用。PR 规则验证只能使用固定快照离线运行；真实数据获取只允许在盘后或显式本地命令中执行，数据源失败必须输出 `degraded` 或 `insufficient`，不得伪造为成功。

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

GitHub Actions 的规则门禁见 `.github/workflows/trading-rules-pr.yml`；它会校验规则、文档同步、全量确定性测试和 docs contract。若本机缺少 Python，hook 可能只警告放行，不能把这种放行当作验证通过。

## active plan 必需字段（Gate 4 检查，标题中英任一即可）

`Stage`（阶段）、`Status`（状态）、`Acceptance`（验收）、`Completion Evidence`（完成证据）、`Remaining Gaps`（剩余缺口）、`Next Step`（下一步）。模板见 `docs/exec-plans/active/define-scope.md`。

## 技术约定

- 运行时：Python 优先（数据 / 分析栈）。
- 平台：Windows / macOS / Linux 均为一等公民；脚本禁止绑定单一平台路径与命令。
- 后端测试使用 pytest；前端测试使用 Vitest，生产构建使用 Vite。
- CI 规则门禁必须保持离线、确定性和可复现；盘后真实数据 workflow 与 PR 门禁分离。

## 验证命令

按改动范围选择最小但足够的验证，并在交付说明中记录未运行的检查：

```bash
python -m pytest tests -q
python -m src.trading_system.cli rules validate
python -m src.trading_system.cli rules coverage
python -m src.trading_system.cli docs sync-check
python scripts/check-docs-contract.py --mode=full
```

前端改动还需在 `apps/market-environment-dashboard/` 执行 `npm run test` 和 `npm run build`。部署清单改动先执行 Helm lint、离线 template 或 `python scripts/render-k3s.py --kube-version <版本>`；不要把真实 provider smoke、生产接口访问或部署写操作混入普通测试。

## 领域不变量与安全边界

- 市场数据必须保留真实日期、来源和质量状态；缺失数据用 `null` / `missing` / `insufficient` 表达，不用 0 或其他日期数据补齐。
- 普通 GET 只读本地精确日期快照或聚合；provider 采集只能由明确的盘后或本地采集命令触发。
- `scheduledCollection` 默认必须保持 `enabled=false` 且 `suspend=true`。生产部署、手工采集、CronJob、Helm release、NodePort、PVC 和 SQLite 数据操作须遵循 `docs/runbooks.md`，需要外部写入时先取得明确授权。
- 不得提交凭据、私有环境文件、真实数据快照或运行时产物；不要执行删除 PVC、卸载 release、修改生产集群或改变远端分支的命令来“清理”问题。
- 前端所有可见文字（含图例、坐标轴和 tooltip）不小于 `14px`；桌面和 390px 移动宽度均不得出现页面级横向溢出、重叠或截断。宽表自身滚动除外。
- 当前未接入的数据集和未验证的交易规则必须保持明确的 `unverified` / `documented-only` 状态，不得用历史评论或口头说明代替证据。

修改后同步更新受影响的 `docs/architecture.md`、`docs/runbooks.md`、产品规格或 active plan；阶段完成前补齐 plan 的 `Status`、`Completion Evidence`、`Remaining Gaps` 和 `Next Step`。

## 沟通语言

- 后续与用户的回复统一使用中文。
- 不输出内部思考过程；仅提供必要的结论、依据和执行结果。
