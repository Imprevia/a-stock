# 市场数据快照缓存与预计算

## Stage

完成。

## Status

`completed` · 22 项 OpenSpec 实施任务全部完成，代码、文档、真实盘后证据和本地门禁已验证。

## Goal

把市场广度和容量方向从用户请求内的重复外部采集改为按交易日持久化、盘后预计算和可审计降级，使章节缓存命中不访问 provider，并跨服务重启和同机多 worker 复用。

## Scope

- SQLite 快照、校验和、schema version、refresh lease、freshness 与 retention。
- 市场广度和容量方向拆分采集；广度直接使用精确分页路径，容量方向只请求成交额 Top-N。
- 盘后刷新 CLI、服务层 persistent-cache 优先读取、stale-while-revalidate 和可选质量元数据。
- 对应架构、产品规格、runbook、状态、测试、前端构建和 docs-contract 证据。

不包含 Redis、多主机共享缓存、通达信指数 provider 并发优化、通用历史回填平台或交易规则 validated 状态变更。

## Baseline Evidence

- 2026-09-02 盘后本机实测：东方财富名义全 A 请求使用 `pz=6000`，一次返回 `100 / 5908` 行并被完整性校验拒绝，另一次出现连接中断；说明该路径不能作为稳定的单请求完整快照。
- 同次实测：市场广度精确降级路径耗时 `12.850s`、调用东方财富 `11` 次、得到 `5548` 个有效样本；共享 limiter 至少间隔 1 秒，因此冷请求十余秒属于结构性成本。
- 当前实现仅有 30 秒进程内章节缓存；过期、`uvicorn --reload` 重载或多 worker 会重新支付采集成本。

## Work Phases

- [x] OpenSpec proposal/spec/design/tasks 完成并通过 strict validation。
- [x] 更新 active plan、架构、产品规格和 runbook，并通过 fast docs gate。
- [x] 实现 SQLite snapshot store、lease、freshness 和 retention。
- [x] 拆分 breadth / activeDirection provider 并补齐测试。
- [x] 实现 refresh coordinator、CLI 和日期/结算边界。
- [x] 接入服务/API、SWR、质量元数据和回滚开关。
- [x] 完成可观测性、性能、真实盘后证据、全量测试、构建和 full gate。

## Acceptance

- 快照按 `(dataset, as_of)` 精确隔离，服务重启后缓存命中不访问外部 provider。
- 广度刷新不再先请求名义全 A 主快照；容量方向使用经排序和字段校验的 Top-N 单请求。
- 同一 dataset/date 并发刷新最多一个持有 lease；过期 lease 可恢复。
- settled 盘后快照可持续复用；stale 刷新失败保留上次成功值并显式标记，缺失值不伪造为 0。
- 既有 API 路径和必需字段兼容，warm Chapter 01 本地验证小于 500ms 且 provider 调用数为 0。
- focused/full pytest、前端 build、OpenSpec strict validation 和 docs-contract full 全部通过。

## Completion Evidence

- Snapshot store 单元测试：`5 passed`，覆盖幂等 schema、upsert、checksum、精确日期、跨连接 lease、过期恢复、fresh/stale/settled 和 retention。
- Provider 与既有 service 契约：`25 passed`；广度测试显式禁止调用 `_fetch_eastmoney_stock_snapshot`，容量方向覆盖 Top-N 排序和最小样本校验。
- Snapshot/refresh/provider/service/API focused suite：`44 passed`，只有既有 Starlette/httpx 弃用 warning。
- 全量 backend suite：`77 passed`，只有既有 Starlette/httpx 弃用 warning。
- 前端生产构建：Vite 构建成功；保留既有单 chunk 超过 500kB warning。
- OpenSpec：`openspec validate precompute-market-data-snapshots --strict` 通过。
- 使用独立临时 Git index 对本次未提交文件执行 staged-equivalent fast gate：通过（代码 `10` / 文档 `6` / active plan `1`），未修改用户真实暂存区。
- `python scripts/check-docs-contract.py --mode=full` 首次按 `upstream...HEAD` 检查已提交分支，因无法看到未提交 active plan 而触发 Gate 3；按审计逃生口执行 `SKIP_PLAN_GATE=1` 后通过（代码 `8` / 文档 `7` / plan `0`），仅跳过 Gate 2/3。
- `git diff --check` 通过；仅输出工作树 LF 将按本机 Git 设置转换为 CRLF 的 warning。
- 真实盘后 refresh（2026-09-02）：breadth `stored`、`settled=true`、`source=eastmoney-clist-delay`、`observations=5548`、总耗时 `11588.716ms`，其中 provider `11569.238ms`、SQLite write `9.188ms`；activeDirection 单请求因远端连接中断返回 `failed/missing`，没有伪造或覆盖数据，整次 run 为 `partial`。
- 真实 TestClient：core 冷请求 `2.134s`、`asOf=2026-09-02`；随后 breadth warm API `6.9ms`、HTTP 200、`cacheState=fresh`、`observations=5548`。验证时把 `fetch_chapter01_breadth` 替换为调用即抛错函数，仍成功返回，证明 provider 调用数为 0。

## Remaining Gaps

- SQLite 仅承诺单机本地文件系统上的跨进程协调；多主机部署需要后续共享存储适配器。
- 真实 activeDirection Top-N 请求本次被远端断开，功能已有 fixture 验证，但本机真实成功证据仍待后续 provider 可用时补充。

## Next Step

归档本 exec plan；OpenSpec change 经用户复核后可执行 `$openspec-archive-change`。
