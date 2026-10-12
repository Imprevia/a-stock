# Fuyao THS 行业与板块三数据集改造

## 目标

将历史 `sectors` 公共采集契约迁移为 `industry-ranking`、`sector-turnover`、`sector-breadth` 三个顶层数据集，建立四类 THS 目录、板块量价历史、当日内部结构和可恢复回填能力，同时保留旧快照作为不可改写的审计证据。

## 范围

包含：OpenSpec 工件、产品/架构/运维事实文档、PostgreSQL additive schema、领域模型与 repository、Fuyao adapter、显式 CLI/POST、collection 编排与 Chapter 01 聚合、公共 API、TypeScript 类型、数据管理页、第 05 页四视图、离线 fixture 与自动化验证。

默认排除：生产数据库迁移、生产部署、首次真实目录同步或历史回填、调度激活，以及将 THS 行业/概念/区域/特色指数映射为申万一级规则输入。真实 provider probe 仅在用户授权、上海结算后、隔离临时路径执行；本次 probe 证据不等于生产 capability promotion。

## Stage（阶段）

- 当前阶段：**真实 probe 已完成部分能力审阅，生产操作门禁阻塞**
- 阶段序列：OpenSpec → 事实文档 → 数据模型/持久化 → provider/应用编排 → API/CLI → 前端 → 全量验证 → 回写

## Status（状态）

`real-probe-completed-promotion-and-production-gates-blocked` · 用户已明确授权继续 task 9.1/9.2，且已在上海 15:10 结算边界后完成隔离真实 probe。current membership 与单编号历史报告通过本地 evidence policy 审阅；目录/快照、三类 dump 均为 `ineligible`，未晋升、未写生产数据库。生产 PostgreSQL migration、首次同步/回填/导入、部署和调度激活仍受备份、clean reviewed commit、镜像/渲染冻结和默认暂停门禁约束。

## 事实源

- `openspec/changes/add-fuyao-ths-sector-datasets/`
- `docs/product-specs/market-environment-dashboard.md`
- `docs/architecture.md`
- `docs/runbooks.md`
- `docs/repository-guide.md`
- `docs/status.md`
- Fuyao 动态接口索引：`https://fuyao.aicubes.cn/llms-full.txt`（最后核对：2026-10-12）

## 实施任务

- [x] 创建并严格验证 OpenSpec proposal、design、delta specs 与 tasks
- [x] 先同步产品规格、架构、runbook、仓库映射与状态记录
- [x] 建立四类版本化 THS 目录及排名、量价日线、回填 checkpoint 和宽度结果模型
- [x] 增加 additive PostgreSQL migration、repositories/UoW 与幂等/冲突语义
- [x] 实现三个独立 collection dataset、依赖顺序、失败隔离与 Chapter 01 聚合重建
- [x] 实现 provider-free 目录/K 线/进度 GET，以及受门禁保护的显式同步、回填和导入入口
- [x] 将公共 `sectors` 契约迁移到三个新数据集，保留旧数据库证据但不再调度或投影
- [x] 更新数据管理页与第 05 页四视图，验证桌面和 390px 响应式边界
- [x] 完成 focused/full 测试、前端测试/构建、规则三门禁、OpenSpec strict 和 docs-contract full
- [x] 补齐 task 9.1 的 THS real-probe 工具链：四类 catalog/snapshot、代表编号 current membership/单编号 history，以及 daily/incremental/adjustment dump 的临时下载、schema/checksum 探测和六份脱敏 capability reports
- [x] 为六个精确 THS revision 注册 promotion evidence policy；离线测试证明预签名 URL、API key、原始响应和临时 dump 不进入 stdout、报告或持久化 evidence
- [x] 修复 current membership 运行时断链：`catalog-sync` 在双 revision/capability 预检和总预算门禁后，同步四类 Top 10 与显式点选编号，逐编号隔离失败并调用 `put_sector_memberships`；增加独立 membership env/Helm 配置和消费测试
- [x] 按官方 dump schema 探测 daily/incremental 的 `thscode`、`date_ms` 与价格字段；adjustment 仅含公司行动事件项，在复权公式及前收盘证据实现前报告 `ineligible`，不得将 synthetic `adjustment_factor` fixture 晋升为真实能力

## Acceptance（验收）

- 四类目录保存 `tag`、`thscode`、名称、provider/fetch 时间、数量、checksum 和 revision；重复、跨分类和 revision 行为有离线测试。
- `industry-ranking` 只有在目录唯一、快照 100% 覆盖且上海交易日/时间戳一致时发布稳定排名。
- `sector-turnover` 保存 OHLC、`volume`、`turnover`，支持单编号最多近 5 年的按需、每批最多 60 编号、可恢复且不覆写已验证数据的历史回填。
- `sector-breadth` 仅发布当日每类 Top 10 与用户点选编号的完整内部结构，Fuyao dump 为主、TDX 精确日期为降级，并保留混合来源 lineage。
- collection 依赖为 `industry-ranking -> sector-turnover -> sector-breadth`，单项失败不抹除成功兄弟任务；首次成功后可重建 Chapter 01。
- 普通 GET 只读本地 PostgreSQL；外部请求、dump 导入和回填只能经显式、受授权/盘后/预算/capability revision 门禁的 POST 或 CLI 触发。
- 公共 API/TypeScript/调度/前端不再接受 `sectors`；旧快照仍可审计且不被重写为新数据集。
- Chapter 01 暴露 `industryRanking`、`sectorTurnover`、`sectorBreadth` 和独立 `sectorAnalysis`，THS observation 不进入申万一级 `QTS-01-05-*` 输入。
- 后端、前端、规则、OpenSpec 和 docs-contract 门禁通过；未执行的真实 provider/生产操作有明确记录。

## Completion Evidence（完成证据）

- OpenSpec apply 进度仍为 `30/32`；9.1 的 probe/tooling 子项已完成，但 capability apply/promotion 与 9.2 生产操作仍未完成。`openspec validate add-fuyao-ths-sector-datasets --strict` 通过。
- 后端 focused 回归（含 THS probe/dump/operations、capability promotion、DAG、HTTP、查询、部署契约）：`310 passed`；architecture gate `13 passed`，dump/promotion 回归 `59 passed`。最后一次全库回归在工作树收口前为 `1416 passed, 6 skipped`，仅暴露 direct-network architecture violation 与一次非确定性性能尖峰；两者均已修复/复核，受影响测试分别通过 `13 passed` 与 `1 passed`，未重新耗时运行整套全库。
- 前端 Vitest：`20 files / 139 tests passed`；Vite production build 通过，仅有既有大 chunk warning。Playwright 在 1440×1000 与 390×844 检查四视图：页面级 overflow 为 false、可见字号违规为 0、console/page error 为 0，桌面与移动 K 线 Canvas 均非空。
- Helm/部署清单测试：`190 passed`；Helm lint `1 chart(s) linted, 0 failed`，离线 template 成功。Deployment/CronJob 均注入 10 个 THS fail-closed 环境变量，CronJob 保持 `suspend=true`。
- 规则门禁通过：`rules validate` 为 49 条可执行规则，`rules coverage` / `docs sync-check` 均为 330 条文档规则、49 条可执行规则。交易快照桥接只读取独立 `sectorAnalysis`，测试证明 THS `industryRanking` 不进入 `QTS-01-05-*` 输入。
- `python scripts/check-docs-contract.py --mode=full` 与 `git diff --check` 通过。
- 2026-10-12 15:21（Asia/Shanghai）隔离真实 probe：`sector-membership` revision `fuyao-ths-membership-v1` 为 `eligible`（203 个成员，checksum `2c85bc56…99779`），`sector-turnover-history` revision `fuyao-ths-history-v1` 为 `eligible`（24 根 K 线，checksum `d61cab08…3f680`）。`industry-ranking` 因真实快照 `883401.TI` 缺少 `changePct` 为 `ineligible`；daily/incremental/adjustment dump 元数据均未提供 SHA-256，全部 `ineligible`。未执行 capability apply/promotion、正式事实写入或生产数据库变更。

## Remaining Gaps（剩余缺口）

- 真实 probe 已执行但 `industry-ranking` 仍因响应字段缺失为 `ineligible`；需 provider 契约修复或人工审阅后才能重新 probe/promotion。
- 真实 dump 元数据缺少 SHA-256，daily/incremental 无法下载并晋升；不得放宽 checksum 门禁。
- Fuyao adjustment dump 真实契约不直接提供 `adjustment_factor`；复权因子推导所需公式、公司行动顺序和前收盘证据尚未实现，因此 adjustment capability 必须保持 `ineligible`。
- membership/history 虽通过隔离 policy 审阅，但 promotion 尚未 apply 到生产 PostgreSQL；在 9.2 的备份、migration 和镜像冻结完成前不得写生产 capability 表。
- 生产 PostgreSQL 尚未执行 `0004`/`0005` migration；首次目录同步、历史回填、成员导入、部署与调度激活均未执行。
- 当前生产 release 仍保留历史 `sectors` fallback；仓库新公共运行时已退役该标识，生产切换必须在独立授权下完成备份、migration、suspended rollout 和回滚审阅。

## Next Step（下一步）

保留本次隔离 probe 的脱敏摘要；临时 report/evidence 已按数据边界清理，正式 promotion 前必须重新 probe 并保存受审报告。待 provider 修复后重新探测目录/dump；membership/history 的 capability apply 需在 9.2 的 clean reviewed commit、备份恢复演练、additive migration 和镜像冻结之后执行。随后才可进行 suspended rollout 与小批同步/回填/导入观察；默认调度保持 `enabled=false / suspend=true`。
