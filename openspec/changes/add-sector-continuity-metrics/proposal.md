## Why

第 05 章当前只展示当日行业排名，生产链尚未生成板块相对强度、成交持续性、板块宽度、分歧承接和前五行业成交集中度，因此无法基于真实盘后数据形成“今日唯一验证项”。现有 Fuyao 行业快照、TDX 全 A 盘后数据和规则 evaluator 已具备部分基础，但缺少统一的申万行业时点归属、连续历史聚合及从市场环境快照到交易规则输入的确定性桥接。

## What Changes

- 建立仅覆盖申万行业的时点行业主数据：稳定行业 ID、分类版本、股票成员关系及生效区间；历史计算不得使用当前成分回填过去日期。
- 复用 TDX 精确日期盘后包作为全 A 原始 OHLC/成交额事实，并引入经过 capability probe 的前复权或复权因子来源；按同一交易日、同一普通 A 股 universe 聚合行业收益、成交额、宽度和全市场成交额。
- 提供任意显式有界、可恢复的历史回填路径，首次预热默认覆盖截至分析日的 272 个交易日，并允许小范围修复或更长研究区间；普通 GET 不触发 provider，自动采集默认仍保持关闭/暂停。
- 在现有 `sectors` 结果上新增可选的连续性分析契约，计算 `QTS-01-05-01..05` 所需五项指标、历史覆盖、分位质量、候选行业和确定性阶段标签。
- 固定此前文档未明确的计算口径：行业与全 A 基准均使用同一普通 A 股 universe 的前复权日收益等权聚合，5 日/20 日相对强度两窗均有效后取较低滚动分位，负收益日作为分歧事件；同步量化文档、规则和证据后仍保持 `needs-backtest`。
- 根据预先定义的优先级生成一条“下一交易日只验证”及确认/失效条件；关键输入缺失时输出 `insufficient`，不得用涨停名单、当前成分、零值或其他日期替代。
- 将已生成的 sector metrics 接入标准交易规则快照，使规则 evaluator 使用生产计算值而非仅依赖测试 fixture；保留规则版本、数据版本、计算版本和证据引用。
- 第 05 页展示持续性、宽度、成交、内部结构边界、集中度、候选阶段和唯一验证项，同时保留原有当日行业表及质量告警。
- 本变更不覆盖概念板块，不自动推断“龙头/中军/补涨”角色；内部结构仅展示可证明的成交额、涨跌停、排名和扩散事实，角色自动分类留待后续规则定义。

## Capabilities

### New Capabilities

- `point-in-time-industry-data`: 定义申万行业分类、时点成员关系、个股/基准日线和行业日聚合的精确日期、完整性、复权、回填及审计契约。
- `sector-continuity-analysis`: 定义五项第 05 章指标、滚动分位、候选与阶段判定、抱团否决、唯一验证项和质量降级行为。

### Modified Capabilities

- `sector-data-collection-stability`: 将现有当日行业排名作为观察源保留，并增加与申万行业分析事实的身份隔离、精确日期历史输入及同日期失败留存要求。
- `market-data-collection-management`: 在现有 `sectors` 任务和 provider-free 读取中暴露历史覆盖、派生状态、版本和缺口，并提供显式、可审计的历史回填操作，而不新增普通 GET 的外部 I/O。
- `trading-rule-evaluation`: 将市场环境生成的五项 sector metrics 规范化写入标准规则快照，并保证缺失值、质量和版本信息参与确定性求值。

## Impact

- 后端：`src/market_environment/` 的 provider/source adapter、时点行业映射、持久化、历史回填、纯分析、materialization、HTTP/CLI 契约；`src/trading_system/` 的标准快照构建和证据映射。
- 前端：`apps/market-environment-dashboard/` 第 05 页及数据管理页的覆盖率、回填状态和唯一验证项展示。
- 数据与规则：可能新增 PostgreSQL 时点行业成员/日聚合表或等价 repository，保持 `trading-rules/` 中既有规则 ID、权重和 YAML 路径不变；本提案明确的相对强度、分歧事件和基准口径必须同步量化文档、规则 YAML、覆盖清单、测试和证据。
- 依赖：优先复用已安装的 `mootdx`、TDX 盘后包、现有统一 transport 和 capability gate；新的分类/复权来源必须先经离线 fixture 与授权盘后 probe，默认关闭且不得提交真实数据快照或凭据。
- 文档与运维：实现前创建 active exec plan，并同步产品规格、`docs/architecture.md`、`docs/runbooks.md`、`docs/repository-guide.md` 和 `docs/status.md`；历史回填、真实 probe、生产 rollout 和调度激活均需独立授权。
