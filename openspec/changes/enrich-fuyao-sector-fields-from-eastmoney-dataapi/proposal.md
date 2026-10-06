## Why

扶摇行业 fallback 已能稳定提供同花顺行业代码、名称、涨跌幅和成交额，但当前 `SectorRow` 的主力净流入、主力净流入比例、上涨/下跌家数和领涨股仍为空；东方财富主、延迟行业接口持续失败时，第 05 页只能展示不完整的行业证据。已验证的 `data.eastmoney.com/dataapi/bkzj/getbkzj` 接口能够返回这些字段，但它仍属于东方财富、只提供 latest-only 数据，且行业分类覆盖与扶摇目录不一致，因此需要一个受限、可审计的字段增强方案，而不是把它误认为独立 provider 或历史数据源。

## What Changes

- 在扶摇行业结果成功后，按当前上海交易日、显式字段列表调用东方财富 `dataapi/bkzj/getbkzj`，补充 `mainNet`、`mainNetPct`、`upCount`、`downCount` 和 `leader`。
- 对东方财富 `f3`、`f6`、`f62`、`f104`、`f105`、`f128`、`f184` 做独立字段校验和口径归一；不把整数化百分比直接写入现有 `SectorRow`。
- 建立版本化的行业身份匹配边界：不得把扶摇 THS 代码与东方财富 `BK` 代码直接等同；仅对明确匹配的行业合并字段，未匹配行继续保留 `null`。
- 在质量元数据中记录增强来源、匹配覆盖率、字段覆盖率、latest-only 限制、同供应商补充性质和前序失败 warning；增强失败不得使扶摇已有四字段结果失效。
- 保持精确日期和失败留存语义：历史日期不得调用该接口或用当前响应回填，响应缺少可接受的当前日期证据时只返回未增强的扶摇结果。
- 增加离线 fixture、字段归一、身份匹配、部分覆盖、日期限制、增强失败和 collection/API 质量契约测试；真实 provider 只允许在显式盘后隔离 probe 中验证。
- 保持 Tushare 为未启用备选。当前 token 无 `moneyflow_ind_ths`、`moneyflow_ind_dc`、`ths_index`、`ths_daily` 等相关接口权限，本变更不引入 Tushare 运行时依赖。
- 同步行业采集 capability spec、架构、运行手册、产品规格和 active plan，明确该接口是东方财富同供应商字段增强，不是独立回退源。

## Capabilities

### New Capabilities

无。该变更扩展现有行业板块采集契约，不新增用户可见数据集或 API 路由。

### Modified Capabilities

- `sector-data-collection-stability`: 增加经过字段、身份、日期和覆盖率门禁的东方财富 dataapi 字段增强，并规定增强失败时保留扶摇基础结果。
- `market-data-collection-management`: collection task、snapshot 和 provider-free 读取需要保留增强来源、覆盖率、warning 以及同日期失败留存语义。

## Impact

- 后端 provider、扶摇适配器、collection coordinator、质量元数据和快照 payload。
- 现有 `SectorRow` 字段保持兼容，可能增加质量元数据字段，不新增数据库表或公开路由。
- Eastmoney 统一传输层需要覆盖 `data.eastmoney.com`，并继续执行请求门、单飞、有限重试、缓存和失败分类。
- 前端行业页继续使用现有字段，但需要展示字段增强/部分匹配 warning，不得把补充字段伪装成完整独立来源。
- 测试 fixture、provider contract、collection/API contract、部署默认值和文档门禁。
