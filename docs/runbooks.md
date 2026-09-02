# Runbook

## 环境要求

- Python 3.11+（建议使用仓库 `.venv`）
- Node.js 18+ 与 npm
- git
- 可选：GitHub Actions（仓库 CI）
- 可访问通达信 TCP 和腾讯/百度 HTTPS 行情接口的网络

安装依赖：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install --prefix apps/market-environment-dashboard
```

## 启动命令

启动后端 API：

```bash
python -m uvicorn src.market_environment.api:app --reload --port 8000
```

启动前端开发服务器（另开终端）：

```bash
npm run dev --prefix apps/market-environment-dashboard
```

浏览器访问 `http://localhost:5173`；生产构建后可由 FastAPI 从 `apps/market-environment-dashboard/dist` 托管静态文件。

前端可读性基线：全部可见文字（包括 ECharts 图例、坐标轴和 tooltip）不得小于 `14px`。修改页面样式后需检查 01 至 09 视图，并在桌面与移动宽度确认没有文字重叠、控件截断或页面级横向溢出；宽表自身的横向滚动属于预期行为。

新增或调整页面时，布局、组件、颜色、图表、状态和响应式验收遵循 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。

接口检查：

```bash
curl "http://127.0.0.1:8000/api/health"
curl "http://127.0.0.1:8000/api/market-environment?as_of=2026-08-28"
curl "http://127.0.0.1:8000/api/market-environment/core?as_of=2026-08-28"
curl "http://127.0.0.1:8000/api/market-environment/chapter-01?as_of=2026-08-28&section=breadth"
```

`/api/market-environment` 保留完整聚合响应用于兼容；网页首屏使用 `/api/market-environment/core`，该接口不访问全 A、涨跌停池和行业 provider。章节接口的 `section` 支持 `breadth`、`limits`、`sectors`、`activeDirection` 和 `summary`，其中 `summary` 用于第 08、09 页并加载全部已接入章节证据。`chapter01` 仍是向后兼容的可选扩展。`breadth`、`sectors` 和 `activeDirection` 只在请求上海时区当前日期、且其实际交易日与最新市场快照一致时读取；查询历史日期时这些当前快照型数据集返回 `missing`，不得拿今日数据回填。`limits` 使用实际交易日查询日期化涨停/跌停/炸板池。所有数据集检查 `quality.status` 和 `quality.warnings`；缺失值保持 `null`，不要在前端转换为 0。

章节请求按数据集缓存 30 秒。`breadth` 与 `activeDirection` 共享全 A 快照，因此任一章节首次请求会同时缓存两者；后续切换不重复拉取全市场快照。排查加载慢时分别计时核心接口和目标章节接口，不再只看完整聚合接口总耗时。

看板日期控件使用浏览器本地日期作为默认值和最大值，不要改回 `new Date().toISOString().slice(0, 10)`；API 的默认日期与未来日期校验使用 `Asia/Shanghai`。东方财富 `data.diff` 若为键值对象会先转为行列表；无效行会被丢弃，不能用 0 填充。主 `push2` 全 A 快照必须满足返回行数不小于 `data.total`，否则视为不完整并触发市场广度降级；降级成功时 `chapter01.breadth.quality.source` 为 `eastmoney-clist-delay`、状态为 `fallback`。若主域和延迟域均失败，保留 `null` 并在 `quality.warnings` 记录两段错误。

指数 `history` 契约中的每个点应包含 `date`、`open`、`close`、`low`、`high`、`ma5`、`ma10`、`ma20`、`ma60` 和 `amount`。浏览器 QA 必须确认 60 日图存在非空 K 线实体、红涨绿跌、均线叠加和 OHLC tooltip；禁止用收盘价复制生成开高低。

指数卡的量价区域应先展示 `amountRatio5`，再展示可选的 `volumePriceState`。量价状态为 `null` 表示价格与成交额组合未命中任何明确规则，不是接口错误，前端不得改写为“量价平稳”；只有比值缺失时显示 `--` / “数据不足”。

每个指数的 `combination` 契约应包含 `key`、`state`、`matched`、`tone`、`evidence` 和 `tradingMode`。`chapter01.combinationOverview` 汇总 `strength`、`stage`、`capitalAcceptance`、`tradingMode`、`confidence` 和 `evidence`。浏览器 QA 必须切换至少两个指数，确认组合状态和证据同步变化；未命中状态显示“未命中明确组合”，不得补成六类中的任意一类。

本地门禁：

```bash
# 手动验证文档契约（快速 / 完整）
python scripts/check-docs-contract.py --mode=fast
python scripts/check-docs-contract.py --mode=full

# （重）安装本地 hooks
python scripts/install-hooks.py
```

交易规则平台离线命令：

```bash
python -m src.trading_system.cli rules validate
python -m src.trading_system.cli rules coverage
python -m src.trading_system.cli docs sync-check
python -m src.trading_system.cli evaluate --rule-set market-environment --snapshot tests/fixtures/trading-system/market-environment-complete.json --output .artifacts/evidence
python -m src.trading_system.cli evidence verify .artifacts/evidence
```

创建快照与回测：

```bash
python -m src.trading_system.cli snapshot create --as-of 2026-08-31 --output .artifacts/snapshot.json
python -m src.trading_system.cli backtest --rule-set market-environment --snapshots .artifacts/history --output .artifacts/backtest.json
```

PR 验证必须只使用 `tests/fixtures/trading-system/`，不得访问外部网络。盘后 workflow 可访问真实数据；任何 provider 失败必须写入 snapshot 的质量状态，并上传 `degraded` 或 `insufficient` 证据，不能用 0 填充缺失数据。

## 验证矩阵

| 检查 | 命令 / 方法 | 证据位置 | 必需 |
|------|-------------|----------|------|
| docs-contract | `python scripts/check-docs-contract.py --mode=full` | 终端输出 / plan 的 Completion Evidence | 是 |
| hooks 连通 | `git config core.hooksPath`（应为 `.githooks`） | 终端输出 | 是 |
| Build | `npm run build --prefix apps/market-environment-dashboard` | 终端输出 / plan | 是 |
| Backend tests | `.venv` Python 下运行 `python -m pytest tests -q` | 终端输出 / plan | 是 |
| Frontend build | `npm run build --prefix apps/market-environment-dashboard` | 终端输出 / plan | 是 |
| Browser QA | 启动前后端后检查 01 至 09 视图的桌面与移动宽度、最小 `14px` 字号和溢出；01 页检查真实 OHLC K 线、均线和 tooltip；确认首屏先于章节数据出现、章节失败不清空核心数据 | 截图 / plan | 是 |
| Rule registry | `python -m src.trading_system.cli rules validate` | 终端输出 / PR workflow | 是 |
| Rule coverage | `python -m src.trading_system.cli rules coverage` | `trading-rules/coverage.yaml` / PR workflow | 是 |
| Deterministic replay | 固定 fixture 执行两次并比较 canonical result | pytest / golden fixture | 是 |
| Evidence verification | `python -m src.trading_system.cli evidence verify <bundle>` | manifest / CI Artifact | 是 |

## 常见调试路径

- **pre-commit / pre-push 未触发**：`git config core.hooksPath` 是否为 `.githooks`；不是则跑 `python scripts/install-hooks.py`。
- **API 返回 503**：先检查 `/api/health`，再查看服务日志中的各指数数据源错误；mootdx 失败时应看到百度或腾讯降级 warning。
- **核心接口冷启动仍较慢**：分别计时 `/api/market-environment/core` 与章节接口。若核心接口慢且 warning 显示通达信不可用，当前实现仍会为五个指数串行执行既定降级链；不要通过跳过价格交叉校验换速度，后续应以独立熔断或线程安全并发方案处理。
- **成交额比值显示 `--`**：腾讯历史 K 线公共接口可能只提供成交量而无成交额；服务会先尝试新浪指数 K 线（用腾讯实时成交额校准），再尝试东方财富显式指数 K 线，最后降级到腾讯。若所有历史成交额源均不可用，保留 `--`，不要把缺失成交额当成 0。
- **有 5 日成交额比值但没有量价状态**：该日价格变化与比值处于已定义规则之间的空档，属于预期的未分类状态；不要在 API 或前端增加兜底分类。
- **组合判断显示“未命中明确组合”**：先核对 API 的 `combination.evidence` 和量化版 `0.2` 映射。六类条件要求同时成立，单独处于高位、放量或站上均线都不足以形成组合状态。
- **第 01 章证据显示 `missing` / `partial`**：先看对应对象的 `quality.warnings`。历史日期缺少广度、板块或成交额榜是当前快照源的预期边界；东方财富 403 或空 `data` 也必须保留缺失状态，不能用空数组伪造为 0。只有接口成功且明确返回空 `pool` 时，涨跌停计数才可为 0。
- **指数价格异常**：检查实时腾讯报价是否可用。沪市歧义代码没有实时交叉校验时，mootdx/百度结果会被拒绝，避免错误股票数据进入页面。
- **hook 报 `\r` 相关错误**：`.githooks/*` 行尾被改为 CRLF，恢复 LF（`.gitattributes` 已强制 `eol=lf`，重新 checkout 即可）。
- **gate 误报需要紧急绕过**：优先修文档；确需绕过用 commit message 标记（`[skip-plan]` / `[no-docs]` + 理由）或环境变量（见 `AGENTS.md` 逃生口）。
- **规则加载失败**：先运行 `rules validate`；重复 ID、未知字段、未知 evaluator、阈值无来源或非法生命周期都会在执行前失败。
- **盘后证据显示 degraded/insufficient**：检查 manifest 的 provider 状态和 warnings。东方财富 403 不应循环重试；切换到降级源或等待下一次运行。
- **证据校验失败**：不要手改证据文件。重新从原 snapshot、规则版本和 Git SHA 执行；manifest 中任一 SHA-256 不一致都视为证据失效。

## 运维控制

- hook 逃生开关：`SKIP_DOCS_CONTRACT=1`（仅应急，须在 plan 或 commit message 记录原因）。

## 失败解读指引

gate 输出的每条错误消息都自带修复指引（对应 `AGENTS.md` 硬规则编号语义）。修改 `scripts/check-docs-contract.py` 的消息文案时必须同步 `AGENTS.md`。
