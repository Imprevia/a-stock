## 1. 执行计划与事实文档

- [x] 1.1 创建 `docs/exec-plans/active/restore-v2-limit-pool-membership.md` 并登记 `_index.md`，写明 Stage、Status、Acceptance、Completion Evidence、Remaining Gaps、Next Step；验收检查字段齐全、实现边界仅含本地读取修复及合成测试。
- [x] 1.2 在代码改动前同步 `docs/architecture.md`、`docs/product-specs/market-environment-dashboard.md`、`docs/runbooks.md` 和必要的 `docs/repository-guide.md` 映射，说明成员/连板/高级属性边界、晋级口径、隔离测试与无生产写入；验收逐项对应本 change 的两份 delta，且不新增采集或调度入口。
- [x] 1.3 协调已完成 `restore-limit-ecosystem-data-availability` 与本次主规格同步，按先旧后新顺序保留既有独立扩展，更新重叠的晋级和证券事实 requirements；验收主规格不再以高级属性完整作为基础晋级或连板梯队的前置条件，两份相关规格通过 OpenSpec 校验。

## 2. 成员有效性与 PostgreSQL 池投影

- [x] 2.1 将 `limit_facts.py` 中成员无效原因提取为不可变领域常量并供原 property 复用，不改变归一化和旧 eligible 值；验收 `tests/test_market_environment_limit_facts.py`、`test_market_environment_limit_fixtures.py` 覆盖原有效/无效结果且通过。
- [x] 2.2 在 `v2_market_data.py` 使用共享原因集和参数化 SQL，按非空身份、精确实际日期与成员原因过滤三类池，显式允许 null 原因，在排序及 `limit+1` 前完成过滤；验收 adapter 测试保留有界参数和 cursor 约束，且不再使用 `invalid_reason IS NULL` 作为唯一资格过滤。
- [x] 2.3 对齐 PostgreSQL 行投影与现有 `_detail_row` 的 `rowQuality`/warning 行为，补入未出现的存储排除原因，保持 nullable 字段与 API 字段形状；验收兼容适配器对照测试覆盖原因 warning 去重、缺连板数、池级 degraded 与 failed-retained 传播。

## 3. 晋级池与聚合一致性

- [x] 3.1 在晋级 SQL 当前/前日别名复用成员有效性谓词，仅由可信相邻会话解析前日，保留收盘涨停条件且不添加旧 eligible 限制；验收案例覆盖高级属性缺失仍晋级，以及前日身份/日期/重复/跨池冲突不能证明晋级。
- [x] 3.2 复用 PostgreSQL manifest、snapshot、trading-session 的固定两日证据读取，补齐集合完整度、规则版本和 detail checksum 绑定校验，不全量加载事实；验收缺 manifest、完整度 null/false、版本不支持返回不足，校验和/存储日期完整性失败返回既有完整性错误，普通读取无 provider 或 DML。
- [x] 3.3 保持合法零分母及同日失败保留语义；验收完整空前日返回空晋级集合、null 比率和 zero-denominator 质量，合法合成非空集合的晋级全页身份数等于同 revision 的聚合分子。

## 4. 真实 SQL 与消费者回归

- [x] 4.1 新增 `tests/test_market_environment_v2_postgres_pools.py`，使用既有 `MARKET_ENVIRONMENT_TEST_DATABASE_URL` 隔离 PostgreSQL、临时表与事务回滚模式；验收至少实际执行一次原生产 adapter 的 pool SQL，不用 mock execute 替代过滤，缺测试数据库时明确 skip 且记录验收缺口。
- [x] 4.2 构造三类池的高级属性不足、`not-v1-pool`、null 原因、各类成员无效原因、缺身份、缺/错实际日期的合成矩阵；验收真实 SQL 全页身份集合与领域 `membership_valid` 期望集合一致，合法输入下与 legacy/兼容明细集合一致。
- [x] 4.3 验证晋级两日合成集合的完整性和聚合绑定、前日无效行、真实零分母，以及混合有效/无效行跨页；验收无重复、无遗漏、无提前分页结束，顺序稳定，分子与全页晋级成员一致。
- [x] 4.4 增加经过 PostgreSQL adapter 的 HTTP v2 回归，覆盖保留质量、日期、revision pinning、cursor 续页、409 和完整性错误；验收响应沿用现有形状，并通过测试监控证明 GET 期间 provider 调用与数据库写入均为零。
- [x] 4.5 用内存 transport 把同一两日合成 HTTP 证据交给每日分层脚本，覆盖高级属性不足但连板有效及缺连续板数两组；验收冻结高/中/低样本的四类结果之和等于各自分母、修复率分子/分母准确，且缺连板数不被 aggregate 总数补齐。只增加测试，不改总结格式或经验阈值。

## 5. 综合验证与交付记录

- [x] 5.1 运行受影响的 limit facts/promotion/ecosystem、v2 read adapter/resource/contract、每日分层 Skill 测试及新增 PostgreSQL pool 集成测试；验收全部必要用例通过，真实 SQL 测试不得以 skipped 宣称通过，未运行或阻塞检查逐项记录。
- [x] 5.2 运行 `openspec validate restore-v2-limit-pool-membership --strict`、`python scripts/check_market_environment_architecture.py` 和 `python scripts/check-docs-contract.py --mode=full`；验收命令通过或明确记录阻塞，不修改门禁以绕过失败。
- [x] 5.3 更新 active plan 的 Status、Completion Evidence、Remaining Gaps 和 Next Step，按需要同步 `docs/status.md`；验收区分本地实现验证与尚未授权的生产部署/只读恢复核对，不记录真实快照、凭据或 provider 原始响应，也不把本次任务标成生产恢复。
