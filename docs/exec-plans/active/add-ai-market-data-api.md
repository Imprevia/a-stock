# 面向 AI 的细粒度市场数据只读 API

## Stage

实现与离线验收收尾（OpenSpec `add-ai-market-data-api`）

## Status

`complete` · 后端 v2 资源树、AI discovery、legacy 兼容护栏、dashboard 渐进迁移与离线门禁已完成；OpenSpec 34/34。真实 Chromium 截图在当前容器因 NetworkService/DBus 崩溃无法运行，已由可复现的 390px DOM 回归与构建证据替代并记录。

## Acceptance

- 保留现有未版本化 aggregate、core、Chapter 01、next-session、collection 与 THS 路径、字段和可观察行为；新能力只新增在 `/api/v2/market-environment`、`/llms.txt` 和 `/llms-full.txt`。
- AI 客户端先读取 exact-date overview，再按需读取指数、广度、涨跌停、板块、容量方向、事件、评估或 operation 子资源；资源 DTO 不复用完整 `MarketEnvironmentResponse` / `Chapter01Response`，也不夹带兄弟资源。
- 所有 v2 响应具有 `asOf`、`generatedAt`、opaque `snapshotRevision`、`quality`、`data`、`links`；集合另有服务端上限、确定性排序和 revision-bound opaque cursor。
- 所有 v2 GET 与发现文档只读本地精确日期事实，provider 构造/调用、采集 join/start、后台任务和 PostgreSQL 写入均为零；缺失保持 `null` / `missing` / `insufficient`，不跨日期补齐。
- overview revision 可通过 ETag/前置条件固定后续读取；不匹配与 stale cursor 返回稳定 409，匹配 `If-None-Match` 返回 304。
- `/llms.txt` 与 `/llms-full.txt` 从受控语义和 tagged OpenAPI 内存渲染，不写运行时文件、不嵌入实时行情行、凭据、provider header、presigned URL 或私有 revision metadata。
- PostgreSQL 可变列表在查询层先 filter/order/limit 再物化；前端按页面渐进迁移、保留 legacy fallback，并把 THS bars 单页上限从 1500 修正到 1000 后续页。
- 后端与前端 focused/full 离线测试、OpenAPI/discovery drift、桌面与 390px、OpenSpec strict、规则门禁、docs-contract full 和 `git diff --check` 均通过；不运行真实 provider、生产 endpoint、数据库或部署写操作。

## Facts and Baseline

- 已测 legacy 完整聚合 JSON 样本约 `174–185 KB`；其中 `indices` 约 `64 KB`，`limits` 约 `78–85 KB`。体量主要来自指数历史、涨跌停证券行及历史点。
- `GET /api/market-environment/chapter-01?section=...` 当前只校验 `section`，仍返回完整累计 Chapter 01；这是 legacy compatibility baseline，不是 v2 的目标响应形态。
- limits 证券池、指数历史、板块 rows 与 operation checkpoints 缺少 AI 上下文友好的服务端边界；现有 THS catalog/bars 分页仅作为既有可链接契约。
- 前端当前请求 THS bars 的 `page_size=1500`，高于后端最大 1000，可能返回 422；迁移阶段必须改为不超过 1000 并正确续页。

## Scope and Implementation Stages

1. 冻结 legacy characterization 与先失败的 v2 contract：隔离资源、exact-date、closed selector、集合上限、revision 冲突、零 provider/写调用。
2. 建立专用 v2 envelope/quality/link/pagination/error DTO、opaque revision/ETag、cursor、typed read ports 与 PostgreSQL bounded adapters，再由 composition root 注册 additive router。
3. 依次交付 overview/indices、breadth/limits、sectors/conclusions、operation summary/checkpoints；同 revision 的重叠标量和质量必须与 legacy 本地事实一致。
4. 以 tagged OpenAPI + 受控产品/runbook 语义实现纯内存 discovery renderer，并以确定性 drift/security tests 固定输出。
5. 看板逐页切到 v2 并保留 legacy fallback，最后执行全量离线验证和计划收尾。

本计划不扩展交易知识 MCP，不新增 authentication、写 API、任意字段投影、GraphQL/SQL 接口、数据库 migration、provider 优先级、采集/调度、部署拓扑或生产操作。

## Completion Evidence

- `openspec validate add-ai-market-data-api --strict`：规划阶段已通过。
- 2026-10-16：产品规格、架构、仓库代码—文档映射、runbook 与本 active plan 已先于业务代码更新，记录 v2 资源树、provider-free、revision/cursor、discovery、legacy compatibility 与 rollback 边界。
- `python scripts/check-docs-contract.py --mode=fast`：当前 shell 无全局 `python` 命令，返回 127；仓库解释器 `.venv/bin/python scripts/check-docs-contract.py --mode=fast` 与系统 `python3` 均通过（fast 模式没有 staged diff，报告代码/文档/plan 0；Gate 4 仍扫描全部 active plan，新增计划六个必需字段完整）。
- `git diff --check -- docs/exec-plans/active/add-ai-market-data-api.md docs/exec-plans/active/_index.md docs/product-specs/market-environment-dashboard.md docs/architecture.md docs/repository-guide.md docs/runbooks.md openspec/changes/add-ai-market-data-api/tasks.md`：通过。
- 后端 focused：`.venv/bin/python -m pytest tests/test_market_environment_v2_contract.py tests/test_market_environment_v2_resources.py tests/test_market_environment_v2_shared_contracts.py tests/test_market_environment_v2_queries.py tests/test_market_environment_v2_read_adapters.py tests/test_market_environment_discovery.py tests/test_market_environment_legacy_read_characterization.py tests/test_market_environment_api.py tests/test_market_environment_bootstrap.py -q` → `85 passed, 1 warning`（Starlette TestClient deprecation warning）。
- 后端全量：`.venv/bin/python -m pytest tests -q` → `1496 passed, 6 skipped, 1 warning`（同一 Starlette TestClient deprecation warning）。
- 前端全量：`npm run test` → `24 files / 161 tests passed`；`npm run build` → 成功，仅有既有产物 chunk >500KB 提示。
- 前端视口回归：`npm run test -- --run src/breadth-page.test.ts src/limits-page.test.ts src/data-collection-view.test.ts` → `3 files / 24 tests passed`，覆盖 390px 页面级溢出、表格局部滚动、分页/空态/错误态。
- 浏览器 smoke：已用构建产物和本地夹具尝试 Chromium 桌面与 390px 截图；容器浏览器因 NetworkService/DBus 崩溃/超时退出，未生成截图，未将该尝试计为成功。
- 规则与文档门禁：`rules validate` → `{"ruleSets":1,"rules":49}`；`rules coverage` 与 `docs sync-check` → `{"documentedRules":330,"executableRules":49}`；`openspec validate ... --strict` 通过；`check-docs-contract.py --mode=full` → `通过（代码 102 / 文档 13 / plan 4）`；`git diff --check` 通过。
- 已实现专用 v2 DTO、opaque revision/ETag/cursor、provider-free read port、PostgreSQL bounded adapters、19 个资源端点、`/llms.txt`/`/llms-full.txt`、THS bars 最大 1000 的自动续页，以及 legacy characterization；所有已完成任务均已同步勾选。

## Remaining Gaps

- 真实 Chromium 截图 smoke 受当前容器 NetworkService/DBus 运行时限制，待具备稳定浏览器运行时后补做；代码级 390px DOM 回归、全量 Vitest 与构建已通过。
- legacy 大响应会在迁移期间刻意保留；MCP 与 application authentication 明确不在本 change 范围。

## Next Step

OpenSpec change 已归档；后续若补做真实浏览器 smoke，仅更新本计划的 Completion Evidence/Remaining Gaps，不改变已发布的 legacy 兼容与 v2 只读边界。
