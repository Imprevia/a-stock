# 修复市场广度页数据可用性

## 目标

修复第 02 页在当日市场广度摘要完整时因 V2 历史查询失败而丢失上涨家数、下跌家数和中位数的问题；同时修复 PostgreSQL breadth/limits 历史查询的可选参数绑定，明确 60 个有效观察与 250 日窗口语义，并提供默认 dry-run、显式授权、精确日期且可审计的 breadth 历史维护入口。

## 范围

包含：OpenSpec `fix-breadth-page-data-availability` 的文档契约、PostgreSQL V2 历史读取、HTTP 契约、前端 summary/history 隔离与重试、60/250 覆盖口径、最近 5 日展示、受限历史维护 CLI、离线测试与只读本地 smoke。

排除：降低 60 个观察阈值、补零或跨日期替代、浏览器重算市场事实、普通 GET/页面加载触发采集、真实 provider probe、生产 PostgreSQL 回填、部署、Helm/Kubernetes/PVC/Secret 写操作。排除项必须取得单独明确授权。

## Stage（阶段）

- 当前阶段：**Stage 5 — 集成验证与交付**
- 阶段序列：执行计划与事实文档 → PostgreSQL 历史可靠性 → 前端隔离与历史语义 → 有界精确日期维护入口 → 集成验证与交付
- 本轮边界：完成 OpenSpec tasks 1.1–5.4 的仓库内实现、离线验证和本地只读 smoke；不执行真实 provider、生产写入、部署或生产回填。

## Status（状态）

`completed` · OpenSpec 规划产物 4/4 完成，实施任务 20/20；后端读取、前端隔离、有界 breadth 历史维护入口和 seeded PostgreSQL 只读 API smoke 均已完成。

## 事实源

- `openspec/changes/fix-breadth-page-data-availability/`
- `docs/product-specs/market-environment-dashboard.md`
- `docs/architecture.md`
- `docs/repository-guide.md`
- `docs/runbooks.md`
- `docs/status.md`

## 预期代码归属

- PostgreSQL V2 历史查询：`src/market_environment/infrastructure/persistence/postgres/v2_market_data.py`
- V2 query/router 与 HTTP 契约：`src/market_environment/` 对应 application/query、API router 和测试
- breadth 历史维护：既有 acquisition/coordinator/lease/fencing/committer/audit 链路与 CLI 入口
- 前端状态和页面：`apps/market-environment-dashboard/src/stores/market.ts` 及第 02 页组件/测试
- 后端与契约测试：`tests/`；前端测试：`apps/market-environment-dashboard/src/**/*.test.*`

## 阶段任务

- [x] 建立 active plan、登记索引并通过 fast docs-contract
- [x] 更新 architecture、产品规格、runbook 和 repository guide 的实施前契约
- [x] 修复 breadth/limits PostgreSQL 历史查询并补充 adapter/HTTP/integrity 测试
- [x] 拆分前端 summary/history 状态、409 group restart、60/250 元数据和最近 5 日展示
- [x] 实现默认 dry-run、有限预算、显式授权、精确日期的 breadth 历史维护 CLI
- [x] 完成 targeted/full backend、frontend、架构、规则、OpenSpec、docs-contract 和本地只读 smoke 验证
- [x] 更新状态与交付证据，明确所有未授权生产动作仍未执行

## Acceptance（验收）

- breadth/limits history 在省略任意可选日期或 cursor 参数时不产生 PostgreSQL 未类型化 `NULL` 错误，分页按精确日期升序、有界且无重复。
- 普通 V2 GET 只读本地证据，provider 调用计数和数据库写入计数均为零；无合法本地请求因可选参数绑定返回 500。
- breadth summary 成功而 history 失败时，当日上涨/下跌/平盘/有效家数、中位数、宽度标签和质量保留，其它 V2 资源不被全局关闭；history 可单独重试。
- history 409 会重新读取 overview、summary 和 history，任何可见状态不混合不同 revision。
- 历史元数据使用真实唯一观察数、`requiredObservations=60`、`windowDays=250`、有界 coverage；只展示最近 5 日，少于 60 日保持 `insufficient` 和空分位。
- 历史维护入口默认 dry-run、预算有界、逐日独立、只接受精确交易日证据；apply 必须显式授权且复用既有采集、lease/fencing、committer 和 audit 链路，不含直接快照 SQL。
- 后端、前端、架构、规则、OpenSpec 与 docs-contract 检查通过；无法运行的检查如实记录为 Remaining Gap。

## Completion Evidence（完成证据）

- 2026-10-20：`openspec validate fix-breadth-page-data-availability --strict` 通过；apply 指令确认 schema 为 `spec-driven`、规划产物 4/4，实施任务已完成 20/20。
- 2026-10-20：`.venv/bin/python scripts/check-docs-contract.py --mode=fast` 通过；Gate 4 扫描 active plans 并确认必需字段完整。系统未提供裸 `python` 命令，因此后续验证统一使用仓库虚拟环境解释器。
- 2026-10-20：已在 architecture、dashboard 产品规格、runbook 和 repository guide 固化条件式 typed history predicate、summary/history 独立提交、60/250/最近 5 日语义和生产回填未授权边界；repository guide 已覆盖 PostgreSQL adapter、query/router、前端 store/page、维护 CLI/collection/materialization 与两端测试路径。`git diff --check` 和 fast docs-contract 通过。
- 2026-10-20：`.venv/bin/python -m pytest tests/test_market_environment_v2_read_adapters.py -q` 通过（11 passed）；breadth/limits 首页不再生成 absent optional bind，单边/双边/cursor 只绑定非空 `DATE`，排序和 `limit + 1` 保持不变。
- 2026-10-20：使用一次性本地 Podman PostgreSQL 16.4 运行 `MARKET_ENVIRONMENT_TEST_DATABASE_URL=<isolated-local-postgres> .venv/bin/python -m pytest tests/test_market_environment_v2_postgres_history.py tests/test_market_environment_v2_read_adapters.py -q`，23 passed。真实矩阵覆盖 breadth/limits 无筛选、单起点、单终点、双边界、空结果和 continuation，另修复 schema 为整数时 `session.is_session=TRUE` 的 PostgreSQL 类型错误为 `=1`；临时容器已停止并自动删除。
- 2026-10-20：`.venv/bin/python -m pytest tests/test_market_environment_v2_read_adapters.py tests/test_market_environment_v2_contract.py tests/test_market_environment_v2_resources.py -q` 通过（29 passed）；HTTP breadth/limits 首页和续页保持同 revision，stale revision 为 409，改筛选/跨资源 cursor 为 422，provider/write counters 为 0。
- 2026-10-20：历史 SQL 改为选择完整 snapshot row，并复用 `PostgresSnapshotRepository.candidate_from_row` 校验 checksum、schema version 和 exact date；一次性 PostgreSQL 16.4 的 integrity 矩阵 14 passed，HTTP 坏证据返回脱敏 503 `snapshot_integrity_error`，临时容器已停止并自动删除。
- 2026-10-20：前端 breadth summary/history 已拆为独立提交与状态；history 失败保留 summary 和全局 V2，支持 history-only retry；history 409 清空旧 breadth group 后重读 overview/summary/history。元数据固定为真实唯一观察、60/250 和最后 5 点，少于 60 保持 `insufficient`。
- 2026-10-20：`apps/market-environment-dashboard/` 的 `npm run test` 通过（24 files / 172 tests），`npm run build` 成功（2191 modules；仅保留既有 chunk >500 kB 提示）。第 02 页覆盖 loading/error/insufficient、重试、summary 保留、0/26/65 点、integrity、409、桌面与 390px 无页面级溢出回归。
- 2026-10-20：新增 `BreadthHistoryMaintenanceRequest/Result/Service` 与 `snapshots breadth-history` CLI；显式日期或闭区间交易日二选一，单次最多 20 日，默认 dry-run，`--apply` 必须同时提供 `--allow-real-provider` 与 `--allow-snapshot-writes`，拒绝发生在 provider I/O 前。逐日复用 coordinator 的 breadth acquisition plan、TDX exact-date/universe 校验、typed committer、lease/fencing、task/run audit；失败分类为 retained/unavailable/failed，成功日期只触发已存 250-session 窗口相关 aggregate 的升序有界重建。新增维护 fixture 5 项测试；与 bootstrap、compatibility、refresh 回归合计 29 passed，架构门禁、fast docs-contract 和 OpenSpec strict 通过。
- 2026-10-20：`.venv/bin/python -m pytest tests -q` 通过（1575 passed, 20 skipped）；`.venv/bin/python scripts/check_market_environment_architecture.py` 通过；规则 `validate` 输出 49 条、`coverage` 输出 documented 330/executable 49、`docs sync-check` 通过；前端 `npm run test` 通过（24 files / 172 tests），`npm run build` 成功（2191 modules，仅既有 chunk >500 kB 提示）；`openspec validate ... --strict` 与 `scripts/check-docs-contract.py --mode=full` 通过（代码 21 / 文档 6 / plan 1）。
- 2026-10-20：早期环境缺少 `MARKET_ENVIRONMENT_TEST_DATABASE_URL` 的阻塞已通过新增一次性本地 seed fixture 解除；最终 smoke 证据见下一条记录。
- 2026-10-20：新增 `scripts/seed_market_environment_smoke.py`，仅接受显式 PostgreSQL URL 或 `MARKET_ENVIRONMENT_TEST_DATABASE_URL`，通过 `create_schema` 与 typed snapshot store 幂等写入 5 个精确交易日、breadth/limits 历史、当前 core 快照和合法 checksum/schema-version/exact-date aggregate；不触发 provider、task 或 lease。使用隔离 Podman PostgreSQL `postgres:16.4`（`127.0.0.1:55433`）完成真实 `create_app()` 只读 smoke：overview、breadth、breadth history 首页/续页、limits history、legacy compatibility 全部 HTTP 200；breadth 首页 `[2026-09-01, 2026-09-02]` 与续页 `[2026-09-03, 2026-09-04]` 无重复；请求前后 snapshot/aggregate/run/task/lease/write 计数不变。临时容器已停止并删除，未连接任何现有或生产容器。

## Remaining Gaps（剩余缺口）

- 无待完成的 OpenSpec 集成验证任务；5.3 seeded PostgreSQL smoke 与 5.4 状态交付均已完成。
- seeded PostgreSQL smoke 仅使用一次性本地 Podman 数据库和本地 fixture；未执行任何生产 provider、生产写入、部署或回填操作。
- 当前生产 breadth 历史仅有部分精确交易日，少于 60 个观察时分位继续保持 `insufficient`；本任务不以降低阈值绕过证据不足。
- 真实 provider probe、生产 snapshot 写入/回填、部署及任何 Kubernetes/Helm/PVC/Secret 操作未获授权且不会执行。
- 工作树含用户或其他 change 的未跟踪内容；本计划不清理、不覆盖无关改动。

## Next Step（下一步）

完成本 change 的归档前检查；如需保留实现记录，可运行 `openspec archive fix-breadth-page-data-availability`，不得将本地 seed URL 用作生产配置。
