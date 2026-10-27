## Context

动机见 [proposal.md](proposal.md)。本设计涉及领域成员规则、PostgreSQL 投影及跨层验证，且需要处理旧主规格与已实现基础晋级口径的冲突，因此保留独立设计制品。

已核查的实现事实：

- `domain/policies/limit_facts.py` 的 `LimitSecurityFactRecord.membership_valid` 检查非空证券身份、精确实际日期，并排除身份、日期、重复和跨池冲突；成员无效原因集合目前位于 property 内部。
- `infrastructure/persistence/postgres/v2_market_data.py` 的 `limits_pool` 对所有池额外要求 `invalid_reason IS NULL`。其 `promoted` 子查询只检查前日身份和收盘涨停，未完整复用前日成员有效性及完整集合门禁。
- `limit_promotion.py` 已以两日 `membership_complete`、实际日期、规则版本及 limits snapshot 的 detail checksum 绑定作为基础晋级门槛，再计算两日有效涨停身份交集。`limit_ecosystem.py` 的证券明细沿用这一口径，且将 `invalid_reason` 合并入行级 warning。
- v2 兼容适配器直接读取上述聚合明细；生产 PostgreSQL 适配器从事实表分页读取。这两个读取入口产生了语义漂移。
- `tests/test_market_environment_v2_read_adapters.py` 的模拟连接不执行 SQL WHERE；HTTP resource 测试主要走兼容适配器。`test_market_environment_v2_postgres_history.py` 已提供通过 `MARKET_ENVIRONMENT_TEST_DATABASE_URL` 连接隔离 PostgreSQL、临时表和事务回滚的测试模式，可复用。
- 每日分层脚本按上一交易日连续板数冻结样本，仅支持 4 板及以上、2 至 3 板和首板；它已分页读取 v2 三池，不需要另设计算口径。

## Goals / Non-Goals

**Goals:**

- 同一已存储成员在领域集合、legacy 明细、兼容 v2 和 PostgreSQL v2 中具有一致可见性。
- 池成员、连续板分层及高级资格分别使用自己的证据门槛。
- 在 SQL 分页前完成有效成员过滤，并保持普通 GET 的只读、有界和 revision 一致性。
- 用实际 PostgreSQL 执行结果验证根因修复，再验证这些结果能进入既有分层计算。

**Non-Goals:**

- 不新增数据库字段、索引、迁移、provider 或调度路径；不调用采集、回填或生产写接口。
- 不修复 Fuyao 单行身份不一致导致整体降级的问题，不扩大为 provider 容错重构。
- 不新增分层阈值、推荐、预测或输出格式，不把缺失高级属性伪装成完整证据。

## Decisions

### 1. 以领域成员规则为唯一过滤语义

将现有成员无效原因集合提升为领域模块中的不可变常量，供 `membership_valid` 和 PostgreSQL 适配器共同使用；不创建 SQL 依赖领域层的反向引用。SQL 对非空 `security_id/code/exchange`、`actual_as_of = as_of` 和排除原因逐项与 property 对齐。

SQL 的原因判断必须显式允许 null，再排除共享集合；不能直接用 `NOT IN` 而让 SQL 的 null 三值逻辑再次过滤正常行。参数化绑定原因值，静态且受控的 alias 仅供当前和前日谓词复用。所有谓词在稳定排序和 `LIMIT limit+1` 前执行。

未采用直接删除 `invalid_reason` 条件，因为它会泄漏冲突成员；未采用先取页再用 Python 过滤，因为它会导致短页、提前结束和遗漏有效成员；未采用独立复制原因清单，因为两个入口会继续漂移。

### 2. 晋级池对齐已实现的基础交集和门禁

保留现有基础晋级规则版本与 `closed_limit_up=true` 语义，不添加旧 `eligible` 过滤。当前及前日别名均采用同一个成员谓词，前日仅由可信 `trading_sessions.previous_as_of` 解析，不搜索更早交易日。

在有界事实查询前，通过现有 PostgreSQL repository 读取两日 manifest、limits snapshot 和 trading-session 证据，校验实际日期、`membership_complete`、受支持规则版本和 detail checksum 绑定。复用已有快照/会话完整性错误，不在 query 中调用 provider 或 `get_facts()` 全量物化事实；不以 legacy 大聚合明细代替数据库分页。

缺集合、旧 manifest 的完整度为 null 或规则版本不支持时，沿用明确 missing/insufficient 质量和空明细；已存证据的校验和或日期完整性错误沿用 `snapshot_integrity_error`。真实完整零分母继续是空晋级集合、null 比率和 zero-denominator 不足。有效两日证据下，全部晋级页的身份集合必须与现有聚合分子一致。

未采用“严格 eligible 分子/分母”，因为这会撤销已完成的基础晋级修复；未采用只检查前日 `closed_limit_up`，因为冲突或错日期行仍可能证明虚假晋级。

### 3. 保留行级解释与池级质量，不扩展响应模式

继续使用当前的 `securityId`、`streakDays`、`rowQuality`、`warnings` 等字段。PostgreSQL 投影按现有 `_detail_row` 规则，在 warning 中补入未出现的 `invalid_reason`，保留 nullable 字段，并对齐已有 rowQuality 的缺失回退语义；不新增必填字段，不把 pool 成员有效解释为晋级资格完整。

池质量和 `failed-retained` 优先级继续由原存储证据传播，不因 SQL 恢复可见成员而升级。`observations` 保持数据集口径，分页 `returned` 保持本页口径，不强行把两者相等作为成功条件；只在完整合成集合、同一日期与版本下验证全页成员数与对应总数一致。缺 `streakDays` 的涨停成员仍可见，但分层脚本不得把它计为首板或用 aggregate 计数补齐。

相比增量暴露 `eligible/invalidReason/membershipValid`，本次先复用既有解释字段，减少消费者契约扩张。

### 4. 将实际执行 SQL 纳入验收

新增独立 pool PostgreSQL 集成测试文件，复用既有隔离测试 URL、临时表及事务回滚模式。合成样本包括：高级属性不足、`not-v1-pool`、无效身份、错/缺实际日期、重复和跨池冲突、真实空池、跨页有效行及前日无效行。

以领域 property 产生期望身份集合，对照真实 SQL 的全页结果；以现有基础晋级计算产生期望交集，对照晋级明细。针对合法合成业务数据分别验证 legacy 和 v2；不能把故意破坏校验和的原始 SQL 注入案例当作合法 legacy 聚合输入。

HTTP 测试至少一条走 PostgreSQL read adapter 到 v2 router，再用内存 transport 将同一合成两日证据交给每日分层脚本，核对冻结样本、四类结果守恒、失败样本修复分子/分母及缺连续板数的不足提示。测试拦截 provider 构造/请求和 GET 期间 DML，建立测试数据的事务写入不计为 GET 写入。

保留既有 SQL 结构、cursor、409、retained warning 测试；增加真实查询而非只断言 SQL 文本。缺测试数据库时明确记录 integration skipped，不能把它计作根因验收通过；不得改用生产数据库。

### 5. 协调规格事实源，不覆盖已完成变更

`docs/architecture.md` 和 `docs/runbooks.md` 已记载基础晋级不依赖高级属性，主规格却仍要求旧资格。实施阶段先创建 active plan 并同步 docs，再核对已完成 `restore-limit-ecosystem-data-availability` 的 delta；主规格中本次涉及的两个 requirement 以本变更最新增量为准，保留旧变更对其他 requirements 的独立扩展。后续同步或归档必须按先旧后新的顺序合并，禁止由旧 delta 把新规则覆盖回去。

本提案阶段仅写本 change 制品；事实文档、主规格同步及实现均列入 apply 任务，不提前执行。

## Risks / Trade-offs

- [恢复明细后仍可能有真实数据缺口] -> 只承诺修复成员过滤；连续板数、前日集合和高级属性仍各自按证据降级，不承诺所有历史日期可生成完整总结。
- [过滤过宽导致冲突行可见] -> 共享领域原因集合，增加所有成员无效原因及缺身份/日期的 property-versus-SQL 对照测试。
- [晋级明细与分子漂移] -> 两日使用相同成员门槛和绑定检查，验证完整分页集合与聚合一致；零分母独立验证。
- [有界查询退化成全量加载] -> metadata 只读固定两日证据；成员过滤和分页留在 SQL，不复用会全量读取事实的 detail 方法。
- [修复后 warning 被丢失或质量被升级] -> PostgreSQL 与兼容路径对照行 warning、pool status 和 failed-retained；不根据结果非空重算质量。
- [隔离 PostgreSQL 不可用] -> 运行现有离线测试，单独记录真实 SQL 验收缺口；不访问非测试数据库补齐。
- [旧 OpenSpec delta 后续覆盖新口径] -> 明确合并顺序和两份 delta 的重叠 requirement，并在任务中复核最终主规格。

## Migration Plan

1. Apply 阶段先建立并登记 active plan，更新对应产品、架构、运行手册及必要映射，再实施代码和测试。
2. 在隔离 PostgreSQL 和离线测试环境完成合同验收；补齐 plan 的 Status、Completion Evidence、Remaining Gaps 和 Next Step，通过 docs-contract gate。
3. 无数据迁移，不要求重采或重建历史聚合。生产部署需另行明确授权，按 runbook 执行；可在获准部署后只读核对目标日及前一交易日的全部池页、来源、质量和分层结果，不把本地合成测试宣称为生产恢复。
4. 回滚仅回退应用版本；不删除或修改事实表、快照、PVC 和运行记录。回滚到旧查询会重新出现空池，因此须如实标注该行为。
