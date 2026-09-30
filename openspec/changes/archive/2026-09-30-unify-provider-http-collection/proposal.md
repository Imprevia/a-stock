# Proposal

## Why

部分行情 provider 已有独立限流和降级，但腾讯、百度、新浪及 TDX 仍绕过统一请求门直接发起 HTTP 请求。一次核心刷新可能在多个指数上重复访问多个 host，缺少统一缓存、失败冷却和请求画像管理，导致连接失败、429/403 和冷启动耗时放大。

## What Changes

- 增加跨 provider 的 HTTP 请求层，统一连接复用、超时、请求节奏、有限退避、Retry-After、请求预算和失败分类。
- 为每个 host 的 session 使用现代浏览器 UA 池，session 生命周期内保持稳定，重建时再轮换。
- 增加相同请求单飞、短 TTL 缓存和 host 短熔断/受控恢复探测。
- 将 Tencent、Baidu、Sina 和 TDX 盘后包请求迁移到统一请求层。
- 保持现有 Eastmoney/Fuyao 质量状态、provider 路由、精确日期和 feature flag 语义。
- 不增加代理池、Cookie 伪造或绕过供应商访问控制的行为。

## Capabilities

### New Capabilities

- `provider-http-transport`: 为行情 provider 提供统一、可测试且按 host 隔离的请求节奏、重试、缓存和熔断能力。

### Modified Capabilities

- `market-data-collection-management`: provider 失败、重复采集和独立任务的请求行为增加统一 transport 约束，继续保持失败隔离和失败留存。
- `market-data-snapshot-cache`: 增加请求层短缓存与单飞边界，禁止跨日期复用外部响应。
- `sector-data-collection-stability`: 行业主/延迟端点继续按既有顺序运行，但统一使用请求层的限流、退避和失败分类。
- `active-direction-data-collection-stability`: 容量方向主/延迟端点继续按既有顺序运行，但统一使用请求层的限流、退避和失败分类。

## Impact

- 主要影响 `src/trading_system/data/providers.py`、`src/market_environment/providers.py`、`src/market_environment/tdx_daily.py` 及相关 Fuyao/请求测试。
- 需要同步 `docs/architecture.md`、`docs/runbooks.md`、产品规格和 active plan。
- 不新增第三方依赖；复用现有 `requests`/urllib3 能力。
