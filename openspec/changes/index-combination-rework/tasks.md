# Tasks: 指数、趋势位置和成交额补全与第四部分呈现重做

## 1. 事实源与规则登记（Gate 前置）

- [ ] 1.1 创建 `docs/exec-plans/active/index-combination-rework.md`（含 Stage/Status/Acceptance/Completion Evidence/Remaining Gaps/Next Step 六字段），验证 `python scripts/check-docs-contract.py --mode=fast` 通过
- [ ] 1.2 在 `搭建交易系统-量化版/01-如何判断市场环境/01.指数、趋势位置和成交额.md` 规则表追加 `QTS-01-01-06`（五态同步，含深成指中性口径说明）、`QTS-01-01-07`（20 日区间位置）、`QTS-01-01-08`（5 日成交额比值）三行，并同步 `docs/trading-system-quantified-directory.md`（327→330、46→49）与 `AGENTS.md` 口径，验证目录索引与文档规则数一致
- [ ] 1.3 在 `trading-rules/rule-sets/market-environment.yaml` 追加三条 `metric.band` 规则（append-only、不入 `QTS-01-00-01` members），在 `trading-rules/coverage.yaml` 登记 executable，验证 `python -m src.trading_system.cli rules validate` 与 `rules coverage` 通过
- [ ] 1.4 扩展 `src/trading_system` snapshot schema 与固定快照 fixture 新增输入字段（`index.sync_pattern`、`index.range_position_20`、`market.turnover_ratio_5`），补三条规则的 evaluator 测试，验证固定快照 golden 回放中 `QTS-01-00-01` 及既有全部规则分数与 trace 逐字节不变

## 2. Provider 深度扩展

- [ ] 2.1 将指数 K 线 `limit` 从 160 提升到 280 并核对 mootdx/百度/新浪/东方财富/腾讯各路径参数（`datalen`/`lmt` 同步上调），验证 provider 单测覆盖新深度且降级链与价格校验行为不变
- [ ] 2.2 盘后或显式本地命令对五个指数逐一冒烟验证 280 根返回（验证条数 ≥ 280 或按 provider 上限如实记录），核对冷缓存耗时对比并记录到 exec plan 证据

## 3. 计算层纯函数

- [ ] 3.1 在 `src/market_environment/calculations.py` 实现同步性五态判定（优先级：同步上涨 > 普遍走弱 > 权重护盘 > 成长占优 > 分化未定型；深成指仅计入同步多数），验证单测覆盖五态各自命中、优先级冲突与未定型场景
- [ ] 3.2 实现 MA20 斜率 250 日滚动分位、量价推进效率 250 日滚动分位（分母下限 0.5）与五指数均线多头比例计算，验证单测覆盖 ≥280 根、60–279 根降置信、<60 根 insufficient 三档边界
- [ ] 3.3 实现收束句成分组装（同步性、MA20 相对位置、60 日区间分档、成交额对 5 日均值、价格推进、环境倾向；缺成分输出"数据不足"分段），验证单测覆盖全成分与部分缺失两场景

## 4. 服务层与 API 契约

- [ ] 4.1 在 `schemas.py` 新增可选字段并在 `service.py` 输出：`syncPattern`（五态码 + 中文标签）、`ma20SlopePercentile`、`advanceEfficiencyPercentile`、市场层 `bullishAlignmentRatio`、`summarySentence`、`dataGaps`（闭合 reason 枚举），验证 API 契约测试覆盖新字段与各缺失原因枚举
- [ ] 4.2 将 `_combination_overview` 的 strength 文案接入五态同步输出并保留广度验证语义，验证既有四问契约测试更新后通过且未命中时仍不兜底

## 5. 前端重做

- [ ] 5.1 同步 `types.ts` 契约，重组第 01 页第四部分为"四问结论条 + 五指数 × 六组合矩阵 + 选中行证据展开"（矩阵行与指数卡联动、六类组合定义合并到列头），验证前端组件测试覆盖矩阵渲染、行展开与联动
- [ ] 5.2 增加收束句面板与 `dataGaps` 差异化缺失文案（四种 reason 各自文案），移动端矩阵紧凑化/横向滚动，验证前端测试覆盖缺失态文案分支
- [ ] 5.3 运行 `npm run build`（生产构建）并用真实浏览器走查桌面与移动第 01 页（指数切换、矩阵行点击、收束句、缺失态），截图证据记入 exec plan

## 6. 验收与回写

- [ ] 6.1 全量 Python 与前端测试、`python scripts/check-docs-contract.py --mode=full`、`openspec validate index-combination-rework --strict` 全部通过，结果记入 exec plan 证据
- [ ] 6.2 回写 `docs/status.md`（已实现/口径 49 条）、`docs/architecture.md`（数据流与深度变更）、`docs/runbooks.md`（280 根参数与历史快照 160 根限制），exec plan 六字段收口并标注 Remaining Gaps
