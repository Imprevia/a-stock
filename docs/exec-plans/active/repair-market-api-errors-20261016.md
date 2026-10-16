# 修复市场环境 API 错误与 2026-10-16 core 错位快照

## Stage（阶段）

代码修复、生产停写、备份恢复演练、不可变镜像发布、同日前向重采、接口验收和 writer 恢复均已完成。

## Status（状态）

`completed-with-production-repair`

## Scope（范围）

- 修复 PostgreSQL `limits/pools/{pool_type}` 首页无 cursor 时绑定无类型 `NULL` 导致的 `AmbiguousParameter`。
- 补充首页与后续 cursor 页的 repository/HTTP 回归，保持排序、上限、revision 和 provider-free GET 合同不变。
- 从 clean reviewed commit 构建并发布不可变镜像，验证 `2026-10-15` limit-up pool 返回真实本地事实。
- 对生产 `2026-10-16` core 错位记录执行受控前向修复：先暂停 Hermes job、关闭 manual/automation 写入口、确认 writer=0，完成不可覆盖 PostgreSQL 备份及隔离恢复，再仅通过同日 provider 证据和 fenced commit/aggregate rebuild 覆盖。
- 保留旧 run/task/idempotency 审计；不直接编辑 payload/checksum，不重标、跨日期复制、删除历史/PVC 或伪造成功。

## Acceptance（验收）

- pool 首页 SQL 不绑定 `after_* = NULL`，真实 PostgreSQL 与测试均不再出现参数类型推断错误；合法 cursor 后续页仍按 `(exchange, code, security_id)` 严格分页。
- `/api/v2/market-environment/2026-10-15/limits/pools/limit_up?limit=20` 返回 HTTP 200、20 条以内真实事实和可继续使用的 cursor；GET 前后 provider/write 计数不变。
- 生产写前 manual/automation gate 均关闭、Hermes job 已暂停、active run/task/lease 为零；备份有 SHA-256、0400 sidecar 和全新隔离 PostgreSQL 16.4 单事务恢复证据。
- `2026-10-16` core 只在 provider 返回五个指数的同日日期证据时提交；否则保留 503 与真实失败/留存状态并停止，不降级为跨日期 200。
- 成功时 v2 overview 与 legacy core 返回 HTTP 200，snapshot key、payload/quality asOf、五个 history 尾日、materialized key/payload 和 revision/checksum 一致；失败时保持稳定脱敏 503。
- focused/full pytest、docs-contract full、`git diff --check`、部署离线门禁及发布后健康检查通过；生产 writer 恢复到授权前状态前再次确认无活动写入。

## 实施任务

- [x] 建立独立 active plan、登记索引并记录用户对代码发布和生产数据前向修复的明确授权。
- [x] 文档先行同步 architecture/runbook 的无 cursor PostgreSQL 查询合同与生产修复顺序。
- [x] 修复 pool 首页 SQL 并补无 cursor/有 cursor 回归。
- [x] 补齐并验证同镜像、无 hook、只允许 automation `1→0` 的受控停写入口。
- [x] 完成 focused/full 离线验证、docs-contract full 和 diff 检查。
- [x] 提交并推送 clean reviewed commit。
- [x] 暂停 Hermes job并关闭 backend manual/automation gate，确认 writer=0。
- [x] 创建不可覆盖 PostgreSQL 备份，校验 SHA-256，并在全新隔离 PostgreSQL 16.4 中恢复验收。
- [x] 用普通受控入口发布不可变镜像并验证 limit-up pool。
- [x] 在 Ready Pod 中显式执行 `2026-10-16` core 同日重采/重建；若 provider 日期不符则 fail closed。
- [x] 补齐只允许 CLI `--force --repair-integrity --dataset core` 的 fenced 前向替换，并修复完整性异常遗留 collecting run/task。
- [x] 修复 v2 index history 无日期/cursor 时 PostgreSQL 可选参数类型推断错误，并补首页 SQL 回归。
- [x] 验证 API、目标行日期证据、run/task、revision/checksum 与数据指纹，恢复授权前写入开关与 Hermes job 状态。
- [x] 回写 Completion Evidence、Remaining Gaps 和 Next Step，提交并推送生产证据。

## Completion Evidence（完成证据）

- 2026-10-16：用户在收到两个根因后明确回复“授权”，授权修复代码、提交推送、重新部署及按备份/停写门禁执行生产数据前向修复。
- 2026-10-16：只读诊断确认 overview 的 materialized key=`2026-10-16`、payload `asOf=2026-10-15`，接口稳定返回 503 `snapshot_integrity_error`；limit-up pool 直连后端为 PostgreSQL `AmbiguousParameter`，目标日期 36 条事实存在且日期正确。
- 2026-10-16：repository 已将 limits pool 首页与 cursor 后续页拆成两种 SQL；首页不含 `after_*` predicate/bind，后续页只绑定三个非空 cursor 分量。v2/read-adapter 聚焦回归 `22 passed`，市场环境架构门禁通过。
- 2026-10-16：在本机既有 PostgreSQL 16.4 镜像启动一次性 loopback-only 临时实例，真实 psycopg 执行首页与 `next_sort_key` 后续页均通过；第一页返回前两条 SSE 事实，第二页仅返回剩余 SZSE 事实，无 `AmbiguousParameter`、重复或遗漏，测试容器随后自动停止并删除。
- 2026-10-16：首次全量 pytest 为 `1516 passed, 6 skipped, 1 failed`，唯一失败是无关 legacy SQLite 缓存耗时断言 `0.686s < 0.5s`；该用例立即单独复跑通过。随后完整重跑结果 `1517 passed, 6 skipped, 1 warning`，warning 为既有 Starlette `BlockingPortal` 弃用提示。
- 2026-10-16：`.venv/bin/python scripts/check_market_environment_architecture.py`、rules validate、rules coverage、docs sync-check、docs-contract full（代码 2 / 文档 4 / plan 1）和 `git diff --check` 全部通过。
- 2026-10-16：生产只读 preflight 为 k3s `v1.26.6`、Helm 126 deployed、Dashboard/PostgreSQL 1/1、CronJob/Job absent、PVC/Secret UID 稳定、manual/automation=`1|1`、active run/task/lease=`0|0|0`；Hermes a-stock job 当日 16:05 自然运行成功后已按授权暂停，另外两个无关股票任务保持 active。
- 2026-10-16：新增对称 `--disable-automation-refresh` 受控入口，只允许完整 reviewed packet 中 automation `1→0`，要求 manual=0、writer=0、同一 frozen image、无 hook、stored/live 零漂移及 PVC/Secret identity 不变。部署/packet/guard 回归 `251 passed`，Helm strict lint、`bash -n`、docs-contract full 和 `git diff --check` 通过。
- 2026-10-17：新增 `--repair-integrity` 维护入口，仅接受 `--force --dataset core --history-sessions 1`；`CoreCommitRequest` replacement intent 只接受五个指数全部 success 的同日 candidate，坏 existing 仅在显式 intent 下跳过留存读取并经正常 repository upsert 重算 checksum。完整性异常现在落为 `failed-retained`、`SNAPSHOT_INTEGRITY_ERROR`，并结算 parent run；PostgreSQL/SQLite inactive-task expiry 同步结算 run。CLI application adapter 透传 repair intent。专属回归 `74 passed`，全量 pytest `1524 passed, 6 skipped, 1 warning`。
- 2026-10-17：发布后只读 smoke 发现 v2 index history 的三个可选日期参数在 PostgreSQL 首页面临 `AmbiguousParameter`；查询已对 `start/end/after` 显式 `CAST(... AS DATE)`，新增无 filter/cursor 回归，focused `17 passed`。
- 2026-10-17：代码修复分别以 `50e5cf9`、`b40de56`、`d12dae3` 提交并推送到 `origin/main`；最终 reviewed HEAD=`d12dae330e91c7e58500188acfd45a6d91516ddd`，全量 pytest=`1524 passed, 6 skipped`，docs-contract full 通过。
- 2026-10-17：Hermes job `ef7389b87a92` 暂停后，manual/automation 均关闭且 writer=`0|0|0`。生产备份 `/tmp/a-stock-repair-20261016.jZ6VVt/a-stock-pgdump-20261016T153812Z-helm128-schema11-pvc-6c426fc5-e69052c.dump` 为 4,054,134 bytes，SHA-256=`abf58de8b5e11bde1e30069af8161ad2b3528118b650858bec95985515535bf8`，已在全新 PostgreSQL 16.4 隔离容器 `a-stock-pg-recovery-repair-20261016T153812Z` 单事务恢复验收；备份、恢复容器和临时证据继续保留。
- 2026-10-17：不可变镜像 `localhost/a-stock-market-environment:20261017-005702-d12dae3` 发布完成，archive SHA-256=`4a4273de698dfaa1a710999f420cf2152e354835c3685dec84985faa6cfcf219`，containerd manifest digest=`sha256:28644467836cb5048e9be96005cdcb75bbaaf1334521c840655d685e4618d7e0`。最终恢复写入口的普通受控发布再次构建/导入同 tag，archive hash 与 manifest digest 均保持完全一致。
- 2026-10-17：唯一 provider-backed repair 命令生成 run `3450b03168db487cb7b99aafab0c9f34` / task `3e441420818543339fa0908dd7ab43da`，均为 `success`；五个指数 `sh000001/sh000300/sh000905/sz399001/sz399006` history 尾日均为 `2026-10-16`。旧 run `f97c007eb0e54972a955d464d7e568e0` 已结算为 `failed`，旧 task `052a78b1b6de4522acbe7005a0a4f046` 为 `failed-retained`、category=`worker-interrupted`。
- 2026-10-17：core snapshot checksum=`3bb13c87c56f82604dc4a6ca0e78ed1862a670a4bb0f0f77857f3620b0fea122`、payload `asOf=2026-10-16`；materialized aggregate checksum=`68dd5ef7337e5308499e4933b2083e575a8118317838c18925b54fef4a21dc79`、payload `asOf=2026-10-16`；交易日证据为 `2026-10-16 | previous=2026-10-15 | actual=2026-10-16`。
- 2026-10-17：automation 通过同镜像、无 hook 入口在 revision 141 恢复为 `1`；manual 通过普通受控 `component=all` 发布在 revisions 142/143/144 恢复为 `1`，其中 database hook、service rollout、完整 release 收敛各执行一次。最终 Pod `a-stock-54b994d888-knzb5` Ready、0 restart，manual/automation=`1|1`、writer=`0|0|0`、CronJob/Job absent，PVC UID `c03bc7f8-…` / `6c426fc5-…` 与 Secret UID `653a79bf-…` / `81b9d039-…` 未变。
- 2026-10-17：`/api/health`、`/api/v2/market-environment/2026-10-16/overview`、`/api/v2/market-environment/2026-10-15/limits/pools/limit_up?limit=20` 与 legacy core 均返回 HTTP 200。limit-up 的 36 条本地事实全部带 `invalid_reason=missing-board`，因此合同过滤后的 `items=[]`、`hasMore=false`，不再是数据库 503。
- 2026-10-17：Hermes job `ef7389b87a92` 已恢复为 active，下一次运行是 `2026-10-19T15:30:00+08:00`；未执行 `hermes cron run`，未额外调用 provider。

## Remaining Gaps（剩余缺口）

- 本次 503 修复、生产数据前向修复、部署和 writer 恢复无剩余缺口。
- limit-up pool 当前为空是 `missing-board` 数据质量事实，不属于本次接口错误；后续若要补 board 证据应另立范围，不能把无效事实直接暴露为有效涨停池成员。

## Next Step（下一步）

提交并推送本计划与 runbook 的最终生产证据；随后只读观察 Hermes 在 `2026-10-19 15:30 +08:00` 的下一次自然调度，不进行人工触发。
