## 1. 事实文档与执行计划

- [x] 1.1 创建 `docs/exec-plans/active/add-fuyao-ths-sector-datasets.md` 并更新 active 索引，确认 Stage、Status、Acceptance、Completion Evidence、Remaining Gaps、Next Step 齐全。
- [x] 1.2 更新产品规格，冻结三数据集、四类目录、四视图、历史/宽度边界与旧 `sectors` 迁移语义，并通过文档审阅确认与 delta specs 一致。
- [x] 1.3 更新架构与仓库映射，记录 normalized repository、collection DAG、Chapter 01 字段、代码归属和与申万连续性 change 的隔离，并运行架构/文档相关测试。
- [x] 1.4 更新 runbook 和状态，记录 Fuyao 官方动态接口索引及 2026-10-12 核对日期、显式操作/恢复/回滚/授权边界，并运行 docs-contract fast。

## 2. 领域契约与离线 fixture

- [x] 2.1 增加四类目录 revision/relation、共享 THS identity、日线 OHLCV/turnover、回填 run/checkpoint、成员事实和宽度结果的不可变领域模型，并用领域测试覆盖有限值、日期、唯一键和 null 语义。
- [x] 2.2 增加合成 Fuyao fixtures，覆盖四类目录、跨分类复用、重复/名称冲突、checksum/revision、完整/缺失 snapshot、日期漂移、历史 OHLCV/turnover 和 dump schema 漂移；验证 fixture 不含真实目录、凭据或预签名 URL。
- [x] 2.3 实现 catalog checksum、稳定排名、K 线规范化和当前日宽度纯函数，测试所有公式、稳定并列排序、零分母、MA20 不足、limits 缺失、Top 10 与用户选择去重。

## 3. Capability 与 Fuyao provider adapters

- [x] 3.1 为 catalog/snapshot、current constituents、one-code history、daily/incremental/adjustment dump 定义独立 capability policy，验证 disabled/missing/mismatch/unverified 时零 provider I/O 且证据经过脱敏。
- [x] 3.2 扩展 Fuyao adapter 支持 `industry`、`cn_concept`、`region`、`tszs` 目录和完整批量 snapshot，验证 100% 覆盖、唯一性、字段、上海日期和跨批时间戳。
- [x] 3.3 实现单 `thscode` 最多近五年的日线 adapter，完整保留 OHLC、`volume`、`turnover`，测试范围、重复日期、字段缺失、身份/日期不符和请求预算。
- [x] 3.4 实现 Fuyao dump/复权导入 reader 与 TDX 精确日期字段级降级组合，测试 schema/checksum/重复键、复权只作用于价格、混合来源 lineage 和 `partial/insufficient`。

## 4. PostgreSQL 持久化

- [x] 4.1 增加 additive Alembic migration 和 schema 定义，为目录 revision/relation、共享代码、当前成分关系、板块日线、成员事实、回填 run/checkpoint、宽度证据建立业务唯一键与查询索引，并验证 upgrade/rollback/migrate-again 与旧 `sectors` 行不变。
- [x] 4.2 扩展 application repository/UoW ports 与 PostgreSQL 实现，验证相同 checksum 幂等、不同 revision 共存、冲突不覆写、跨 tag 共享 bar 和事务回滚。
- [x] 4.3 增加 provider-free catalog、单编号 K 线、覆盖率和 operation progress queries，测试分类/名称/编号/revision/日期范围/分页且断言零 provider 调用。

## 5. 应用命令与三任务编排

- [x] 5.1 实现显式目录同步命令，将四类目录和完整 snapshot 原子写入 normalized repository，并验证日期、capability 和请求预算门禁。
- [x] 5.2 实现最多 60 编号、近五年、按代码/窗口 checkpoint 的可恢复历史回填命令，测试单编号失败隔离、续跑、预算耗尽、同编号幂等与冲突保留。
- [x] 5.3 实现显式成员事实导入命令，验证下载 URL/密钥/原始响应不落库不输出，且坏 schema/checksum 零正式写入。
- [x] 5.4 将公共 dataset 集合迁移为七项并实现 `industry-ranking -> sector-turnover -> sector-breadth` DAG、blocked 语义和兄弟失败隔离；测试 `sectors` 被明确拒绝且历史记录保留。
- [x] 5.5 增加三个 collector/committer/projector 并在任一成功提交后重建 Chapter 01，测试 sector-only run 能物化 aggregate 且失败不移除同日成功兄弟结果。

## 6. HTTP、CLI 与公共 schema

- [x] 6.1 增加 provider-free 目录、单编号 K 线和 operation progress GET schemas/routes，测试过滤、分页、本地覆盖范围、缺口与 OpenAPI 输出。
- [x] 6.2 增加受 manual-write、盘后、权限、预算和 capability revision 门禁的目录同步、历史回填和成员导入 POST/CLI，测试异步 run ID、错误脱敏和未授权零 I/O。
- [x] 6.3 更新 Chapter 01 Python/OpenAPI schema 为 `industryRanking`、`sectorTurnover`、`sectorBreadth`、`sectorAnalysis`，删除新响应的 `sectors` 并验证旧数据库证据不被迁移或投影。

## 7. 前端迁移

- [x] 7.1 更新 TypeScript collection dataset、Chapter 01 和本地查询/operation 类型与 API client，测试旧 `sectors` 不在支持枚举且错误消息包含迁移目标。
- [x] 7.2 用 `industry-ranking`、`sector-turnover`、`sector-breadth` 三个独立任务状态替换数据管理页的 `sectors` 展示，并测试进度、依赖失败、重试和 390px 无页面级溢出。
- [x] 7.3 将第 05 页实现为排名、板块宽度、量价 K 线、申万持续性四视图；K 线展示蜡烛、成交量和成交额，本地覆盖不足时提供显式回填操作，并测试 THS/申万视觉与语义隔离。
- [x] 7.4 核对所有新增可见文字、ECharts 图例/坐标/tooltip 不小于 14px，运行 Vitest、Vite build 和桌面/390px 浏览器截图检查。

## 8. 集成验证与收口

- [x] 8.1 运行后端 focused 测试，覆盖四目录、历史回填、dump/TDX lineage、宽度公式、任务依赖、聚合重建、旧证据保留和 provider-free GET。
- [x] 8.2 运行 `python -m pytest tests -q` 并记录结果；若受工作区既有 change 阻塞，保存精确失败和归属证据而不回退其修改。
- [x] 8.3 运行 rules validate、coverage、docs sync-check，确认 THS observation 未进入申万 `QTS-01-05-*` 输入且既有规则 ID/状态不变。
- [x] 8.4 运行 `openspec validate add-fuyao-ths-sector-datasets --strict` 和 `python scripts/check-docs-contract.py --mode=full`，更新 active plan 的 Status、Completion Evidence、Remaining Gaps、Next Step 与 `docs/status.md`。

## 9. 另行授权的真实操作

- [ ] 9.1 在上海盘后且再次明确授权后运行四类 catalog/snapshot、历史、dump/复权的隔离真实 probe，审阅并提升脱敏 capability revisions；在此之前保持 `unverified` 和零正式写入。
- [ ] 9.2 在再次明确授权后演练并执行生产 PostgreSQL migration、小批目录同步/历史回填/成员导入、部署与观察；默认调度继续保持 `enabled=false`、`suspend=true`。
