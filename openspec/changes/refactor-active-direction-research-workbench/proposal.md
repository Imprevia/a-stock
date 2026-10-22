## Why

当前“大成交额主动进攻方向”页只展示少量成交额靠前股票及质量提示，无法回答《搭建交易系统/04-板块、题材与个股筛选》01—07 所要求的方向真实性、资金异常、核心辨识、候选模式、基本面风险和次日验证问题。需要把单一榜单升级为精确日期、证据优先的盘后研究工作台，同时保持缺失数据、未经回测规则和来源边界可见。

## What Changes

- 保留 `/dashboard/06`、现有导航名称和旧 `activeDirection.topStocks` 兼容字段，把页面重构为“方向总览、成交额资金地图、核心股辨识、候选模式、基本面与验证”五个工作视图。
- 新增 provider-free 的精确日期工作台读取契约，组合本地板块、容量方向、涨跌停、事件及后续批准的股票历史/基本面事实；读取不得触发采集、回填或跨日期替代。
- 将容量榜从仅展示 Top 10 扩展为可审计的 Top 30 研究样本，保留来源排序或本地派生排序、证券身份、行业映射版本、覆盖率和 warning；旧 Top 10 消费者继续兼容。
- 为板块方向、成交额榜、六项核心辨识、异动资金、放量长上影、一进二和基本面风险返回结构化证据、覆盖率、缺失输入、否决项、确认条件和失效条件。
- 所有 `QTS-04-01-*` 至 `QTS-04-07-*` 继续显示 `documented-only` / `needs-backtest`；证据完整也不得标记 `validated`、自动赋予“龙头/中军/补涨”角色或生成买卖建议。
- 一进二视图保持盘后边界：严格首板次日候选与五日涨停强势候选分开；竞价和盘中确认仅作为下一交易日待验证输入，不增加实时交易或自动下单能力。
- 缺少股票历史、规范板块身份、分钟事实或财务事实时，相应模块返回 `missing` / `insufficient` 和具体缺口，不用零值、其他日期或前端推断补齐。
- 页面在桌面和 390px 移动视口保持所有可见文字、图例、坐标和 tooltip 不小于 14px，无页面级横向溢出；宽表只允许自身滚动。

## Capabilities

### New Capabilities

- `active-direction-research-workbench`: 定义盘后五视图工作台、结构化筛选证据、规则状态、缺失语义、跨模块选择和次日验证契约。

### Modified Capabilities

- `active-direction-data-collection-stability`: 在维持现有 Top-N 校验、来源降级和旧 Top 10 兼容的前提下，保留并公开经过验证的 Top 30 研究样本及其排序和映射 lineage。

## Impact

- 后端：active-direction 采集 payload、精确日期 materialization/read model、domain analysis、typed read ports、PostgreSQL repository、V2 DTO/router 和兼容 adapter。
- 前端：`Document06ActiveDirectionPage.vue`、类型、Pinia V2 资源加载、路由资源声明、可复用证据/状态组件、样式和 Vitest。
- 规则与文档：保持现有 QTS-04 规则 ID 和 `documented-only` 状态；同步产品规格、架构、运行手册、repository guide、active exec plan 和阶段完成证据。
- 测试：Top 30 兼容与分页、精确日期/provider-free GET、缺失和失败保留语义、五视图交互、桌面/390px 可读性、后端 focused/full pytest、前端 Vitest/Vite build、规则门禁与 docs-contract full。
- 外部边界：不新增 application-owned CronJob，不在普通 GET 中访问 provider，不执行生产回填、部署、数据库删除或自动交易。
