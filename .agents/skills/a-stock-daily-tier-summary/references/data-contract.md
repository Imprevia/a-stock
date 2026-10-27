# 每日分层总结数据合同

## 日期与相邻交易日

- 时区固定为 `Asia/Shanghai`，日频数据只在目标交易日完成收盘后使用。
- “今天”指上海日历今天；“昨天”指上海日历昨天。若字面日期休市，必须说明休市，并由可信交易日历解析到最近已完成交易日。
- 当前与上一交易日都必须有独立的精确日期证据。禁止用最新响应填补历史日期，禁止把请求参数日期改写为 payload 日期。
- 本地 v2 响应的 `asOf` 必须等于请求日期；每个日期先固定首个响应的 `snapshotRevision`，该日期所有 pool 后续页都携带同一 `revision`。两个日期可以有不同 revision。
- 外部降级分别记录请求参数日期与响应 `qdate`/顶层日期。显式响应日期与请求矛盾时该 session 为 `insufficient`；只有请求参数日期而无独立响应日期时最高为 `degraded`。

## 输入形状

脚本 fixture 模式接受以下顶层结构：

```json
{
  "request": {
    "relative": "today",
    "now": "2026-10-23T16:00:00+08:00",
    "tradingSessions": ["2026-10-22", "2026-10-23"]
  },
  "sessions": {
    "2026-10-22": {"requestedDate": "2026-10-22", "actualDate": "2026-10-22", "source": "fixture", "revision": "r1", "quality": {"status": "ok"}, "pools": {}},
    "2026-10-23": {"requestedDate": "2026-10-23", "actualDate": "2026-10-23", "previousSession": "2026-10-22", "source": "fixture", "revision": "r2", "quality": {"status": "ok"}, "pools": {}}
  },
  "previousPlan": null
}
```

`pools` 的键为 `limit_up`、`failed_limit_up`、`limit_down`。每池包含 `rows`、可选 `total` 和 `quality`。fixture 只用于合成或调用者提供的数据，不得把真实运行时快照加入仓库。

联合复盘 fixture 可在顶层增加 `marketEnvironment`：

```json
{
  "marketEnvironment": {
    "asOf": "2026-10-23",
    "revision": "synthetic-current-revision",
    "quality": {"status": "ok", "warnings": []},
    "summary": {"synchronizationAssessment": {}},
    "indices": [],
    "breadth": {}
  }
}
```

`marketEnvironment.asOf` 必须等于当前 `sessions` 日期，revision 必须与当前 session revision 相同；显式不一致时整个联合复盘 fail closed。缺少 `marketEnvironment` 的旧 fixture 仍可计算分层事实，但环境区块和环境验证必须为 `insufficient`，不得从 limits 推断指数环境。

## 证券身份与字段优先级

- 唯一身份为规范交易所 `SH`、`SZ` 或 `BJ` 加六位代码，例如 `SH:600000`。
- 支持将 `SSE/XSHG/1` 归一为 `SH`，`SZSE/XSHE/0` 归一为 `SZ`，`BSE` 归一为 `BJ`。来源未给交易所时，只能按明确 A 股代码规则确定性推导；无法确定时拒绝该行。
- 同一池内同身份、同规范字段的重复行折叠一次并写 warning。同身份但名称、连续板数或身份字段冲突时拒绝该池，不使用输入顺序决胜。
- 本地来源的连续板数只读 `streak_days`/`streakDays`。东方财富来源只读 `lbc`。两者都必须是大于等于 1 的整数。
- `zttj.days` 和 `zttj.ct` 是区间涨停模式信息，不是连续板数。即使 `zttj.days=8`，只要 `lbc=2`，仍归中位。
- 缺连续板字段的涨停成员保留在涨停池总数中，但排除出高/中/低位计数，并降低 tier 质量。

## 质量传播

质量从好到坏按 `ok -> degraded/partial -> insufficient` 传播。以下情况至少降级：

- 精确重复行已折叠；
- 外部证据只有请求日期；
- 个别涨停成员缺连续板数；
- 某层样本为空或某池为 partial。

以下情况必须 `insufficient`：

- 实际日期与请求日期显式冲突；
- cursor 页 revision 改变；
- 同身份冲突行；
- 所需 pool 缺失或读取失败；
- 当前 session 的上一交易日与给定上一 session 不一致。

局部缺失不得污染证据完整的其他层，但依赖缺失 pool 的跨日结论必须标记不足。

## 可空分母

- 分层继续率、炸板率、跌停率的分母是上一交易日该层冻结样本数。分母为 0 时比率为 `null`。
- 失败样本修复分母是上一交易日完整炸板池的规范身份数。分母为 0 时 `ratio=null` 且 `status=insufficient`。
- 不得把 `null` 格式化为 `0` 或 `0%`；输出“样本为 0，修复率不足”。

## 本地 v2 读取边界

读取路径：

- `GET /api/v2/market-environment/{date}/overview`
- `GET /api/v2/market-environment/{date}/indices`
- `GET /api/v2/market-environment/{date}/breadth`
- `GET /api/v2/market-environment/{date}/limits`
- `GET /api/v2/market-environment/{date}/limits/pools/limit_up`
- `GET /api/v2/market-environment/{date}/limits/pools/failed_limit_up`
- `GET /api/v2/market-environment/{date}/limits/pools/limit_down`

当前交易日先读 `overview` 并固定其 `snapshotRevision`，随后 `indices`、`breadth`、`limits` 和全部 pool 页都携带该 revision。上一交易日先读自己的 `limits` 并固定自己的 revision。每个响应的 `asOf` 必须等于请求日期，revision 必须等于该日期已固定的值；HTTP 409、日期冲突或 revision 改变时拒绝整次组合读取。

分页参数为 `limit=100`、`cursor` 和固定的 `revision`。不调用 POST/PUT/PATCH/DELETE，不调用 collection、refresh、backfill、operation 或 provider route。

## 市场环境字段

- 五指数身份固定为上证指数、深证成指、创业板指、沪深300和中证500；规范身份重复、缺少预期指数或出现未知替代行时保留具体缺口，不用另一指数代替。
- 方向使用 `changePct`：正数上涨、负数下跌、零平盘；缺失时进入数据不足组。
- MA20 位置使用同一指数行的 `close` 与 `movingAverages.ma20`；`close >= ma20` 为上方，否则为下方，任一缺失时不可计算。
- 宽度事实来自 v2 breadth 的 `advanceRatio`、`medianReturn`、`widthLabel`、`widthLabelReason` 和 `indexConsistent`。
- 五指数成交额中位数、放量上涨/下跌计数优先使用规范 assessment/market evidence，并与指数行的 `amountRatio5`、`changePct` 和 `volumePriceState` 交叉检查。
- `summary.synchronizationAssessment` 是环境模式、结论和置信度的首选规范输入；`marketEvidence` 是数值汇总，不得以其中单个空字段覆盖有效 assessment 或原始指数事实。
