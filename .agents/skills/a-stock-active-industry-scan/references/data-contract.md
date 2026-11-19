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

## 3. 行业成分股

| 项 | 口径 |
|---|---|
| 数据源 | `hithink-finance index catalog --tag industry` + `index constituents --thscode` |
| 层级 | 一级 `881*`（90 个），二级 `884*`（230 个） |
| 耗时 | 一级 5.75s（6 并发）；两级 20.16s |
| 缓存 | `.cache/active-industry-scan/industry/level{N}-{YYYY-MM-DD}.json`，按日 |

**限制**：成分股接口只返回当前快照，没有 `--as-of`。历史某一日的行业归属无法还原。本 Skill 不做历史对比，因此影响有限；但若当日发生行业调整，当日结果与昨日结果不可直接相减。

**缓存策略**：优先读当日文件；缺失时回退到最近的旧文件并在输出中标注 `industryMembershipDate`，质量状态记 `degraded`；完全无缓存且接口失败时行业段标记 `insufficient`，榜单与交集仍照常输出。

## 4. 分时 K 线

| 项 | 口径 |
|---|---|
| 接口 | `CN_MarketDataService.getKLineData`，`scale=5` |
| 时间戳 | 按 bar **结束**时刻标注：首根 09:35，末根 15:00 |
| 午休 | 11:30 → 13:05，间隔 95 分钟 |
| 当日 | 48 根 |
| 耗时 | 96 只 / 并发 12 / 1.25s |

- 时间过滤用 `bar_time <= now`，10:30 恰好保留 12 根（09:35–10:30）。
- 单只失败有 2 次有界重试；仍失败则进入 `missing_bars`，并记 `degraded`。缺失列表必须暴露，否则限流会伪装成「大量股票没有成交」。

## 5. 时点状态机

| 时段 | `sessionState` | 分位可用 |
|---|---|---|
| < 09:30 | `preopen` | 否 |
| 09:30–11:30 | `intraday` | 否 |
| 11:30–13:00 | `lunch` | 否 |
| 13:00–15:00 | `intraday` | 否 |
| 15:00–15:10 | `settling` | 否 |
| ≥ 15:10 | `closed` | 是 |

复用仓库既有环境变量：`MARKET_ENVIRONMENT_OPEN_TIME`（默认 `09:30`）、`MARKET_ENVIRONMENT_SETTLEMENT_TIME`（默认 `15:10`）。

`elapsedBars ≤ 3` 时输出早期快照提示。

## 6. 质量状态

| 状态 | 含义 | 典型触发 |
|---|---|---|
| `ok` | 全部数据源正常 | — |
| `degraded` | 有源失败但结论仍可用 | 单榜失败、分时缺失、旧缓存、上市日期缺失 |
| `insufficient` | 某段完全缺失，结论不完整 | 行业段无缓存且接口失败、全量快照也失败 |

`insufficient` 覆盖 `degraded`（更严重者优先）。**任何单源失败都不会让整个运行失败**；只有两个榜都无数据时以退出码 2 结束，且不输出看似成功的结果。

## 7. 凭据

解析顺序与 `qts04-core` 一致：

```
FUYAO_API_KEY  →  MARKET_ENVIRONMENT_FUYAO_API_KEY  →  deploy/truenas/deploy.env 中的 FUYAO_API_KEY
```

- 凭据通过子进程环境变量传递，**不出现在命令行参数**，因此不会留在 shell 历史或进程列表。
- 只读取目标键，不读取、不回显同文件的其他变量。
- 输出中的 `credentialSource` 只记录来源标签（如 `env:FUYAO_API_KEY`），从不记录值。

## 8. 缓存目录

```
.agents/skills/a-stock-active-industry-scan/.cache/active-industry-scan/
├── industry/level1-{date}.json
└── industry/level2-{date}.json
```

`.cache/` 已加入该 Skill 的 `.gitignore`。缓存可随时删除重建，不写入数据库。