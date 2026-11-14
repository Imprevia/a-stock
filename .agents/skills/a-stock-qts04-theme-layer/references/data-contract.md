# STEP 2 数据合同

本文件记录 `theme_pipeline.py` 实际调用的 fuyao 命令、字段、窗口与降级语义。JSON 是唯一事实源；字段名变更必须同步 `theming.py`、`theme_report.py`、`theme_check_report.py` 与测试。

## 1. 命令与用途

| 命令 | 用途 | 关键参数 | 降级 |
|---|---|---|---|
| `index catalog --tag cn_concept` | 概念目录（390 条） | `--format json` | 空目录 → `insufficient` |
| `index constituents --thscode CODE` | 概念当前成分股 | 单代码 | 空/失败 → 该概念跳过并告警 |
| `index snapshot --thscodes ...` | 概念最新快照 | 每批 200 个代码 | 历史日期不可用 → 候选生成只用原因词 |
| `index history-batch --thscodes ...` | 概念/基准日线 | 每批 10 个代码，5 年窗口 | 单代码失败 → 该概念指标缺失 |
| `special limit-up-pool --date-ms ...` | 当日涨停池 | `--size 200` 翻页至 `pagination.total` | 空池 → `insufficient` |
| `special limit-up-statistics --date ...` | 涨停统计 | 单日 | 失败 → 空对象 + 告警 |
| `news anomaly-analysis --begin-date --end-date` | 异动解读 | 单日 | 失败 → 空列表 + 告警 |
| `market calendar` | 交易日校验 | 无 | 失败 → 无法证明非交易日，继续并在 `quality.warnings` 记录 |
| `stock history-batch` | 成员涨跌样本 | 每批 10 只，45 天 | 失败 → 该批成员宽度缺失 |

所有命令都通过 `qts04-core` 的 `FuyaoClient` 调用：凭据只进子进程环境，不落 argv；限流按指数退避重试；错误码写进 `FuyaoDegraded`。

## 2. 数据窗口

| 数据 | 实际窗口 | 备注 |
|---|---|---|
| 概念日线 | 5 年（按需缓存） | 新概念可能只有 1—2 年 |
| 个股日线 | 45 天（成员涨跌） | 只取目标日前两日即可算涨跌 |
| 涨停池 | 约 12.5 个月 | 2025-10-31 起可用；更早日期 `FUYAO_1002` |
| 涨停统计 | 1 年 | 与涨停池同日 |
| 异动解读 | ≥2 年 | 文本自带“AI 技术搜集公开信息总结生成” |
| 概念快照 | 仅最新 | 无日期参数，历史日期不能回填 |
| 概念成分股 | 仅当前 | 没有历史成员接口，`pointInTime=false` |
| 市场日历 | 约 1 年（242 个交易日） | 历史校验受窗口限制 |

## 3. 缓存布局

根目录默认 `.agents/skills/a-stock-qts04-theme-layer/.cache/qts04/`，全部可重建、不提交：

```
catalog.json                         # 概念目录
snapshots/2026-11-13.json            # 当日概念快照
limit-up/2026-11-13.json             # 当日涨停池
limit-up-stats/2026-11-13.json       # 当日涨停统计
anomalies/2026-11-13.json            # 当日异动解读
constituents/886060.TI.json          # 当前成分股（按概念）
bars/concept/886060.TI.json          # 概念日线
bars/stock/000101.SZ.json            # 成员日线
bars/benchmark/000001.SH.json        # 基准日线
point-in-time/2026-11-13.json        # 当题题材快照（确定性）
```

`--refresh` 只禁用读取，不删除已有缓存；删除缓存只增加取数时间，不影响结果口径。

## 4. JSON 合同

| 字段 | 类型 | 说明 |
|---|---|---|
| `schemaVersion` | string | 当前 `1.0`；消费方必须校验 |
| `step` | string | 固定 `STEP 2` |
| `reportId` | string | 16 位 SHA-256；对 `{schemaVersion,step,asOf,config,input,themes}` 取规范化 JSON |
| `asOf` | string | 目标交易日 `YYYY-MM-DD` |
| `config` | object | 权重、lift 闸门、分级闸门、窗口、停用表、市场股票数 |
| `input` | object | 目录数、涨停数、异动条数、市场股票数、STEP 1 摘要 |
| `status` | string | `ok` / `degraded` / `insufficient` |
| `quality` | object | 数据窗口、`pointInTime`、`backtestGrade`、成员缺口、告警、调用次数 |
| `catalystPolicy` | object | `confirmedAvailable=false` 与原因 |
| `noCoreTheme` | boolean | 当日是否有核心题材 |
| `noCoreReasons` | array | 空结果原因枚举；有核心时为空 |
| `themes` | array | 题材条目，按 tier/分数/lift 排序 |
| `unmappedTokens` | array | 未映射到任何概念名的原因词（最多 20 条） |
| `disclaimer` | string | 免责声明 |
| `calibration` | string | 固定 `needs-backtest` |

`themes[]` 关键字段：`themeId`、`name`、`concept{thscode,name,memberCount,barsObservations,barsStart,barsEnd}`、`direction`、`tier`、`tierReasons`、`score`、`confidence`、`status`、`lift`、`observed`、`expected`、`metrics[]`、`catalyst{label,primaryToken,sources,reason,confirmedAvailable}`、`members{codes,sampled,membershipGap,limitUp,sharedTokens}`、`confirmation`、`invalidation`、`calibration`。

## 5. 状态与降级

- `ok`：目录、涨停池、基准日线齐全；无告警。
- `degraded`：有题材，但存在缓存未命中、成分股/成员日线失败、涨停统计口径差或历史快照缺失。
- `insufficient`：目录为空、涨停池为空、基准日线缺失、目标日无概念日线、或全部题材指标覆盖率 <50%。

失败时仍写出结构化 JSON：`status=insufficient`、`themes=[]`、`quality.warnings` 说明原因；不得用相邻日期或 0 补齐。

## 6. 目标日校验

1. `--as-of` 必须是合法 `YYYY-MM-DD`。
2. 未来日期拒绝。
3. 当日 15:10 前拒绝（统一按 `Asia/Shanghai`）。
4. 实时模式用 `market calendar` 校验交易日；fixture 模式用 `tradingDays`。
5. 历史日期不拉概念快照；候选生成退化为“涨停原因词匹配”，并在 `quality.candidateBasis` 记录。

## 7. 退出码

- `theme_pipeline.py`：`0` = `ok`/`degraded`；`1` = `insufficient`；`2` = 输入/参数错误。
- `theme_check_report.py`：`0` = `PASS`；`1` = `FAIL`；`2` = `ERROR`。
