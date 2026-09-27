## Context

当前 TDX 解析器在完成压缩包、日期、数值和市场文件校验后，只要 `close > 0` 就把行放进 `TDXDailyPackage.rows`。因此 `rows` 是“有价格的全证券集合”，不是普通 A 股集合。`MarketDataProvider._fetch_tdx_breadth()` 直接使用这些行计算广度；同一个共享包也被 TDX 派生的 `activeDirection` 用于成交额排序。现有快照、刷新和采集协调器已经具备精确日期、checksum、失败保留和 provider-free 读取语义，质量对象也允许增加可选审计字段。

本设计承接 `proposal.md` 的动机和两份市场广度/快照 delta spec，并额外明确共享 TDX 包对 `activeDirection` 的影响：普通 A 股分类是两个股票型消费者的共同前置阶段，而不是只在某一个计算函数里临时过滤。

## Goals / Non-Goals

**Goals:**

- 建立一个按请求日期选择规则版本的、默认拒绝未知身份的普通 A 股分类阶段。
- 让 `breadth` 和 TDX 派生 `activeDirection` 共享同一证券宇宙，且保留原始包行数与过滤审计。
- 保持现有公开计数字段、Top-N 字段、来源链和前端兼容；新增质量字段为可选元数据。
- 在过滤后事实不足时明确返回 `insufficient`/`failed`，并复用现有 exact-date 快照与失败保留机制。
- 为已知错误日期提供只通过显式采集命令执行的重采集、原子替换和失败保留路径。

**Non-Goals:**

- 不改变 Eastmoney 的股票筛选、排序、重试顺序或主源优先级。
- 不把名称、价格、成交额、当前行情或指数成分猜测当作证券类型证明。
- 不在本 change 中建立全量实时证券主数据服务，也不提交真实全市场数据或未经审核的行业映射。
- 不在普通 GET、状态查询或前端加载过程中调用 provider、自动修复快照或跨日期回填。
- 不执行生产发布、CronJob 激活、数据库/PVC 写入或真实 provider 采集。

## Decisions

### 1. 保留结构化解析，新增共享的 universe 分类阶段

`parse_tdx_daily_package()` 继续负责 ZIP 和二进制记录的结构化事实，保留原始有价格行及原有 `marketCounts`/`recordCount` 作为包级证据。新增一个纯函数式分类边界（可命名为 `classify_tdx_stock_universe` 或等价接口），输入规范化行和请求日期，输出：

- 通过的普通 A 股行；
- 过滤前、保留、排除、未分类总数；
- `sh`、`sz`、`bj` 的保留统计；
- 每个排除行唯一的原因分类；
- 选择的策略版本和分类 warning。

`MarketDataProvider._fetch_tdx_package()` 在日期/结构校验后执行一次该阶段，并以过滤后的行返回给 `breadth` 和 TDX 派生 `activeDirection`。原始计数仍留在 metadata 中，避免把“包完整但混合证券”误写成普通股票样本。

备选方案是只在 `_fetch_tdx_breadth()` 内做临时过滤。该方案会让共享 TDX 包继续污染 `activeDirection`，也容易在未来新增消费者时再次遗漏，因此不采用。把分类直接塞进二进制解析器也不采用，因为解析器应保留结构事实，且测试/诊断需要看到过滤前分母。

### 2. 使用版本化的市场/代码白名单，未知默认不保留

分类器同时检查 `market` 和六位代码，并按请求日期选择不可变的规则版本。规则以代码号段白名单为主、非股票号段显式排除为辅；不依赖证券名称、价格、成交额或是否“看起来可交易”。上海、深圳和北京分别维护规则，普通主板、科创板、创业板和北交所普通股票纳入，基金/债券/指数/权证/B 股/存托凭证等排除。

北交所历史号段与 2025-10-09 起适用的 `920` 号段作为日期边界写入策略表和 fixture。规则版本必须随质量元数据输出；未登记市场、非法代码和不适用日期的号段归入 `unclassified`，不能靠名称猜回股票。普通股票的 ST、退市整理等名称变体不通过名称过滤，避免把名称语义混入证券身份。

### 3. 将包完整性门槛与股票宇宙门槛分开

现有包解析门槛用于证明三个市场文件和原始记录没有截断；它不再被直接解释为普通 A 股数量。分类后另行检查各市场普通股票最小行数、必需市场覆盖和全局最小样本。两组阈值均由版本化常量/配置提供，测试可注入小门槛，生产值须在 runbook 中记录。

这样既能保留原始包的传输完整性，也不会把例如上海原始证券数的门槛错误套到过滤后的普通股票数。过滤后的候选若缺少必要市场、超过允许未分类比例、低于股票门槛或缺少关键价格事实，则整个候选保持 `insufficient`/`failed`。

### 4. 质量元数据以过滤后样本为统计事实

TDX 成功质量对象增加可选字段，建议包括：

- `stockUniversePolicyVersion`
- `stockUniverseRawCount`
- `stockUniverseRetainedCount`
- `stockUniverseExcludedCount`
- `stockUniverseUnclassifiedCount`
- `stockUniverseRetainedByMarket`
- `stockUniverseExcludedByReason`

`breadth.validCount`、三类计数、`medianReturn`、`quality.observations` 和前一交易日身份重叠率只基于保留的普通 A 股行。`activeDirection` 的 `quality.observations` 仍表示通过事实校验的 Top-30，另外暴露过滤后的总保留数；任何失败结果也保留策略版本和过滤诊断，不能回退成旧的全证券计数。若需要扩展 `_missing_breadth()` / `_missing_active_direction()`，应让其接受来源和 metadata，而不是把失败来源硬编码为 Eastmoney。

### 5. TDX 派生 activeDirection 明确复用该边界

由于容量方向的 Eastmoney 主/延迟端点本身就是股票榜，TDX 派生路径也必须使用同一普通 A 股集合。过滤后再执行成交额降序、规范证券身份升序的本地排序；Top-30 最小样本、名称补齐、行业映射和 `fallback-derived` 语义保持原有 delta spec，不把新增分类当作 provider 排名证据。

这一决定已通过本 change 增加 `active-direction-data-collection-stability` delta spec，避免共享 helper 的行为扩展没有验收标准。`sectors`、`limits`、`core` 和 Eastmoney 成功路径不使用该 TDX 分类器。

### 6. 精确日期重采集复用现有刷新/采集事务

已知错误日期通过显式的 exact-date refresh/collection 调用重新获取原日期 TDX 包。成功结果走现有 `SnapshotStore.put()` 的同日期原子 upsert，重新生成 payload checksum、observations、quality metadata 和聚合证据；失败只记录 collection/refresh attempt，并保留同日期旧快照及 `failed-retained`/`failed-missing` 状态。

不增加普通 GET 的修复分支，不直接 SQL 改 payload，不把 2026-09-23 或 2026-09-24 的结果改名到其他日期。应用版本发布前先用离线 fixture 和显式、只读 real probe 验证；生产重采集属于单独授权的运维动作。

## Risks / Trade-offs

- [代码号段规则随交易所调整或新证券类型出现] -> 采用不可变策略版本、默认拒绝未知身份、记录未分类原因，并用边界 fixture 阻止静默纳入。
- [股票最小行数阈值过严导致真实包被判不足] -> 将原始包完整性阈值与股票宇宙阈值分离，支持注入测试门槛，并在受控 real probe 后校准生产常量；不足时保留失败而不伪造成功。
- [共享分类同时改变 TDX 派生 activeDirection] -> 增加对应 capability delta spec、独立 provider/collection 回归测试和质量审计字段，明确这是有意的同一股票宇宙收敛。
- [名称补齐或相邻交易日事实仍失败] -> 只对保留行执行有界补齐；任一关键事实不足即进入失败保留，不使用其他来源的价格/日期。
- [旧错误快照仍存在] -> 先显式重采集受影响日期；失败时保留旧值但附带错误 universe warning，禁止普通 GET 自动联网或跨日替代。
- [旧客户端不认识新增质量字段] -> 保持既有 payload 字段和状态值兼容，新增字段只放入质量对象；前端只增加质量标签/审计展示，不重算计数。

## Migration Plan

1. 在开始代码实现前创建或更新对应 `docs/exec-plans/active/*.md`，记录范围、受影响 capability、禁止生产写入边界和验收字段。
2. 实现版本化分类器、TDX package metadata、两个 provider 消费者的过滤后校验，并补齐离线 fixture、后端/快照/采集回归测试；默认开关和 Eastmoney 成功路径保持不变。
3. 运行 `.venv/bin/python -m pytest tests -q`、规则/文档门禁、前端测试与构建，并执行不写快照的显式 TDX real probe，确认请求日期、策略版本、原始/保留行数、三地覆盖和失败语义。
4. 经另行授权后，按原日期对 2026-09-23、2026-09-24 及审计清单中的其他日期分别重采集 `breadth` 和 `activeDirection`；逐项核对 checksum、observations、过滤审计、聚合响应和 collection 状态。任何日期失败都只保留同日期旧值并标记 warning。
5. 若部署后发现分类规则或阈值不正确，先关闭 TDX fallback/derived 开关并停止继续重采集，再按 runbook 回滚应用；不删除快照、PVC 或历史审计记录。
