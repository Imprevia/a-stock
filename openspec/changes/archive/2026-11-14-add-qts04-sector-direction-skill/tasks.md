## 1. 文档基线与索引

- [x] 1.1 确认 `docs/exec-plans/active/add-qts04-sector-direction-skill.md` 含全部必需字段（Stage / Status / Acceptance / Completion Evidence / Remaining Gaps / Next Step），并在 `docs/exec-plans/active/_index.md` 中登记；验证 `python scripts/check-docs-contract.py --mode=fast` 能识别该 plan。
- [x] 1.2 在 `docs/repository-guide.md` 的 Skill 映射表中新增 `a-stock-qts04-sector-direction` 的三行条目（SKILL 指令、scripts、references），写明职责与安全边界；验证表格中记录的路径与后续实际文件一一对应。

## 2. Skill 包骨架

- [x] 2.1 创建 `.agents/skills/a-stock-qts04-sector-direction/` 目录与 `SKILL.md`，frontmatter 的 `name` 为 `a-stock-qts04-sector-direction`，`description` 明确触发场景（板块定向、强势板块、板块四象限、某交易日板块排名）并声明不产出买卖建议；验证 frontmatter 可被解析且描述不含 `validated` 承诺。
- [x] 2.2 在 `SKILL.md` 写入工作流章节：前置检查 → 取块目录 → 拉板块日线 → 算四指标 → 排序取前 N → 算宽度 → 打分 → 输出；验证每个步骤都指明对应脚本入口或命令。
- [x] 2.3 在 `SKILL.md` 写入输出合同：方向数量上限 3、每条方向必含五指标明细与确认/失效条件、`needs-backtest` 标记；验证输出合同与 spec 中"方向输出包含确认与失效条件"及"结论边界与规则状态"两条要求逐条对应。
- [x] 2.4 在 `SKILL.md` 写入失败边界：CLI 缺失、凭据缺失、限流、目标日无数据各自的状态与处理；验证四条边界都能在脚本中找到对应分支。

## 3. 取数层

- [x] 3.1 实现 `scripts/fuyao_client.py`：以 `subprocess.run` 调用 `hithink-finance`，统一解析 `{ok, command, data, meta}` 信封，设置显式超时与 `check=False`；验证成功响应返回 `data`、`ok=false` 响应抛出带原始 `code`/`message` 的专用异常。
- [x] 3.2 在 `fuyao_client.py` 实现前置检查：检测 `hithink-finance` 是否在 `PATH`、`FUYAO_API_KEY` 环境变量或 `deploy/truenas/deploy.env` 是否可用；验证两者任一缺失时抛出 `insufficient` 类异常且不发起任何子进程调用。
- [x] 3.3 在 `fuyao_client.py` 实现限流处理：识别 HTTP 429 与 `code=4001`，执行有界指数退避后重试有限次数；验证注入的假 CLI 连续返回 429 时退避次数与总耗时受上限约束，最终抛出 `degraded` 类异常。
- [x] 3.4 在 `fuyao_client.py` 封装四个高层方法：`list_industries()`、`industry_history_batch(codes, start, end)`、`constituents(thscode)`、`stock_history_batch(codes, start, end)`；验证批量方法按每批不超过 10 个代码切分，且不超过 fuyao 的原始 token 上限。
- [x] 3.5 实现凭据脱敏：验证任异常消息、日志与结构化输出中都不出现 API Key 明文或连续 8 字符以上片段。

## 4. 缓存层

- [x] 4.1 实现 `scripts/cache.py`：把板块日线与个股日线按 `thscode` 与交易日写入可重建缓存目录，记录 `fetched_at` 与数据窗口；验证写入后可读回且字段完整。
- [x] 4.2 实现缓存状态判定：`cold`（目标日缺失）、`warm`（目标日齐全）、`partial`（窗口不足但目标日存在）；验证三种状态各有对应用例。
- [x] 4.3 实现缺口补齐：缓存窗口不足时只拉缺失区间；验证补齐请求的 `start`/`end` 精确对应缺口，不整段重拉。
- [x] 4.4 确认缓存路径不在 git 跟踪范围内且在 `.gitignore` 中；验证 `git check-ignore` 返回该路径。

## 5. 指标与打分

- [x] 5.1 实现相对强度计算：`sectorReturn5 - benchmarkReturn5` 与 `sectorReturn20 - benchmarkReturn20`，基准固定 `000001.SH`；验证合成序列下手算值与实现值一致，窗口不足时返回 `null`。
- [x] 5.2 实现成交额增量：`turnover / mean(turnover, 20)`，20 日均值不含当日；验证分母为零或缺失时返回 `null` 而非 0。
- [x] 5.3 实现板块宽度：对成分股逐只计算 MA20，统计 `close > MA20` 比例，并输出有效覆盖率；验证覆盖率 0.60 的样本被判为 `insufficient` 且不进入排名。
- [x] 5.4 实现持续与恢复：近 5 日跑赢基准天数与最大回撤修复率的均值分；验证 5 日窗口不足时该指标为 `null`，且不参与加权。
- [x] 5.5 实现滚动分位打分：`rolling_midrank` 窗口 250、最少观测 60，五档边界 `≤0.20=0`、`≤0.40=25`、`≤0.60=50`、`≤0.80=75`、`>0.80=100`；验证 59/60/250 三个观测数分别产出 `insufficient`（得分为 `null`）/`reduced-confidence`/`ok`。
- [x] 5.6 实现加权总分与权重归一：五指标权重 25/15/20/20/20；验证某指标 `null` 时按剩余有效权重重新归一，且输出记录原始权重与归一权重。
- [x] 5.7 实现四象限分类：由上涨覆盖率与资金强度原始值判定真实流入/短线脉冲/权重拉升/资金撤退；验证分位全部降级时四象限仍能输出。

## 6. 编排与输出

- [x] 6.1 实现 `scripts/sector_pipeline.py` 主流程：串起取数、缓存、四指标、排序、`--breadth-universe` 截取、宽度、打分、分类；验证在 fixture 模式下端到端产出结构化 JSON。
- [x] 6.2 实现命令行参数：`--as-of`、`--breadth-universe`（默认 30）、`--cache-dir`、`--fixture`、`--output`；验证参数缺省时行为符合设计默认值。
- [x] 6.3 实现方向输出：最多 3 个方向，每个含板块总分、持续性分、四象限、五指标明细、覆盖率、确认条件与失效条件的具体数值；验证无合格方向时输出空列表并注明是被分数门槛还是覆盖率闸门排除。
- [x] 6.4 实现质量状态传播：`ok` → `degraded` → `insufficient` 单向恶化；验证单个行业取数失败只降级该行业，不使整体失败。
- [x] 6.5 验证输出不含 `validated`、买卖建议、仓位、个股推荐字样，且每条规则状态为 `needs-backtest`。

## 7. 参考资料

- [x] 7.1 编写 `references/data-contract.md`：记录四个 fuyao 命令的参数、响应字段、日期口径、批量上限、限流语义，以及缓存与降级规则；验证其中每个命令都能用 `hithink-finance schema <id>` 复核。
- [x] 7.2 编写 `references/scoring-rules.md`：逐条记录 `QTS-04-01-01` ~ `-05` 的公式、窗口、权重、分位边界、否决条件与状态；验证规则 ID 与 `trading-rules/coverage.yaml` 中的条目一一对应且不重排。
- [x] 7.3 验证两份参考文档都由 `SKILL.md` 在需要时链接，且不含与 `src/` 重复的阈值副本之外的第二套定义。

## 8. 离线测试

- [x] 8.1 建立 `tests/fixtures/a_stock_qts04_sector_direction/` 合成样本：行业目录、板块日线、基准日线、成分股、个股日线；验证样本为小型合成数据，不含真实行情快照或凭据。
- [x] 8.2 编写 `tests/test_a_stock_qts04_sector_direction_skill.py`：覆盖五指标数值、分位三档、覆盖率闸门、权重归一、四象限、方向数量上限与输出边界；验证 `python -m pytest tests/test_a_stock_qts04_sector_direction_skill.py -q` 全绿。
- [x] 8.3 增加失败路径用例：CLI 缺失、凭据缺失、429 退避耗尽、目标日空数据、缓存冷启动；验证每种情况产出对应状态且不产生伪造数据。
- [x] 8.4 验证测试全程无网络：通过 monkeypatch 或注入假 CLI 保证不产生外部请求，并断言未调用真实 `subprocess` 到 `hithink-finance`。

## 9. 完成门禁

- [x] 9.1 运行 `python -m pytest tests/test_a_stock_qts04_sector_direction_skill.py -q` 与 `openspec validate add-qts04-sector-direction-skill --strict`，把结果记入 active plan 的 Completion Evidence。
- [x] 9.2 运行 `python scripts/check-docs-contract.py --mode=full` 与 `git diff --check`，把结果记入 Completion Evidence。
- [x] 9.3 回填 active plan 的 Status、Completion Evidence、Remaining Gaps、Next Step；验证 `Remaining Gaps` 明确列出 STEP 2 之后未实现、生产 sector 500 未修、分位缓存依赖三项。
- [x] 9.4 验证本轮未改动 `trading-rules/`、`src/`、`coverage.yaml`、生产集群与数据库：`git status --porcelain` 中不含这些路径。
## 10. 人工可读报告

- [x] 10.1 新增 `scripts/report.py`，实现 `render_markdown(result)` 纯渲染函数，不重算任何指标。
- [x] 10.2 CLI 增加 `--report PATH` 与 `--format {json,markdown,both}`；给 `--output` 而没给 `--report` 时自动写同名 `.md`。
- [x] 10.3 修正渲染缺陷：缺分渲染 `—` 而非 0、未计分指标权重渲染 `—`（避免权重列合计 120%）、短历史提示聚合、`insufficient` 时分节编号自适应。
- [x] 10.4 补充 12 个报告用例（分节、五指标表、缺分、权重合计、insufficient、无 `validated`、自动 `.md`、显式路径、stdout 格式）；验证 57 个用例全绿。
