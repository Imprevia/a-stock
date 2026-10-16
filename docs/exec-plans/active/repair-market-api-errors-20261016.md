# 修复市场环境 API 错误与 2026-10-16 core 错位快照

## Stage（阶段）

计划与生产授权已确认，离线代码修复和全量验证完成；生产停写、备份、发布和前向重采尚未开始。

## Status（状态）

`authorized-code-complete-production-repair-pending`

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
- [ ] 暂停 Hermes job并关闭 backend manual/automation gate，确认 writer=0。
- [ ] 创建不可覆盖 PostgreSQL 备份，校验 SHA-256，并在全新隔离 PostgreSQL 16.4 中恢复验收。
- [ ] 用普通受控入口发布不可变镜像并验证 limit-up pool。
- [ ] 在 Ready Pod 中显式执行 `2026-10-16` core 同日重采/重建；若 provider 日期不符则 fail closed。
- [x] 补齐只允许 CLI `--force --repair-integrity --dataset core` 的 fenced 前向替换，并修复完整性异常遗留 collecting run/task。
- [ ] 验证 API、目标行日期证据、run/task、revision/checksum 与数据指纹，恢复授权前写入开关与 Hermes job 状态。
- [ ] 回写 Completion Evidence、Remaining Gaps 和 Next Step，提交并推送生产证据。

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

## Remaining Gaps（剩余缺口）

- SQL 修复、测试和完整性修复代码已完成；提交、发布和生产数据修复均待执行。
- automation gate 当前为开启状态；在 Hermes job 暂停且 backend automation gate 关闭前不得生成生产备份或触发重采。
- provider 是否能在本次窗口提供 `2026-10-16` 五指数同日证据尚未知；不能以授权代替数据日期证明。

## Next Step（下一步）

先提交并推送当前 reviewed code；随后按 writer freeze → backup/restore → deploy → same-date core refresh（仅一次 `--force --repair-integrity --dataset core`）→ readback → restore writers 的顺序执行生产步骤。
