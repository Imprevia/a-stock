## 1. 事实文档与执行计划

- [x] 1.1 按 `docs/exec-plans/active/define-scope.md` 创建本变更 active exec plan，补齐 Stage、Status、Acceptance、Completion Evidence、Remaining Gaps、Next Step，并更新 `docs/exec-plans/active/_index.md` 与 `docs/status.md`；运行 `python scripts/check-docs-contract.py --mode=fast` 验证计划门禁通过。
- [x] 1.2 先更新 `docs/product-specs/market-environment-dashboard.md`，明确申万一级范围、五项指标、最多三个候选、唯一验证项、观察层与分析层分离以及 observation-only 降级；通过文档审阅确认字段、阶段和失败语义与 delta specs 一致。
- [x] 1.3 更新 `docs/architecture.md` 和 `docs/repository-guide.md`，记录时点行业数据流、PostgreSQL repository/UoW 边界、显式 backfill、`SectorEvidence.analysis`、snapshot v2 bridge 及代码—文档映射；运行架构门禁脚本确认没有新增反向依赖。
- [x] 1.4 更新 `docs/runbooks.md` 和 `docs/status.md`，记录离线 fixture 验证、能力报告、迁移、回填、恢复、回滚和额外授权边界，并确认普通 GET、启动、“全部采集”和默认调度均不会触发历史回填。
- [x] 1.5 同步 `搭建交易系统-量化版/01-如何判断市场环境/05.主线持续性和成交额集中度.md`、对应原版边界说明、`trading-rules/rule-sets/market-environment.yaml`、`trading-rules/coverage.yaml` 和证据引用，冻结 5/20 日相对强度取较低分位、负收益日分歧事件与两日 50% 修复口径，同时保持规则 ID、权重、YAML 路径和 `needs-backtest` 状态；运行 rules validate、coverage 和 docs sync-check 验证同步。

## 2. 数据源能力与离线证据

- [x] 2.1 为 `shenwan-taxonomy`、`shenwan-point-in-time-membership`、`stock-adjusted-price`、`tdx-original-daily-facts`、`benchmark-history` 定义独立 capability report 契约，包含精确日期、市场覆盖、字段语义、版本/checksum、分页完整性、权限/限频、数据权利和负例；用 schema/模型单测验证 `eligible | ineligible | unverified` 及敏感信息拒绝规则。
- [x] 2.2 建立不含真实生产快照的固定 fixture，覆盖申万分类变迁、股票跨行业生效区间、北交所 `920xxx` 身份、退市/停牌、已知除权除息样本、TDX 原始成交额、基准缺口、重复和混合日期；运行 fixture 解析测试验证样本可离线重放。
- [x] 2.3 实现版本化的申万 taxonomy/membership operator import 适配器，拒绝概念/题材、重叠一级行业、缺少生效区间和 checksum 的输入；用导入成功、重复幂等、区间冲突和许可元数据缺失测试验证 fail-closed 行为。
- [x] 2.4 实现前复权价格与 benchmark 的 provider-neutral adapter/capability gate，并为 Baostock、mootdx/除权数据或后续来源保留独立 revision；用沪深北覆盖缺口、公司行动连续性、权限失败、限流、字段漂移和日期不符 fixture 验证未获批来源产生零正式写入。
- [x] 2.5 增加显式 `--allow-real` 的隔离盘后 probe 命令与脱敏报告输出，但默认关闭且禁止写正式快照/分析表；用命令解析和 fake provider 测试证明未授权、盘中、权限不足和混合日期时均 fail closed。
- [x] 2.6 在 runbook/能力报告中分别记录客户端代码许可证和底层数据使用条款，特别核对申万公开表、Baostock、mootdx、Tushare/JQData 候选源的自动采集、长期存储和派生展示边界；通过文档审阅确认附件仅作为候选源目录而非批准证据。

## 3. 时点行业领域模型与持久化

- [x] 3.1 在 domain/application ports 中增加 taxonomy revision、industry identity、membership interval、security daily fact、benchmark fact、industry aggregate、continuity result、backfill run/date attempt 的不可变模型与 repository 协议；运行类型/领域单测验证日期、区间、版本和有限数约束。
- [x] 3.2 增加 additive PostgreSQL migration，为六类记录建立精确业务键、版本/checksum、有效区间、日期和查询索引，并确保原始成交额与前复权价格分列保存；在隔离数据库运行 upgrade/rollback/migrate-again 测试验证不触碰现有五数据集数据。
- [x] 3.3 实现 PostgreSQL repositories 并接入现有 `MarketEnvironmentUnitOfWork`，保证相同证据幂等、不同 revision 共存、不同 checksum 形成显式冲突；运行 repository/UoW 事务回滚和并发唯一性测试。
- [x] 3.4 实现精确日期 membership 解析和 canonical security identity 规则，覆盖改名、行业切换、退市及北交所代码迁移；用未来 membership、区间边界、重复归属和缺失归属测试证明不使用当前成分回填历史。
- [x] 3.5 为事实和聚合输出统一 lineage/quality 模型，包含 requested/actual date、source/revision、domain versions、counts、field availability、checksum、fetch/import time 和 warnings；用缺少关键 lineage、非有限值和零值替代负例验证不能标记为 `ok`。

## 4. 精确日期事实与行业日聚合

- [x] 4.1 复用现有 TDX daily-package normalizer，将审核后的普通 A 股原始 OHLC、昨收、volume 和 amount 写入时点事实仓库，并保留上海/深圳/北京计数、排除原因、source revision 与 checksum；运行现有 TDX 套件及新增精确日期/重复身份/amount 缺失测试。
- [x] 4.2 将前复权价格写入与原始 amount 独立的版本字段，禁止对 amount 应用复权因子或用 volume 代替；用公司行动样本和“价格缺失但 amount 可用 / amount 缺失但价格可用”测试验证指标级降级。
- [x] 4.3 按固定 `ordinary-a-share-equal-weight-v1` 口径从同一普通 A 股 universe 的有效前复权日收益生成 exact-session benchmark facts，并按同样等权口径生成行业收益；用缺日、错日、错 revision、成员缺失和替代 benchmark 负例验证只让相对强度保持 `null`。
- [x] 4.4 实现申万一级行业日聚合纯函数，按同一 as-of、同一普通 A 股 universe 和时点 membership 生成收益、原始成交额、MA20 宽度输入、内部结构事实及全市场成交额；用成交额对账和重复归属测试证明每只股票最多计入一次。
- [x] 4.5 持久化聚合的 metric-specific eligible/excluded counts、原因、输入 checksum 和所有版本，并用同输入重复计算、未来事实存在、不同 universe 分母测试验证确定性和防前视。

## 5. 第 05 章连续性分析

- [x] 5.1 实现 `QTS-01-05-01` 的 5 日/20 日行业超额收益与各自滚动 midrank 分位，两窗均有效时才将较小值映射为 `sector.relative_strength_percentile`；用短强中弱、单窗缺失、并列值和基准缺失测试验证 trace 与 null 语义。
- [x] 5.2 实现 `QTS-01-05-02` 的最近 5 个有效交易日完整行业横截面成交额前 20% 天数，使用 `max(1, ceil(0.2*N))`、成交额降序和稳定行业 ID 并列裁决，固定输出 0–5 天并按既有 bands 评分；用并列排名、横截面缺行业和交易日不足测试验证确定性。
- [x] 5.3 实现 `QTS-01-05-03` 的前复权 `close > MA20` 有效成员比例及滚动分位；用上市不足 20 日、停牌、复权缺失和零分母测试验证无效成员不进入分母且结果不填 0。
- [x] 5.4 实现 `QTS-01-05-04` 的负收益分歧事件、两个后续完整交易日成熟条件和收复跌幅至少 50% 的承接率；用无事件、未成熟、恰好 50%、跨版本缺口测试验证事件 trace 和 `event-not-matured`/`zero-denominator` 原因。
- [x] 5.5 实现 `QTS-01-05-05` 的申万一级行业按原始成交额降序、稳定行业 ID 裁决并选择 `min(5,N)` 后计算去重成交额/同 universe 全市场原始成交额及滚动 midrank 分位；用并列、不足五行业、amount 缺失、分母不兼容和重复成员测试验证确定性与去重。
- [x] 5.6 实现每项分位独立的 60/250 有效观察门槛、经验 bands、原始/归一化权重、覆盖率与置信度，确保 60–249 为 `reduced-confidence`、少于 60 为 `insufficient`；运行边界值和部分指标可用测试。
- [x] 5.7 实现仅来自 exact-date canonical Shenwan identity 的最多三个候选、稳定排序、as-of 单交易日超额收益 top-quintile 诊断、唯一阶段优先级、三项核心得分门槛、连续三日确认和候选级 crowding veto，并把市场级 risk 映射到第一候选；用同分行业、未映射 observation、单日脉冲、确认 streak、风险输入缺失和 veto 优先测试。
- [x] 5.8 实现只包含成交排名、涨幅排名、涨跌停、贡献率和扩散比例的内部结构事实，确认没有代码路径生成“龙头/中军/补涨”角色；用高单股贡献和多股扩散 fixture 验证输出边界。
- [x] 5.9 实现确定性唯一验证项选择与固定文本渲染，覆盖数据恢复、宽度恢复、成熟分歧承接、下一次分歧和无候选五级优先级；用多候选、抱团、关键输入缺失和无 canonical 候选测试证明始终恰好一条、无候选时 `candidateIndustry=null` 且条件含明确恢复目标或数值阈值。
- [x] 5.10 增加完整的防前视、相同输入重放、版本变化、缺失/null、未来数据隔离和规范化字节测试，验证候选、阶段、veto、验证文本和 checksum 可重复。

## 6. 显式历史回填与状态管理

- [x] 6.1 实现独立 backfill application service，按权威交易日历解析任意显式有限范围，首次预热默认 272 个交易日并允许小范围修复或更长研究范围，固定所有 source/domain revisions，并按日期执行输入、聚合、分析阶段；用固定日历测试验证不按自然日倒推。
- [x] 6.2 实现 parent run 与 per-date attempt 的 `success`、`partial`、`failed-retained`、`failed-missing`、`insufficient` 状态和 retry eligibility；用单日失败不影响其他日期、同日兼容结果留存和无兼容结果测试验证隔离。
- [x] 6.3 增加显式 CLI 命令，要求有界日期/交易日数量、批准 revision 和可恢复 run identity，且不把 backfill 加入 `SUPPORTED_COLLECTION_DATASETS`；用 CLI 测试验证普通五数据集“全部采集”仍只创建五个任务。
- [x] 6.4 实现幂等 resume、已成功日期跳过、未完成日期重试和新 revision 新结果逻辑；用中断恢复、重复运行、checksum 冲突和版本切换测试验证不静默重写证据。
- [x] 6.5 增加 provider-free backfill/readiness 查询投影，返回 required/available history、missing sessions、覆盖率、版本、warnings 和最近 attempt；用零 provider fake 测试验证状态读取、Dashboard GET 和启动路径不会触发采集。

## 7. Materialization 与后端 API

- [x] 7.1 为后端新增独立的 analysis quality、history、metric trace、candidate、risk、internal structure、unique validation 和 attempt Pydantic 契约，并将 `analysis` 作为 `SectorEvidence` 可选字段；运行 schema 测试确认旧 observation-only payload 仍有效。
- [x] 7.2 将兼容的同日 continuity result 接入 exact-date materialization，保持 provider observation 的 `rows/state/quality` 原样，并分别投影分析状态与 lineage；用 exact-date observation 成功/analysis 不足、analysis failed-retained 和 failed-missing 测试验证互不遮蔽。
- [x] 7.3 扩展 chapter-01 sectors section 和 collection-status DTO，使本地读取暴露分析 readiness/backfill progress 而不发 provider 请求；运行 HTTP characterization 测试验证 as-of 严格一致和跨日期结果不替代。
- [x] 7.4 增加观察层 identity mapping 的可选 exact-date association 输出，保留 provider 与 Shenwan 双身份及 mapping revision，且模糊/冲突时不关联；用同名不等价、多个候选和过期映射测试验证不会按名称猜测。
- [x] 7.5 运行 market-environment focused pytest，覆盖 persistence、aggregation、analysis、backfill、materialization、HTTP/CLI 与现有 sectors fallback/enrichment 回归，并记录命令和通过数量到 active plan Completion Evidence。

## 8. 第 05 页与数据管理前端

- [x] 8.1 扩展 TypeScript contract，区分现有 provider observation wrapper 与新的 continuity analysis，增加 quality/history/metric/candidate/unique-validation 类型；运行 `npm run test` 中的类型消费测试确认旧 fixture 无需 analysis 字段。
- [x] 8.2 重构 `Document05SectorsPage.vue`，展示五项规则证据、候选阶段、crowding 风险、内部结构事实、历史覆盖和唯一验证项，同时只在日期被证明时保留 selected-date provider 行业表及 enrichment 告警；用 Vitest 验证完整、部分、insufficient、observation-only 和历史日期不混入今日排名五种状态。
- [x] 8.3 在数据管理页只读展示 sector analysis readiness、backfill progress、缺失日期和 retry eligibility，不把 backfill 放入“全部重新采集”或单数据集重试；用交互测试验证现有五数据集动作集合不变。
- [x] 8.4 增加桌面和 390px 视口测试，验证所有可见文字不小于 14px、页面无横向溢出/重叠/截断且宽表仅自身滚动；运行相关 Vitest DOM/layout 断言。
- [x] 8.5 在 `apps/market-environment-dashboard/` 运行 `npm run test` 和 `npm run build`，将结果记录到 active plan；任何未运行检查必须写入 Remaining Gaps。

## 9. 交易规则快照桥接

- [x] 9.1 将 canonical snapshot schema 演进为 v2，显式增加 closed `metricProvenance` 契约并继续接受冻结的 v1 replay；用 JSON Schema 测试验证 v1 fixture、合法 v2、未知字段和缺失 sector provenance。
- [x] 9.2 更新 `create_after_market_snapshot` 或新的应用层 builder，使其只从本地同日 materialized analysis 复制五个 canonical sector metrics 和 provenance：前四项取第一 canonical 候选、集中度取市场值，无候选时前四项为空；不自行重算、不发 provider 请求，并用 fake service 测试 complete、partial、无候选、observation-only 和 as-of mismatch。
- [x] 9.3 将 data/classification/membership/universe/adjustment/benchmark/calculation 和上游 immutable evidence revisions 纳入 normalized snapshot 与 hash，并保留 rule-set/rule/code versions、排除当前输出 bundle ID；用数值相同但 provenance revision 不同及 bundle 自引用负例验证 snapshot identity 改变且无哈希循环。
- [x] 9.4 验证 `QTS-01-05-01..05` 使用既有 evaluator、输入名、权重、veto 和缺失策略，生产 bridge 上线不改变规则 ID 或升级校准状态；运行规则 evaluator focused tests 检查 individual traces、coverage、confidence 和 crowding veto。
- [x] 9.5 更新 trading-system fixtures/golden evidence，增加完整 v2、部分 sector metrics 和 observation-only 三类快照；运行 golden replay 两次确认结果字节、snapshot hash、traces 和 evidence bundle 确定性。

## 10. 全量离线验证与收尾

- [x] 10.1 运行新增 focused tests、`python -m pytest tests -q` 和市场环境架构门禁，修复回归并把完整命令/结果写入 active plan Completion Evidence。
- [x] 10.2 运行 `python -m src.trading_system.cli rules validate`、`python -m src.trading_system.cli rules coverage`、`python -m src.trading_system.cli docs sync-check`，确认规则、量化文档、覆盖和证据引用一致。
- [x] 10.3 运行 `openspec validate add-sector-continuity-metrics --type change --strict --no-interactive`，确认所有 capability、requirement 和 scenario 严格有效。
- [x] 10.4 运行 `python scripts/check-docs-contract.py --mode=full`，并复核 git diff 不包含凭据、真实数据快照、运行时产物、默认启用调度或无关工作树改动。
- [x] 10.5 更新 active plan 的 Status、Completion Evidence、Remaining Gaps、Next Step 和 `docs/status.md`；只有实现、离线验证和文档门禁均完成后才将实现阶段标记完成，未获授权的真实操作保留为明确缺口。

## 11. 需另行授权的条件性运维操作

- [ ] 11.1 仅在用户明确授权后，于盘后隔离环境运行真实 taxonomy/membership/adjusted-price/benchmark capability probes，审阅脱敏报告、数据条款和 revision/checksum；未授权时保持 `unverified` 且所有真实 provider 开关关闭。
- [ ] 11.2 仅在用户明确授权后，对指定非生产或生产数据库执行 additive migration 与小范围历史回填，核对精确日期、覆盖率、金额对账、checksum 和恢复行为后再分阶段扩展至 60 和 272 个交易日；不得删除或覆盖既有证据。
- [ ] 11.3 仅在用户明确授权后执行生产部署，先离线渲染/校验清单并确认 `scheduledCollection.enabled=false`、`suspend=true`、PVC/数据库不变和回滚开关可用；部署后只做获批的只读健康/状态检查。
- [ ] 11.4 仅在用户再次明确授权且真实数据质量已审阅后，才可单独评估或激活任何历史分析调度；验证最小权限、失败留存和配置回滚，且不得把调度激活与普通实现提交合并执行。
