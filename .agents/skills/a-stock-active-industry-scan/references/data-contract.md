# 数据契约

本 Skill 的唯一数据来源是新浪行情接口与 `hithink-finance`（fuyao）。全部结果落临时 JSON 与 Markdown，不写数据库、不新增 API。

## 1. 双榜

| 榜 | 接口 | 排序键 | 取数 | 实测 |
|---|---|---|---|---|
| 成交额榜 | `Market_Center.getHQNodeData` | `sort=amount&asc=0` | 400 只候选池（4 页 × 100，8 并发） | 0.59s |
| 换手率榜 | 同上 | `sort=turnoverratio&asc=0` | 同上 | 0.58s |

- `node=hs_a` 覆盖全市场 5579 只；`num` 上限 100。
- 服务端排序意味着第 3 页无需读第 1–2 页，页间可并发。
- 候选池必须大于输出条数：上市不足 250 日的过滤会剔除若干只，先取 50 再删会导致榜单不足额。

**降级路径**：两个排序请求都失败时，拉取全量 56–80 页后本地重排（实测 2.76s / 5579 只），质量状态记 `degraded`。

### 榜单接口没有历史回溯能力

`getHQNodeData` 只返回**调用时刻**的累计快照，接口没有 `--as-of` 参数。这意味着：

- 真实盘中（如 10:30）调用 → 拿到 09:30–10:30 的累计成交，排名有效。
- 收盘后（≥ 15:00）调用 → 拿到全天数据，此时传任何 `--now` 都只改变**时点标签**，不改变数据本身。
- 收盘后无法还原「10:30 那一刻的榜单」。

因此 `--now` 参数**仅用于测试与复现**，不是历史回溯开关。用它把收盘后的一次运行标成 `intraday` 会得到一份「标签是盘中、数据是收盘」的产物，这类产物不应作为盘中判断依据。

盘中的有效性已由横截面证据支持（10:30 与收盘的 Top50 重合 43/50，见 `metric-definitions.md` 第 8 节），但那是离线比对的结果，**不是本 Skill 能事后重放的能力**。

## 2. 新股过滤

| 项 | 口径 |
|---|---|
| 数据源 | `hithink-finance symbol list --exchange SH,SZ,BJ --limit 10000` |
| 覆盖 | 5584 只，5580 只有 `list_date` |
| 耗时 | 0.48s；按日缓存后 0.03s |
| 阈值 | `--min-listing-days`，默认 250 |

- 过滤发生在截断到 Top-N **之前**。
- 缺失 `list_date` 的股票被排除，计入 `excluded.missingListDate`，不假设其上市时间足够长。
- 被剔除项输出 `rankIfUnfiltered`，即「若不过滤会排第几」。
- 2026-11-19 实测：换手率榜剔除 9 只，成交额榜剔除 2 只，两者过滤后仍满 50 条。
- **`list_date` 整体缺失时 fail-open**：若接口返回的行全部没有 `list_date`（2026-11-20 上游回归：5584 行全为 `null`），说明是上游字段缺失而非「这些股票都没有上市日期」。此时跳过过滤、不剔除任何股票，记 `degraded` 并在 `quality.degradations` 写明「上市日期字段整体缺失」。若只有部分行缺失，仍按缺失处理（剔除并计入 `missingListDate`）。

## 3. 行业成分股

| 项 | 口径 |
|---|---|
| 数据源 | `hithink-finance index catalog --tag industry` + `index constituents --thscode` |
| 层级 | 一级 `881*`（90 个），二级 `884*`（230 个） |
| 耗时 | 一级 5.75s（6 并发）；两级 20.16s |
| 缓存 | `.cache/active-industry-scan/industry/level{N}-{YYYY-MM-DD}.json`，按日 |

**限制**：成分股接口只返回当前快照，没有 `--as-of`。历史某一日的行业归属无法还原。本 Skill 不做历史对比，因此影响有限；但若当日发生行业调整，当日结果与昨日结果不可直接相减。

**缓存策略**：优先读当日文件；缺失时回退到最近的旧文件并在输出中标注 `industryMembershipDate`，质量状态记 `degraded`；完全无缓存且接口失败时行业段标记 `insufficient`，榜单与交集仍照常输出。

## 4. 方向取数

方向层需要两类数据，都与上述双榜/成分股独立，失败不影响它们。

### 板块指数涨跌幅

| 项 | 口径 |
|---|---|
| 命令 | `hithink-finance index snapshot` |
| 输入 | 当次已加载的**全部**板块 `thscode`（一级 90 个或两级 320 个） |
| 输出 | `{thscode: price_change_ratio_pct}` |
| 耗时 | 90 个 0.36s；230 个 0.58s（单次调用覆盖全部，不逐板块请求） |
| 失败 | `boardChangePct` / `boardDirection` 为 `null`，记 `degraded` |

单次批量调用而不是循环，是因为逐个板块请求会退化成 90 次网络往返；实测单次调用已能覆盖两级全部板块。

### 全市场涨跌幅

| 项 | 口径 |
|---|---|
| 命令 | `hithink-finance market snapshot --limit 1000 --offset N` |
| 分页 | 每页 1000，全市场约 5584 只 → 6 页 |
| 并发 | 6 页并发，实测 0.4–0.7s |
| 字段 | `price_change_ratio_pct`（涨跌幅）、`volume`（判断是否停牌）、`total`（声明总数） |
| 失败兜底 | 改用新浪全量快照（`fetch_full_snapshot`，约 2.7s），`source` 记 `sina-full-snapshot` |
| 双失败 | `source = "unavailable"`，`direction.market.status = "insufficient"`，相对方向与宽度为 `null` |

- 分页按 `thscode` 去重：页边界上的重复记录只保留一条。
- `total` 与 `len(changes)` 分开保存。分页部分成功时 `coverage` 会如实下降，而不是看起来像「全市场就这么几只」。
- 兜底用新浪快照是**同一时点、同一口径**（个股相对前收的涨跌幅），因此是等价替代而不是换了个指标；代价是慢约 2.7s，所以只在 fuyao 失败时使用。

### 方向层的降级矩阵

| 板块指数 | 全市场快照 | 结果 |
|---|---|---|
| ok | ok | 三类证据齐全，相对方向可用 |
| fail | ok | 行业方向退到成员中位，上榜与宽度仍在；`degraded` |
| ok | fail | 板块涨跌与上榜方向可用，相对方向与宽度为 `null`；`degraded`（先尝试新浪兜底） |
| fail | fail | 全部方向字段退到绝对 `changePct`，相对字段为 `null`；`degraded` / `insufficient` |

任何一格都不会以退出码 2 结束——方向层失败不构成「无法产出结果」，双榜与交集仍是完整结论。

## 5. 分时 K 线

| 项 | 口径 |
|---|---|
| 接口 | `CN_MarketDataService.getKLineData`，`scale=5` |
| 时间戳 | 按 bar **结束**时刻标注：首根 09:35，末根 15:00 |
| 午休 | 11:30 → 13:05，间隔 95 分钟 |
| 当日 | 48 根 |
| 耗时 | 96 只 / 并发 12 / 1.25s |

- 时间过滤用 `bar_time <= now`，10:30 恰好保留 12 根（09:35–10:30）。
- 单只失败有 2 次有界重试；仍失败则进入 `missing_bars`，并记 `degraded`。缺失列表必须暴露，否则限流会伪装成「大量股票没有成交」。

## 6. 时点状态机

| 时段 | `sessionState` | 分位可用 | 方向含义 |
|---|---|---|---|
| < 09:30 | `preopen` | 否 | **前一交易日**涨跌幅，非当日 |
| 09:30–11:30 | `intraday` | 否 | 当前时点相对前收 |
| 11:30–13:00 | `lunch` | 否 | 上午收盘时点 |
| 13:00–15:00 | `intraday` | 否 | 当前时点相对前收 |
| 15:00–15:10 | `settling` | 否 | 当日收盘 |
| ≥ 15:10 | `closed` | 是 | 当日收盘 |

复用仓库既有环境变量：`MARKET_ENVIRONMENT_OPEN_TIME`（默认 `09:30`）、`MARKET_ENVIRONMENT_SETTLEMENT_TIME`（默认 `15:10`）。

`elapsedBars ≤ 3` 时输出早期快照提示。

`preopen` 的方向必须靠 `direction.basisNote` 明确标注为前一交易日：此时当日还没有成交，`changePct` 只可能是前收相对前一交易日的变化，把它当作当日方向会得出完全错误的结论。

## 7. 质量状态

| 状态 | 含义 | 典型触发 |
|---|---|---|
| `ok` | 全部数据源正常 | — |
| `degraded` | 有源失败但结论仍可用 | 单榜失败、分时缺失、旧缓存、上市日期缺失、板块指数或全市场快照失败 |
| `insufficient` | 某段完全缺失，结论不完整 | 行业段无缓存且接口失败、全量快照也失败 |

`insufficient` 覆盖 `degraded`（更严重者优先）。**任何单源失败都不会让整个运行失败**；只有两个榜都无数据时以退出码 2 结束，且不输出看似成功的结果。

## 8. 凭据

解析顺序与 `qts04-core` 一致：

```
FUYAO_API_KEY  →  MARKET_ENVIRONMENT_FUYAO_API_KEY  →  deploy/truenas/deploy.env 中的 FUYAO_API_KEY
```

- 凭据通过子进程环境变量传递，**不出现在命令行参数**，因此不会留在 shell 历史或进程列表。
- 只读取目标键，不读取、不回显同文件的其他变量。
- 输出中的 `credentialSource` 只记录来源标签（如 `env:FUYAO_API_KEY`），从不记录值。

## 9. 缓存目录

```
.agents/skills/a-stock-active-industry-scan/.cache/active-industry-scan/
├── industry/level1-{date}.json
├── industry/level2-{date}.json
└── history/{date}.jsonl          # 当日每次扫描的轨迹投影（目录即 store 根）
```

`.cache/` 已加入该 Skill 的 `.gitignore`。缓存可随时删除重建，不写入数据库。

`history/{date}.jsonl` 每行是一次扫描的**投影**（不含双榜明细），用于渲染变化轨迹：

- 追加写入，`reportId` 相同则覆盖该行，避免重试被当成第二次扫描。
- 同一交易日最多保留 40 行，渲染取最近 12 行。
- fixture 模式默认不写（除非显式 `--history-dir`），否则一次离线回放会变成下一次实时扫描的基线。
- 删除该目录只会让下一次扫描显示「首次记录」，不影响任何计算。
## 10. 会话回复格式

JSON 是数据事实源，`--answer` 文件是**展示事实源**。两者都由同一次运行产出，但职责不同：

| 产物 | 谁决定 | 是否允许会话说算 |
|---|---|---|
| JSON（`--output`） | 计算管线 | 否 |
| Markdown 报告（`--markdown`） | `report.render()` | 否 |
| 会话回复（`--answer`） | `report.render_answer()` | **否，逐字复制** |

### 为什么盘中结果不同但格式必须相同

新浪排序接口与 fuyao 成分股只返回**调用时刻**的快照，没有 `--as-of` 回溯能力（见第 1、3 节）。因此相隔十分钟的两次运行，数字必然不同；这不是缺陷，是数据口径本身。但以下内容与时间无关，必须逐字节稳定：

- 标题恒为 `# 最活跃的行业`
- 结论块恒为 5 行：时点 / 全市场 / 最活跃行业 Top3 / 方向分组计数 / 双榜交集
- 正文段落名、顺序、表格列与列序恒定
- 涨跌类字段带 `+`/`-` 符号；换手率等比率不带符号；缺失为 `—`

Top3 由 `hitCount` 降序、再按成交额榜命中、换手榜命中、代码排序决定，**不继承行业表的排序**，因此上游排序调整不会改写结论句。

### 一次运行的三件产物

```bash
python3 scripts/scan_pipeline.py --output /tmp/scan.json --markdown /tmp/scan.md --answer /tmp/answer.md
```

`--answer` 与 `--markdown` 都只读 JSON、不做任何重算，所以两者不能互相矛盾。同一份 JSON 重复渲染结果完全相同（`report.render_answer()` 是纯函数）。

### 复现边界

- **能复现**：拿到同一份 JSON 后，任何会话重跑 `report.render_answer(document)` 得到同一段文字。
- **不能复现**：没有 JSON 时无法依据 `reportId`、时间戳或口头描述复原当次盘中数字；本轮不提供快照留存，也不假装可以回放。

### 变化轨迹的数据来源

`## 四、扫描变化轨迹` 只读 `history/` 里**已经发生过的运行**，不额外请求任何接口：

| 场景 | 行为 |
|---|---|
| 当日第一次运行 | 打印「本次为当日首次记录：暂无对比基线」，段落照常出现 |
| 后续运行 | 每行一次扫描，最后一行为本次；「关键变化」与上一行对比 |
| history 目录被删除 | 退化为「首次记录」，不报错、不降级计算 |
| `--no-history-store` | 不读不写，同样渲染「首次记录」 |

阈值：全市场中位 ±0.50pp、上涨家数 ±5%、行业成交额榜命中 ±2、换手榜下跌家数 ±2、交集增删、候选行业增删。都不触发时明确写「未触发任何阈值」，而不是留空。
