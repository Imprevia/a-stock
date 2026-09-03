## Context

数据采集页与行情研究页当前共用 `getDefaultMarketDate`。该函数在 15:00 前选择上一自然日，适合避免研究页展示未结算行情，却与 `breadth`、`sectors`、`activeDirection` 只能采集上海市场当天的约束冲突。结果是采集页在主要交易时段默认禁用三个 latest-only 数据集。

行业排名只使用东方财富 `push2` 主域。真实请求可以返回完整结果，也会间歇出现 `RemoteDisconnected`；共享 `EastmoneyClient` 没有连接重试，请求 limiter 没有线程同步，而 API 的两个后台 worker 共享同一 `requests.Session`。此外，当前请求只列出 `f140` 并把它映射为领涨股名称，真实接口中 `f128` 才是名称，`f140` 是证券代码且关联字段可能在字段组合不完整时被省略。

## Goals / Non-Goals

**Goals:**

- 让采集页首次打开时默认选择后端上海市场当天，使 latest-only 数据集在有效日期可操作。
- 保持行情研究页现有的结算日期默认逻辑不变。
- 对所有进程内东方财富请求提供真正串行的请求边界和有界瞬态恢复。
- 在行业主域失败后使用同口径延迟域名降级，并保留可审计的来源与 warning。
- 正确输出领涨股名称，并用离线 fixture 锁定真实字段语义。
- 保持失败不覆盖同日期成功快照、禁止跨日期回填的既有契约。

**Non-Goals:**

- 不提供历史行业榜回补，不用当前行业数据伪造历史日期。
- 不引入 Redis、分布式锁、外部任务队列或新的 HTTP 依赖。
- 不改变五类数据集、公开采集 API 路径或现有响应字段。
- 不解决东方财富行业分类同时包含多层级板块的问题；本次只保证采集稳定性和字段正确性。

## Decisions

### 1. 采集页从后端解析默认市场日

采集状态 API 已在省略 `as_of` 时使用 `market_today`。前端的首次状态请求不传日期，并以响应的 `asOf` 初始化日期控件；用户后续手工切换日期时继续发送显式 `as_of`。这样日期能力由后端上海时区统一决定，避免浏览器本地时区和研究页截止时间影响采集入口。

替代方案是新增前端 `getDefaultCollectionDate` 并使用浏览器当天，但这仍可能在非上海时区客户端选错日期，也会重复后端已有的市场日判断。

### 2. 东方财富 limiter 拥有全局请求锁

将串行边界放在共享 limiter 内，由同一个锁覆盖间隔计算、等待和实际 HTTP 请求。所有 `EastmoneyClient` 实例继续复用全局 limiter，因此两个后台 worker 不能并发使用共享 Session 访问东方财富。锁只覆盖单次东方财富请求，不包围解析、存储或其他 provider。

仅在 `acquire()` 内加锁只能保证启动间隔，慢请求仍可能重叠，不能满足仓库规定的“共享串行 limiter”。为保持现有测试可注入性，limiter 提供执行请求的受控入口，时钟、sleep 和随机抖动仍可替换。

### 3. 在 HTTP 适配器层进行有限瞬态重试

为 `EastmoneyClient` 使用的 Session 挂载 `HTTPAdapter` 和 `urllib3 Retry`，覆盖连接中断、读取失败、429、500、502、503、504，使用有限次数和退避。403 不进入状态重试列表，仍由客户端立即转换为 `ProviderFailure(retryable=False)`。

重试必须发生在同一个全局串行请求门内，避免一次逻辑请求的重试与另一个采集任务交错并放大风控。JSON 结构错误和业务空数据不在通用 HTTP 层盲目重试，由具体 provider 决定是否降级。

### 4. 行业排名使用主域到延迟域的确定性降级链

行业 provider 先请求 `https://push2.eastmoney.com/api/qt/clist/get`。主域在有界重试后仍发生连接/HTTP/有效载荷失败时，请求 `https://push2delay.eastmoney.com/api/qt/clist/get`。延迟域返回有效行业行时，质量来源标记为 `eastmoney-clist-delay`，状态保持 `fallback` 或兼容成功快照存储的降级状态，warning 记录主域失败原因。

两个端点都失败时才返回 `failed`，collection coordinator 继续使用现有 `failed-retained` / `failed-missing` 处理。降级不改变 `asOf`，且只允许市场当天调用。

### 5. 显式请求并映射行业领涨股名称

行业字段组合加入 `f128`、`f136`、`f140`、`f141` 等关联字段；响应中的 `leader` 使用 `f128` 名称。暂不扩展公开 schema 增加 leader code，避免不必要的 API 变化。fixture 使用真实字段形态，防止再次把 `f140` 代码伪装成名称。

## Risks / Trade-offs

- [主域和延迟域属于同一供应商，可能同时不可用] -> 两者都失败时明确输出 `failed`，并保留同日期旧快照；不伪造成功。
- [全局串行和退避增加批量采集耗时] -> 普通 GET 仍只读本地快照，采集 POST 已异步；稳定性优先于后台批次总耗时。
- [在锁内 sleep 会阻塞其他东方财富任务] -> 这是满足供应商串行限流的预期行为，非东方财富 provider 不受影响。
- [延迟域的个别可选字段可能缺失] -> 核心行业排名、涨跌家数和资金字段必须验证；可选字段保持 `null` 并通过 warning 表达。
- [首次状态请求改为无日期参数可能影响现有 mock] -> 保留显式日期调用兼容性，并更新前端 API 单测覆盖两种请求。

## Migration Plan

1. 创建 active exec plan，并先更新产品规格、架构和 runbook。
2. 加固共享东方财富请求门和重试配置，增加确定性并发与错误分类测试。
3. 实现行业主域到延迟域降级和真实字段解析，增加 provider/collection 保留测试。
4. 调整采集页首次状态请求和日期初始化，不改变研究页默认日期。
5. 运行后端、前端、OpenSpec 和 docs-contract 验证，并用当前市场日执行显式本地真实数据 smoke test。
6. 回滚时可恢复原前端初始化与单行业端点；SQLite schema 和已保存快照无需迁移或回滚。

## Open Questions

无。行业层级筛选和独立供应商备胎留给后续 change。
