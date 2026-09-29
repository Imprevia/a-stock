## 1. 扶摇行业数据契约

- [x] 1.1 重写 `FuyaoMarketAdapter` 的 sectors 请求路径，接入官方行业目录、指数快照和交易日历接口，并验证缺失 key、HTTP 错误和业务错误均 fail-closed
- [x] 1.2 实现目录与快照的批次请求、唯一身份校验和稳定排序（涨跌幅降序、代码升序），用离线 fixture 验证 320 条目录和快照覆盖不足时不会生成成功结果
- [x] 1.3 实现上海交易日和快照时间戳日期校验，覆盖当前日、周末、非交易日、跨上海日期、缺少批次 timestamp 和同日响应时间抖动场景，验证不会把最新快照包装为历史日期
- [x] 1.4 将扶摇字段映射到兼容的 `SectorRow`，验证代码、名称、涨跌幅、成交额正常输出，主力净流入、涨跌家数和领涨股缺失时均为 `null` 并产生字段 warning
- [x] 1.5 为扶摇 sectors 生成脱敏 capability report 所需的 endpoint、字段覆盖、日期、目录/快照数量、权限和限流证据，并验证 API key 不会出现在报告或日志中

## 2. Provider 门禁与采集集成

- [x] 2.1 扩展 sectors capability revision 与现有 `MARKET_ENVIRONMENT_FUYAO_SECTORS_*` 配置校验，验证 disabled、缺少 report、非 eligible 和 revision mismatch 均不调用扶摇
- [x] 2.2 在东方财富主域和延迟域均失败后接入已批准的扶摇 fallback，合并前序 provider warning、扶摇 source/revision 和缺失字段 warning，验证 fallback 质量状态可被采集器接受
- [x] 2.3 保持同日期快照留存和任务隔离，验证扶摇成功时只写请求日期、扶摇失败时分别得到 `failed-retained` 或 `failed-missing`，且不会跨日期回填
- [x] 2.4 为 fallback 增加 shadow 对账字段和比较结果，验证 shadow 失败只降低可观测质量，不阻断已通过 capability 门禁的正式结果，也不写入凭据
- [x] 2.5 复用现有 provider-free status/read path，验证读取 collection status、快照和聚合时不触发扶摇或东方财富请求

## 3. 前端日期归一

- [x] 3.1 修改 market store，使 core 响应 `asOf` 与请求日期不同时同步 `selectedDate` 和内部 section 请求日期，并保持请求序列、日期一致性和缓存失效语义
- [x] 3.2 增加周末/节假日手工选日期后打开 `sectors` 的 Vitest 回归测试，验证 chapter request 使用归一后的 core `asOf`
- [x] 3.3 增加有效历史交易日和 core 日期一致性测试，验证显式支持日期不被错误改写，section 日期不一致时仍显示错误而非静默合并

## 4. 文档、配置与运行边界

- [x] 4.1 同步 `docs/architecture.md`，记录东方财富双端点到 capability-gated 扶摇 THS 行业指数 fallback 的数据流、字段降级和 provider-free 读取边界
- [x] 4.2 同步 `docs/runbooks.md`，记录官方扶摇 endpoint、盘后 real probe、脱敏报告、批准 revision、失败留存和关闭开关的回滚步骤
- [x] 4.3 更新市场环境产品规格和行业 capability 主 spec，明确 fallback 仅提供行业指数排名/涨跌/成交额，缺失资金流、宽度和领涨股不得冒充完整行业事实
- [x] 4.4 更新 active exec plan 与 `docs/status.md`，记录当前 Eastmoney 断连证据、扶摇探针结果、默认关闭状态和正式启用前置条件
- [x] 4.5 更新 Helm/部署配置说明和 manifest 测试，验证 sectors 开关默认关闭、approved revision 由显式配置注入、Secret 不进入 values 或日志

## 5. 验证与发布门禁

- [x] 5.1 增加后端 provider、capability、collection、snapshot-retention 和 API contract 测试，验证所有新增场景通过现有 pytest focused suite
- [x] 5.2 增加前端 store/page 回归测试并运行 `npm run test` 与 `npm run build`，验证桌面和 390px 视口无页面级横向溢出
- [x] 5.3 运行 `python -m src.trading_system.cli docs sync-check`、`python scripts/check-docs-contract.py --mode=full` 和 `openspec validate restore-sector-data-via-independent-provider --strict`，修复所有门禁错误
- [x] 5.4 在显式盘后授权环境执行扶摇 real probe 和隔离 shadow 对账，只输出脱敏 capability evidence，验证未批准前不写正式 sectors 快照
- [x] 5.5 在批准 revision 后执行一次受控当前日 sectors 采集和 status/API 观察，验证 source、fallback 状态、缺失字段 warning、exact-date 和失败回滚证据；失败时先关闭开关并确认 Eastmoney 留存链路仍可用
