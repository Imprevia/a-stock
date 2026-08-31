# 仓库状态

## 已实现

- harness 骨架：`docs/` 事实源体系、exec-plans 落地位、本地门禁（`.githooks/` + `scripts/check-docs-contract.py` + `scripts/install-hooks.py`）。
  - 事实源：`docs/repository-guide.md`、`docs/architecture.md`、`docs/runbooks.md`
- `搭建交易系统/` 已完成目录归档：11 个章节各自使用唯一章节目录，章节总览和正文不再散落于下载批次子目录。
- `docs/trading-system-directory.md` 已记录交易系统知识库的完整目录和文件清单，并由 `AGENTS.md` 提供入口说明。
- `搭建交易系统-量化版/` 已按原目录的 70 个相对路径完成量化重写：统一 YAML 元数据、327 个稳定规则 ID、固定/分位混合阈值、五档评分、风险否决、缺失处理和校准状态。
- `docs/trading-system-quantified-directory.md` 已记录量化版完整目录和维护规则；所有经验阈值当前均为 `needs-backtest`，没有规则被宣称为 `validated`。
- 市场环境分析看板：`src/market_environment/` + `apps/market-environment-dashboard/`。
  - 已接入 5 个指数、MA5/10/20/60、20/60 日区间位置、成交额比值、趋势/量价状态。
  - 已实现 mootdx → 百度 → 腾讯历史降级、腾讯实时交叉校验、30 秒缓存、非交易日回退和错误质量标记。
  - 已覆盖计算、服务层和 API 契约测试，并通过前端生产构建。
  - 已修复上证指数和中证500成交额缺失：新浪指数 K 线按腾讯实时成交额校准，量价状态不再误报“数据不足”。
- 交易规则工程化产品范围已定义：`docs/product-specs/trading-rule-engineering.md`。
- OpenSpec change `engineer-trading-rules-ci` 已建立 proposal、4 份 capability spec、design 和 19 项实施任务。
- 已修正干净环境依赖冲突：`httpx` 采用 mootdx 0.11.7 支持的 `>=0.25,<0.26` 区间，保证 CI 可解析安装。
- 交易规则工程平台已实现：327 条覆盖清单、第 01 章 46 条 YAML 规则、确定性执行、证据、回测骨架、CLI 和两条 GitHub Actions workflow。
- 固定快照生成 46 条 trace 并通过 golden 回放；全量测试 34 passed，OpenSpec strict 与 docs-contract full 均通过。

## 进行中

- 当前无 active exec plan；下一阶段需先创建扩展真实 provider 与历史校准计划。

## 未实现

- 市场广度（上涨家数、下跌家数、涨跌幅中位数）尚未接入，作为后续独立迭代。
- 第 01 章扩展真实 provider 尚未接入，盘后 workflow 当前会对缺失宽度、涨跌停、板块等输入输出 `insufficient` 证据。
- 第 02 至 11 章 281 条规则仍为 `documented-only`。
- 尚未积累 500–750 日历史快照，没有规则可晋级为 `validated`。

## 当前风险

- 真实行情源受网络可用性影响；页面会显示降级来源、过期报价和部分失败 warning。
- 真实历史数据能否达到目标 750 日取决于 provider 覆盖；不足 500 日时不得形成验证证据。
- `.codex/`、`.opencode/` — agent 工具会话目录（是否入库待确认）
- 本机无 Python 时本地 gate 退化为警告放行（记录于 `docs/runbooks.md`）。
- `docs/exec-plans/active/define-scope.md` 仍为仓库范围计划，与市场环境切片并行保留。

## 下一步

- 完成交易规则平台与第 01 章 46 条规则的离线确定性回放。
- 接入离线 PR workflow 和盘后证据 workflow。
- 后续按覆盖清单逐章实现 evaluator，并以第10章证据契约校准经验阈值。

## 最后更新

2026-08-31
