## Context

行业采集目前由 `MarketDataProvider` 调用东方财富 `push2` 和
`push2delay`，两者均失败时由 collection coordinator 记录
`failed-retained` 或 `failed-missing`。仓库已经有按数据集的扶摇开关、capability
report、shadow 对账和同日期快照保留机制，但扶摇行业适配器使用的
`/api/a-share/industry/ranking` 并不是当前公开接口。

扶摇公开接口将行业能力拆成同花顺行业指数目录、指数行情快照和交易日历：

```
calendar/trading-days
          |
          v
catalog/ths-index-list(tag=industry) --> prices/snapshot(thscodes=...)
                                                |
                                                v
                                      stable top-10 sector rows
```

探针已证明该组合可返回行业代码、名称、涨跌幅和成交额，但不返回主力净流入、
上涨/下跌家数或领涨股。因此这些字段必须按现有 API 结构保留为 `null`，结果
只能作为有明确降级说明的 fallback 证据。

## Goals / Non-Goals

**Goals:**

- 在东方财富双端点失败后，引入经过 capability revision 门禁的扶摇同花顺行业指数 fallback。
- 证明请求日期属于上海交易日，并将目录、快照时间戳和交易日历绑定到同一日期。
- 保持 `SectorRow` 兼容；对扶摇不提供的字段使用 `null` 和可审计 warning。
- 保留东方财富前序失败、扶摇来源/版本、字段缺失和失败留存信息。
- 让核心响应日期归一后，前端 lazy `sectors` 请求使用有效交易日。

**Non-Goals:**

- 不把扶摇行业指数当作东方财富行业资金流、板块宽度或领涨股事实的等价替代。
- 不通过 320 个行业成分股逐一请求来派生上涨/下跌家数或领涨股。
- 不扩展 TDX 行业映射，不改写 `SectorRow` 字段，不新增数据库表或公开 API 路由。
- 不在 PR 测试中访问真实 provider，不自动打开生产开关，不执行生产采集或快照回填。

## Decisions

### 1. Use the documented THS index API rather than the guessed ranking endpoint

新增/重写扶摇 sectors adapter，使用：

- `GET /api/a-share/calendar/trading-days` 获取近一年交易日证据；
- `GET /api/a-share-index/catalog/ths-index-list?tag=industry` 获取行业目录；
- `GET /api/a-share-index/prices/snapshot?thscodes=...` 分批获取行业行情。

目录一次性返回行业身份，快照按有限批次请求；每批必须提供有效 timestamp，批次原始响应时间可以不同，
但转换后的上海日期必须一致。
原 `/api/a-share/industry/ranking` 保留为失败兼容路径或删除其调用，但不得继续把
404 响应当作可用能力。

### 2. Treat the provider as a degraded fallback, not a full replacement

适配器将目录名称映射到 `name`，`thscode` 映射到 `code`，
`price_change_ratio_pct` 映射到 `changePct`，`turnover` 映射到 `amount`。
`mainNet`、`mainNetPct`、`upCount`、`downCount` 和 `leader` 固定为 `null`，并在
quality warnings 中声明字段不可用。采集器使用已有允许落盘的 `fallback` 状态，
避免引入未被 `SUCCESS_STATUSES` 接受的运行时状态；页面仍通过 source、status 和
warning 显示其不完整性。

目录/快照行先按涨跌幅降序，再按 `thscode` 升序打破并列，取前 10 行。缺少身份、
名称、涨跌幅或成交额的行不进入结果；若有效覆盖不足，结果为 insufficient/failed
而不是用零值填充。

### 3. Gate formal use with the existing capability report and dataset switch

复用 `MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED`、
`MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION` 和 capability report。
只有开关开启、report status 为 `eligible` 且 revision 完全匹配时，coordinator 才
在东方财富链路失败后请求扶摇；否则保持现有 failed-retained/failed-missing。
capability report 增加真实 endpoint、字段覆盖、日期、完整目录/快照数量和限流证据，
不记录 API key 或原始凭据。

### 4. Bind every accepted result to an exact Shanghai trading date

适配器把快照 `data.timestamp` 转换为 `Asia/Shanghai` 日期，并要求每个批次均有该证据、所有批次日期一致，且该日期出现在
扶摇交易日历中且等于请求 `as_of`。目录与快照只用于当前可证明日期；不把最新快照
包装成历史日期。日期缺失、周末/非交易日、缺少批次 timestamp 或批次跨交易日时，返回 insufficient
并保留原因，不写入成功快照。

### 5. Normalize the frontend date to the core effective date

`loadCore()` 收到 `nextData.asOf` 后，只要它与请求日期不同，就将
`selectedDate` 和内部 `coreRequestedDate` 同步为 `nextData.asOf`。后续
`loadSection('sectors')` 使用该值并继续检查 section response 与 core 的 `asOf`
一致。这样手工选择周末/节假日时，页面不会用原始日期触发 latest-only 拒绝；真实
支持的历史交易日仍保持原日期。

### 6. Preserve warnings across fallback layers

provider 层返回结构化 warnings；collection 层合并东方财富主域、延迟域、扶摇
请求、日期验证和缺失字段 warning。成功的扶摇 fallback 任务状态为 `partial`（若
已有独立 fallback status 规则）或 `success` with `fallback` quality，失败则只按
同日期快照转成 `failed-retained`/`failed-missing`。

## Risks / Trade-offs

- [扶摇快照是当前时点而非收盘快照] -> 仅在交易日/时间戳可证明时采纳；quality 明确标记 fallback，不宣称资金流和板块宽度完整。
- [320 个行业目录或快照批次发生变化] -> 校验目录身份唯一性、批次总量和时间戳一致性；不完整时拒绝保存成功结果。
- [扶摇限流或权限变化] -> 使用已有 bounded retry/request budget；capability report 记录限流/权限结果，失败继续走同日期留存。
- [与东方财富行业分类不一致] -> source 和 provider revision 显式暴露；不做跨供应商逐行 shadow 的强一致断言，只比较公共代码/名称/涨跌幅等可比字段。
- [日期归一覆盖显式用户选择] -> 仅在 core 返回不同有效 `asOf` 时归一；section response 仍必须与 core 日期一致，避免静默混日。
- [生产启用后字段质量下降] -> 默认关闭、先做真实盘后 probe 和 shadow 对账；未满足 capability revision 时 fail-closed。

## Migration Plan

1. 先完成离线 fixture、适配器契约测试、capability report 生成和前端日期归一测试。
2. 使用显式 API key 执行盘后 real probe，记录脱敏 endpoint、日期、320 行覆盖、字段缺失和限流证据；不写正式 sectors 快照。
3. 在隔离存储执行 shadow 对账，确认目录/快照日期和排序稳定后生成批准 revision；默认部署配置仍为 disabled。
4. 由受控部署将 sectors 开关和 approved revision 一起启用，观察 collection task source/status/warnings 与 exact-date API；不做历史回填。
5. 若 provider 不可用或字段/日期契约退化，先将开关关闭并重新部署；现有东方财富链路和同日期留存继续工作，禁止删除 PVC 或手工写快照。

## Open Questions

无。provider endpoint、字段降级、日期绑定、开关门禁和回滚边界已经由当前文档与探针结果确定。
