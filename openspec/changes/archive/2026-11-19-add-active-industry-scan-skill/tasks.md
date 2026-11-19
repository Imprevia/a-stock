## 1. 前置与骨架

- [x] 1.1 新建 `docs/exec-plans/active/active-industry-scan-skill-plan.md`，包含 `Stage` / `Status` / `Acceptance` / `Completion Evidence` / `Remaining Gaps` / `Next Step` 六个必需字段，并更新 `docs/exec-plans/active/_index.md`；用 `python scripts/check-docs-contract.py --mode=fast` 验证通过
- [x] 1.2 创建 `.agents/skills/a-stock-active-industry-scan/` 目录骨架（`scripts/`、`references/`、`.gitignore`），确认 `.gitignore` 覆盖 `.cache/`、`__pycache__/`、`*.pyc`
- [x] 1.3 写 `SKILL.md` frontmatter，`name` 为 `a-stock-active-industry-scan`、`description` 含触发词「最活跃的行业」「多个行业」「每个行业有多少只股票」「双榜交集」「盘中扫描」；用 `python -c "import re;print(bool(re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', open('.agents/skills/a-stock-active-industry-scan/SKILL.md').read().split('name:')[1].split('\n')[0].strip())))"` 验证名称合法，并确认新会话的 skill 目录中出现该条目

## 2. 纯计算层（零 I/O）

- [x] 2.1 实现 `scripts/quadrant.py`：输入两个榜的行业命中字典与阈值，输出四象限归属；验证单元测试覆盖「双榜均达标」「仅成交额达标」「仅换手达标」「均未达标」四种组合
- [x] 2.2 实现 `scripts/percentile.py`：实现 20 日均值、放大倍数、250 日分位与 `ok`/`insufficient` 状态；验证单元测试覆盖 bar 数 3、59、60、239、272 五个边界，确认 `bar < 60` 时返回 `insufficient` 且分位为 `null` 而非 0
- [x] 2.3 验证 `percentile.py` 的分位对成交量计算与对换手率计算结果一致（构造同一窗口的 volume 与 turnover 两份输入，断言分位相等）
- [x] 2.4 实现 `scripts/contract.py`：生成 `schemaVersion`、`ruleVersion`（固定 `active-industry-scan-v1`）、`reportId` 与运行时刻；验证 `reportId` 在同一次运行内稳定、跨运行唯一

## 3. 取数层

- [x] 3.1 实现 `scripts/sina_client.py` 的排序路径：按 `sort=amount` 与 `sort=turnoverratio` 各取 400 只候选池（每榜 4 页、8 并发）；验证单次拉取耗时低于 2 秒且返回条数为 400
- [x] 3.2 实现 `sina_client.py` 的全量降级路径：排序接口失败时拉取全量 56 页后本地重排；验证用 fixture 注入排序失败后仍产出完整榜单且 `quality.degradations` 记录了降级原因
- [x] 3.3 实现 `sina_client.py` 的 5 分钟 K 线采集（`scale=5`，20 并发）；验证当日 bar 按结束时刻过滤后，`elapsedBars` 与截止时刻计算正确，且首根 bar 时间戳为 `09:35`
- [x] 3.4 实现 `scripts/fuyao_client.py` 的上市日期读取（`symbol list --exchange SH,SZ,BJ --limit 10000`）与按日缓存；验证缓存命中时耗时低于 0.1 秒、缓存文件落在 `.cache/active-industry-scan/symbols/`、连续两次调用结果 checksum 一致
- [x] 3.5 实现 `fuyao_client.py` 的 250 日线与成分股读取，复用 `qts04-core` 的凭据解析顺序（`FUYAO_API_KEY` → `MARKET_ENVIRONMENT_FUYAO_API_KEY` → `deploy/truenas/deploy.env`）；验证凭据不出现在缓存、日志与结构化输出中

## 4. 新股过滤与行业聚合

- [x] 4.1 实现新股过滤：在取 Top N 之前按 `list_date` 剔除不足 `--min-listing-days` 的股票；验证用 2026-11-19 fixture 断言换手率榜剔除 9 只、成交额榜剔除 2 只、榜单仍满 50 条
- [x] 4.2 实现排除段输出，每只含代码、名称、上市日期、上市天数、原始排名；验证 `list_date` 缺失的股票被排除并计入 `missingListDate`
- [x] 4.3 实现 `scripts/industry_map.py` 的一级行业映射与按日缓存；验证成分股缓存命中时行业段耗时为 0，且输出同时含命中数、成分股总数与命中率
- [x] 4.4 实现 `--level 1|2|both` 参数；验证 `--level 2` 输出二级行业命中数、`--level both` 同时输出两级且两级计数互不推导
- [x] 4.5 验证命中率分母为零时返回 `null` 而非 0（构造无成分股行业的 fixture）

## 5. 时点状态机与分位延迟

- [x] 5.1 实现 `sessionState` 判定（`preopen` / `intraday` / `lunch` / `settling` / `closed`），复用 `MARKET_ENVIRONMENT_OPEN_TIME`（默认 09:30）与 `MARKET_ENVIRONMENT_SETTLEMENT_TIME`（默认 15:10）；验证 09:29、09:31、11:29、11:31、12:59、13:01、14:59、15:05、15:11 九个时刻的状态输出正确
- [x] 5.2 实现 `elapsedBars ≤ 3` 时的早期快照标注与首根 bar 集合竞价提示；验证 09:40 运行时输出包含该提示
- [x] 5.3 实现盘中分位字段的 `deferred` 输出，含 `reason` 与 `availableAfter`；验证 `sessionState=intraday` 时该字段不可用、`closed` 时补算，且任何状态下都不会出现按固定比例缩放得到的估算值

## 6. 编排与产物

- [x] 6.1 实现 `scripts/scan_pipeline.py` 编排入口，串起双榜、过滤、分时、行业聚合与四象限；验证完整热路径（盘中、缓存命中）耗时低于 6 秒
- [x] 6.2 实现交集计算与空交集处理；验证构造两榜完全不相交的 fixture 时输出空数组、整体状态仍为 `ok`、且不触发任何阈值放宽
- [x] 6.3 实现 `handoff` 段（候选行业 thscode 列表与入选原因）并声明本 Skill 不评分；验证该列表可直接作为 `a-stock-qts04-sector-direction` 的输入参数
- [x] 6.4 实现 `scripts/report.py`，从 JSON 纯渲染 Markdown；验证报告中的每个数值都能在 JSON 中找到同源字段，且交集段与排除段在两份产物中都存在
- [x] 6.5 实现 `--output` 与 `--fixture` 参数；验证 `--fixture` 模式下全程无网络请求（断网执行仍成功）

## 7. 降级矩阵与测试

- [x] 7.1 用 fixture 覆盖单源失败矩阵：单榜失败、双榜失败、分时失败、成分股失败有缓存、成分股失败无缓存；验证每种情形落在 `degraded` 或 `insufficient` 且其余段完整
- [x] 7.2 验证全部数据源失败时以非零状态退出，不输出看似成功的空结果
- [x] 7.3 写 `references/data-contract.md`，记录双榜口径、降级顺序、成分股仅当前快照的限制与缓存策略
- [x] 7.4 写 `references/metric-definitions.md`，记录换手率口径（`float-share`）、分位等价性证明、流通股本变动不可检测的限制与四象限阈值
- [x] 7.5 在断网环境执行全部测试，验证无网络依赖、无真实凭据依赖

## 8. 文档与门禁

- [x] 8.1 在 `docs/repository-guide.md` 的 Skill 映射表新增一行，说明该 Skill 的位置、职责与不做什么；用 `python scripts/check-docs-contract.py --mode=full` 验证通过
- [x] 8.2 回填 `docs/exec-plans/active/active-industry-scan-skill-plan.md` 的 `Status`、`Completion Evidence` 与 `Remaining Gaps`
- [x] 8.3 用 2026-11-19 的真实数据跑一次端到端，断言输出与本次设计阶段的实测结果一致（换手率榜剔除 9 只、成交额榜剔除 2 只、双榜交集与行业分布可复现）