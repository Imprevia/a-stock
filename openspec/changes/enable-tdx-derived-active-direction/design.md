## Context

当前 `MarketDataProvider` 已能下载并校验指定日期的 TDX 盘后包，也能在 Eastmoney 两条路径失败后尝试该包；但 active-direction 目前要求输入本身已经按成交额降序，因而会拒绝真实 TDX 包中常见的无序记录。采集协调器把质量状态和任务状态分开保存，普通快照读取不调用 provider；质量可接受集合目前不包含 `fallback-derived`，任务状态也没有“快照可用但本次运行降级”的明确映射。

本设计仅处理 proposal.md 中的 activeDirection 派生 fallback。`limits`、`sectors`、当前 Eastmoney 主/延迟链和现有 breadth fallback 不在本设计中重写。

## Goals / Non-Goals

**Goals:**

- 在独立开关开启时，将精确日期 TDX 全市场包转换为可审计的 active-direction Top-30/Top-10 派生结果。
- 让派生结果可写入精确日期快照，同时在 quality、collection task 和 parent run 中保持降级可见。
- 保留 TDX 原始价格、成交额、日期和证券身份事实；本地只负责排序和可选行业聚合。
- 让行业映射缺失只影响方向聚集结论，不阻断股票 Top-N 展示。
- 保持默认关闭、Eastmoney 优先、失败保留和无跨日期回填。

**Non-Goals:**

- 不把本地排序结果标记为 provider-ranked，也不修改 Eastmoney 候选的排序门禁。
- 不允许 TDX 当前包替代历史日期；activeDirection 仍遵循当前快照型数据集的日期能力限制。
- 不用 TDX 日线推断盘中封板、涨停过程、资金流或行业主力净流入。
- 不在本 change 中引入新的数据库表、删除快照、修改公开 Top-10 字段或切换 `limits`/`sectors` provider。
- 不提交未审计的全量股票行业真实数据快照；行业映射不可用时必须明确返回不足状态。

## Decisions

### 1. 为 activeDirection 增加独立的派生开关

新增 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED`，默认关闭。只有 activeDirection 的 Eastmoney 主域和延迟域都失败后，且该开关为真时，才读取 TDX 包。现有 `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED` 继续控制 breadth fallback，避免一次配置改变扩大生产行为。

备选方案是复用已有总开关，但这会把已验证的 breadth 发布和尚未验证的 activeDirection 派生语义绑定在一起，难以独立回滚，因此不采用。

### 2. 保留 TDX 事实，新增确定性本地排序阶段

在 provider 内新增一个只处理 TDX 行的派生步骤：

1. 校验请求日期、包源日期、沪深北覆盖、证券身份唯一性、收盘价、成交额和可信名称。
2. 对有效行按 `amount` 降序排序；成交额相同时按规范证券身份升序排序，确保重复采集结果一致。
3. 截取 Top-30 作为质量观测数和方向聚集输入，截取 Top-10 作为兼容展示字段。
4. 将 TDX 的收盘价、涨跌幅、最高/最低和成交额映射到现有股票字段；不使用名称查询结果覆盖这些事实。

`tdx-daily-package-derived` 只表示排序方法，不表示 TDX 原始包已提供榜单排序。Eastmoney 输入仍执行“源侧已排序、发现逆序即拒绝”的原规则。

### 3. 以 `fallback-derived` 作为质量状态，任务状态保持 partial

质量层新增以下兼容扩展字段：

- `source=tdx-daily-package-derived`
- `status=fallback-derived`
- `derived=true`
- `rankingMethod=local-turnover-desc-identity-asc`
- `sourceRevision` 包含已固定的 TDX 上游 revision
- `industryMappingRevision` 与 `industryMappingCoverage`，仅在行业聚合阶段有值

`fallback-derived` 加入可写入快照的质量状态集合，但 collection task 映射为 `partial`，父 run 只要包含该任务也保持 `partial`。这样数据可以正常被看板读取，又不会把 TDX 派生结果当作五项全量 provider success。

备选方案是将质量状态压成现有 `fallback`。这会丢失“发生了本地排序”的关键证据，无法满足审计边界，因此不采用。

### 4. 行业映射是可选证据，不阻断股票榜

TDX 包不包含可靠行业字段。实现提供一个版本化映射接口，输入规范证券身份和映射生效信息，输出行业名称与覆盖率；它可以接入已有本地参考数据或后续经批准的数据源，但不在本 change 中提交全量真实股票映射快照。

Top-30 股票事实全部有效时，即使映射不可用，也可以保存 Top-10 股票。只有 Top-30 映射覆盖完整时才允许生成行业聚集候选；覆盖不足时 `state=unverified` 或 `insufficient`，行业字段保留 `null`，并输出映射版本/覆盖率 warning。

备选方案是用股票名称或旧日期行业信息猜测行业，这会引入前视偏差和不可追溯的身份错误，因此不采用。

### 5. 名称补齐只补名称，不替换行情事实

优先使用 TDX 包内名称；仅对 Top-30 中缺名行进行一次有界批量名称查询。名称查询失败或返回代码本身时拒绝对应行；不能用该查询的价格、成交额、日期或行业字段覆盖 TDX 包事实。

### 6. 使用现有快照和失败保留机制

不新增表或 API。派生 payload 进入现有 snapshot store，质量和来源随 payload/快照 metadata 保存。失败时沿用同日期 `failed-retained` / `failed-missing`；普通 GET 仍只读本地精确日期快照，不触发 TDX 或 Eastmoney 请求。

## Risks / Trade-offs

- [TDX 包发布时间晚于 CronJob] -> 将候选失败保留为 `failed-retained`/`failed-missing`，由单项重试重新获取，不用当前报价或前一日数据替代。
- [本地排序与 Eastmoney 排名口径不同] -> 明确使用 `fallback-derived`，保留排序方法、源 revision 和 warning，不与 provider-ranked 结果混称。
- [行业映射过期或覆盖不足] -> 版本化记录覆盖率；不足时只展示股票榜，不生成方向聚集结论。
- [名称批量查询触发额外网络故障] -> 只请求缺名的 Top-30，设置有界超时；失败时拒绝缺名行并保留 TDX 主事实，不扩大查询到全市场。
- [新质量状态未被旧前端识别] -> 旧字段保持不变；前端质量映射将 `fallback-derived` 归入降级色调并显示明确标签，未知客户端仍可读取原有 Top-10 字段。
- [生产配置误开导致行为扩大] -> 新开关默认关闭，部署校验、real probe 和回滚只切换该开关，不删除任何快照或 PVC。

## Migration Plan

1. 实现派生排序、质量字段、可选行业映射接口和独立开关；补齐离线 fixture、后端契约测试、collection 状态测试和前端标签测试，默认行为保持不变。
2. 使用显式盘后 real probe 验证目标包的日期、市场覆盖、有效行数、名称覆盖率、排序输出、TDX revision 和质量报告；probe 不写生产快照。
3. 在受控部署中只开启 `MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED=1`，保留 Eastmoney 主/延迟优先，观察至少一个交易日的 collection task、parent run、快照质量和看板展示。
4. 若派生路径异常，关闭新开关并重启采集服务；已有 `fallback-derived` 快照保留为历史证据，后续读取仍可见，不删除数据库或 PVC。
5. 回滚验证包括：新开关为 `0`、Eastmoney 成功路径不额外请求 TDX、失败仍保持同日期 retention、docs/runbooks 和 active plan 记录实际质量结果。
