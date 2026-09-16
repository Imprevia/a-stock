## Context

- 看板 02 页当前由 `apps/market-environment-dashboard/src/App.vue` 第 598-602 行模板渲染，只暴露 4 张卡（上涨家数、下跌家数、上涨占比、涨跌幅中位数）和一个三段堆叠条，外加"组合判定"右侧面板。
- 后端 `src/market_environment/providers.py` 第 1072-1122 行 `_build_breadth` / `_breadth_result` 仅产出 7 个字段：`advanceCount` / `declineCount` / `flatCount` / `validCount` / `advanceRatio` / `medianReturn` / `state`。
- 文档 `搭建交易系统/01-如何判断市场环境/02.上涨家数、下跌家数和涨跌幅中位数.md` 第 9-47 行要求"先抄 6 项结果 + 选 1 个宽度标签 + 写次日验证项"，量化版 `搭建交易系统-量化版/01-如何判断市场环境/02.上涨家数、下跌家数和涨跌幅中位数.md` 给出 5 条规则 `QTS-01-02-01..05`，分位输入 4 个（上涨占比 / 涨跌差率 / 中位数 / 5 日动量）+ 1 个 boolean（指数广度一致性）。
- 已有现成设施可直接复用：`calculations._metric_percentile`（窗口 250 / 最小 60）、`snapshot_store.get("breadth", date)`、`EvidenceQuality`、`LimitHistoryPoint` 视觉模型、ECharts 折线图渲染经验（第 01 页 `renderChart`）。
- 仓库硬规则：≥14px 字体、桌面 + 390px 无页面级横向溢出、缺失值用 `--` / `数据不足` 而非 0、文档是事实源。

## Goals / Non-Goals

**Goals:**
- 02 页可被用户作为每日盘后复盘卡直接对照文档"先做再学"流程。
- 5 条量化规则在页面上能看到当前值、分位、得分、权重与缺失原因。
- 近 5 日宽度趋势既能表格化又能可视化。
- 5 个指数与广度的同向 / 背离一眼可见。
- 后端计算稳定可重复（同样输入永远同样输出），与文档复盘卡双轨并行不冲突。
- 数据不足时不形成虚假判断，所有派生字段为可空。

**Non-Goals:**
- 不修改 `QTS-01-02-01..05` 的规则 ID、阈值、权重。
- 不引入新 provider、新 API 路由、新数据库 schema、新采集任务。
- 不允许用户在前端覆写宽度标签。
- 不导出 CSV / 截图（保持范围最小）。
- 不动 PostgreSQL 表结构、迁移、Helm/TrueNAS 部署清单。

## Decisions

### D1. 后端一次成型，前端不再做派生计算
**理由**：仓库对确定性评估有硬要求；前端做分位 / 动量会引入浮点漂移、时区与窗口不一致风险。所有派生字段（`declineRatio`、`advanceDeclineSpread`、3 个 250 日分位、`momentum` / `momentumPercentile`、`indexConsistent`、`widthLabel` / `widthLabelReason`、`history`、`percentile250` 覆盖信息）在 `_breadth_result` 内部一次性填充。
**备选**：前端独立调用 `metric.band` evaluator — 拒绝，会让看板与交易系统执行路径分叉。

### D2. 历史来源固定为 PostgreSQL `snapshot_store.get("breadth", date)`
**理由**：`service.py` 第 249 行已经在用同一调用读取 breadth 快照，并已在 SQLAlchemy 持久层下；复用即获得跨连接 lease / fencing / stale-while-revalidate / 同日期 fallback 全部好处，不引入新依赖。
**备选**：临时直接 HTTP 拉东方财富 — 拒绝，会绕过 snapshot 缓存与缓存质量元数据。

### D3. 250 日分位采用复用 `_metric_percentile`，不做窗口配置化
**理由**：量化版固定 250 日窗口、最少 60 个观察，与 `calculations._metric_percentile` 默认参数一致；不动签名就减少测试面。
**备选**：在 breadth 上下文里加 `_breadth_percentile` 专门函数 — 拒绝，等出现真差异时再做。

### D4. 5 日动量公式 = `mean(advanceRatio[t-2..t]) - mean(advanceRatio[t-5..t-3])`
**理由**：与量化版 `02.上涨家数…md` 中 `QTS-01-02-04` 公式字段 `mean(advanceRatio,3)-mean(advanceRatio.shift(3),3)` 一字一致；窗口 6 日、覆盖前后各 3 日。
**备选**：用文档第 114 行"连续 3 天上涨家数增加 + 中位数由负转正"的弱判定 — 拒绝，弱判定无法形成标量得分；改在 `widthLabelReason` 中以文字形式补充提示。

### D5. 指数广度一致性 = "5 个指数中 sign(changePct) == sign(medianReturn) 占多数"
**理由**：与文档第 99-108 行"指数强个股弱 / 指数弱个股修复"的判定基础一致；过半数同向 = 一致，否则不一致。
**备选**：要求 5/5 一致才 true — 拒绝，对单日复盘过严。

### D6. 6 档宽度标签
- 数据不足 → `数据不足`（任何关键字段为 null 时）
- 多数指数上涨 + 上涨占比 < 40% 或中位数 < 0 → `指数强个股弱`
- 多数指数下跌 + 上涨占比 ≥ 50% + 中位数 ≥ 0 → `指数弱个股修复`
- 指数方向与中位数同向 + 较前一日共同改善（advanceRatioDelta ≥ 0 且 medianReturnDelta ≥ 0） → `同向增强`
- 同向 + 共同恶化 → `同向走弱`
- 其余 → `混合`

`widthLabelReason` 用一句话自然语言说明依据（例如"上涨占比 67% 与中位数 +0.84% 同为正且较前一日改善"）。
**备选**：仅用 3 档"多数上涨/下跌/涨跌分化" — 拒绝，是当前现状。

### D7. 前端新增独立 ECharts 实例 `breadthChart`
**理由**：与现有 `chart`（指数 K 线）与 `volumeChart`（指数成交量）数据源不同、生命周期不同（随 02 页进入才需要、离开 dispose）。复用同一 import `echarts` 但不共享变量与 `disposeCharts()`。
**备选**：复用 `chart` 实例 — 拒绝，会被 `watch(selectedIndex, ...)` 触发重新渲染而互相覆盖。

### D8. 02 页 5 section 视觉全部沿用现有 token
- 复盘卡用 `metric-grid four`（已有 class），新增 `metric-grid six` 与 `metric-grid three` 两个 class，沿用 `panel-heading` / `panel-kicker`。
- 量化证据表沿用 `limits-table` 的列结构与字号。
- 5 日趋势表沿用 `history-table`。
- 指数 × 广度矩阵用新的 `breadth-consistency-table`，视觉与 `combination-matrix` 同级。
- 验证项面板沿用 `limits-quality-band`。
- 不新增颜色、不改字号、不改 spacing；如确需新增 class 才动 `styles.css`，并在 PR 描述列清单。

### D9. 测试矩阵
- `calculations`：动量公式（t-2..t 与 t-5..t-3 均值差）、分位最小 60 观察的 `insufficient` 边界。
- `providers`：6 档宽度标签各场景（最少 6 个测试）、新字段填充完整性、缺失数据时整体为 `数据不足`。
- `service`：第 02 页章节契约 JSON 含全部新字段、缺失快照时 `history` 为空数组而不报错。
- 前端 Vitest：02 页 snapshot 覆盖 5 section 渲染、宽度标签 color-tone、5 日趋势表列、`copy` 验证项功能。

### D10. 视觉语言不破 14px / 390px 边界
- 全部新增文字 ≥ 14px；移动端 390px 宽表自身滚动（沿用现有 `.table-scroll` 即可）；不出现页面级横向溢出。

## Risks / Trade-offs

- **[R1] 宽度标签与用户主观判断存在偏差** → 初版在 `widthLabelReason` 中暴露派生依据；不在前端做用户覆写；后续若偏差稳定，再考虑引入可编辑字段。
- **[R2] 250 日分位在前期历史数据不足时全部 `insufficient`** → 复用现有 `_metric_percentile` 的 `confidence` 字段（`high` / `medium` / `insufficient`），前端如实显示，不补 0。
- **[R3] PostgreSQL 旧日 breadth 快照可能不全** → `history` 缺位时仅显示已有日；表格行数 = 实际有数据的天数；图表 X 轴相应缩短；不补假数据。
- **[R4] 5 个指数若当日某个指数缺失 changePct** → `indexConsistent` 用已有指数数判定，过半数仍可形成 boolean；缺失指数在矩阵中显示 `--` 与 `数据不足`。
- **[R5] ECharts bundle 体积** → 不引入新依赖，使用现有 `echarts` 包的 line + bar（已用）；体积影响零。
- **[R6] 前端测覆盖 02 页 5 section 渲染较重** → 现有 `app.test.ts` 与 `data-collection-view.test.ts` 已用 Vitest + Vue Test Utils，复用同一套工具即可。

## Migration Plan

- 后端：仅扩展 schema 字段与 provider 计算；旧调用方因字段为可空，向后兼容。
- 前端：02 页模板一次性替换；其它页面（01、03、05、06、08、09）只读 `breadth` 的旧 7 字段或新 11 字段都能渲染，不破坏。
- 部署：无需新 Helm values、无需新 CronJob、无需新 PVC；图像 tag 不变。
- 回滚：单 commit revert 即可；旧 `_breadth_result` 与前端 4 卡页面可直接回滚到上一版本。

## Open Questions

- (无) — 上一轮探索已与用户对齐 7 项决策：复用 PostgreSQL 快照历史源、固定 5 个指数、列顺序与 01 页对齐、宽度标签不允许前端覆写、表格同时给量化数字 + 文字同向提示、验证项只读 + 一键复制、复用现有 color token。