# 恢复 v2 涨跌停池成员读取

## Stage

本地读取修复与合成证据回归，对应 OpenSpec `restore-v2-limit-pool-membership`（17 项任务）。

## Status

completed-local-only（2026-10-27）：OpenSpec 17/17；已完成本地读取修复、主规格同步与隔离 PostgreSQL 合成验证，**未部署、未核对生产恢复**。

## Acceptance

- 三池 SQL 与领域 `membership_valid` 一致；有效身份和精确日期成员不因高级属性缺失或 `not-v1-pool` 消失，无效身份、日期、重复和跨池冲突仍排除。
- 连板分层独立依赖有效连续板数；缺失保持 null，不从聚合观察数补齐。
- 晋级使用可信相邻会话两日完整涨停集合的身份交集，校验完整度、支持的规则版本及 detail checksum 与 limits snapshot 的绑定，不增加旧 eligible 限制。
- 行级 warning、nullable 字段、池质量、failed-retained、稳定排序、limit+1、revision 与 cursor 契约保持一致；GET 不访问 provider、不写存储。
- 隔离 PostgreSQL 临时表/事务回滚实际执行生产 adapter SQL，覆盖三池矩阵、晋级、HTTP 和每日分层消费者；缺测试库时明确记录缺口，不视 skip 为通过。
- 先旧后新同步受影响主规格，保留旧变更独立扩展；受影响测试、OpenSpec strict、架构和 docs-contract full 门禁通过或明确记录阻塞。

## Scope

仅修改本地领域常量、PostgreSQL 读取投影、必要的兼容行为及合成测试、事实文档与主规格。无 schema migration、provider、新采集/调度入口、生产数据库、回填、部署或外部写入；不改变每日总结格式与经验阈值。

## Completion Evidence

- OpenSpec spec-driven：先旧后新合并两份主规格，保留旧 delta 独立场景并修订基础晋级与证券事实口径；本 change 补齐旧场景后 `openspec validate restore-v2-limit-pool-membership --strict --no-interactive` 通过，两份主规格单独 strict 通过。
- 领域共享不可变成员排除原因集合；PostgreSQL 三池先按身份、实际日期和成员原因参数化过滤再稳定排序/`limit + 1`，高级属性不足与 `not-v1-pool` 成员继续可见。行 warning/rowQuality、nullable 连板数和 failed-retained 与兼容明细一致。
- 晋级只读取可信相邻两日固定 manifest、snapshot 与 session 元数据并验证完整度、版本及 detail checksum 绑定；当前/前日复用成员谓词、收盘涨停用数据库实际整数标志，不加载全部事实。有效完整两日合成集合的晋级全页为 3、同 revision 聚合分子为 3；完整空前日返回 null 比率、零分母不足。
- 使用本次专属本地 PostgreSQL 16.4 空库（回环 127.0.0.1，端口 55439），通过 `MARKET_ENVIRONMENT_TEST_DATABASE_URL` 在临时表与事务回滚下执行生产 adapter 真实 SQL；GET SQL 监控拒绝 DML/全量事实读取，provider 调用监控为零。测试数据均为合成身份和日期，未使用真实快照或外部行情。
- `.venv/bin/python -m pytest` 针对十个受影响文件：**274 passed、0 skipped**；补充 v2 queries/shared contracts、PostgreSQL pools 和每日分层四个文件：**118 passed、0 skipped**。每日分层的两种输入经内存 HTTP 与 PostgreSQL adapter：高/中/低各 4 个冻结样本的四类结果各为 1/1/1/1；失败样本修复为 1/2；缺连续板数成员保留可见但不计入任一梯队。只有现有 Starlette/anyio 的 DeprecationWarning。
- `.venv/bin/python scripts/check_market_environment_architecture.py`、`.venv/bin/python scripts/check-docs-contract.py --mode=full`（代码 14 / 文档 24 / plan 10）与 `git diff --check` 均通过；无门禁豁免。未运行全仓库 pytest、前端构建或真实 provider smoke，本次未改前端或运行时采集路径。

## Remaining Gaps

- 本地合成测试证明代码读取语义，不能证明存量生产快照覆盖所有目标日、连续板数齐全或高级属性完整。
- 生产镜像部署、真实环境的只读目标日/前日全页恢复核对、真实 provider 调用与任何数据库/集群写入都未授权、未执行；不把本阶段标成生产恢复。无 migration、重采、回填或采集调度变更。

## Next Step

若需要生产恢复，另行制定并授权部署/只读核对计划；按 runbook 核查目标日及可信前日三池与晋级的每页身份、日期、revision、来源、池质量、warning 和每日分层结果。任何真实缺口保持 `missing`/`insufficient`，不得用 GET、其他日期或聚合观察数补齐。
