# 个人交易盈亏日历

## Stage

本地实现与离线验收。契约见 OpenSpec `add-trading-pnl-calendar`。

## Status

`completed-local-only`（2026-11-28，OpenSpec 14/14，已归档）。

## Acceptance

- 侧栏可进入月历和独立日期明细。桌面和 390px 手机视口文字至少 14px，月历及录入页面无溢出。
- 手机截图经本地 OCR 生成可编辑草稿。用户逐行确认后入账，重复请求幂等，疑似重复可核对，部分成交和撤单按实际成交入账。
- 从 2026-01-20 收盘空仓起重建持仓，以 2026-01-21 为首个统计日。佣金万分之 2.5，每笔最低人民币 5 元。缺流水、会话、费用、收盘价或公司行动证据时展示缺项。
- 支持用有日期和来源的本地证据补齐，普通 GET 无外部 I/O 和数据库写入。按隔离 PostgreSQL、合成截图和固定估值贯通验收。

## Completion Evidence

- OpenSpec 四份规划文件齐备，严格校验已通过。
- 七条需求及验收场景已同步到 [盈亏日历主规格](../../../openspec/specs/trading-pnl-calendar/spec.md)，变更已移至 [OpenSpec 归档](../../../openspec/changes/archive/2026-11-28-add-trading-pnl-calendar/proposal.md)。
- 已登记产品规格、架构、运行手册和代码到文档映射。
- `TradingDayResolver` 可复用精确日及上一交易日验证。个股事实表可提供 `original_close`，仅在日期、证券身份和质量通过时采用。历史覆盖与公司行动独立核实，由本地 JSON 导入补齐缺口。
- Alembic 已在隔离 PostgreSQL 分两步执行 `upgrade 0008_collection_idempotency` 与 `upgrade head`。
- 个人台账测试覆盖本地中文 OCR、字段校验、截图到正式台账、事务回滚、并发重放、预览到期清理和历史复算。用户已提供的截图在本地只读 OCR 校验中提取到两笔有效交易，个人原图无入库或拷贝到仓库。
- Chromium 用合成图片和隔离 PostgreSQL 贯通上传、纠正、确认、首次盈亏估值、日期明细、返回月份和重传去重。390px 与 1440px 的三个页面测得最小文字为 14px，页面和日历格均无横向溢出。
- 涉及台账、HTTP、装配、发现、Alembic 与架构的后端回归 79 passed。前端 Vitest 174 passed，Vite build 通过。架构门禁、docs-contract full、OpenSpec strict、规则校验、覆盖清单和文档同步检查均通过。

## Remaining Gaps

- 全量 pytest 的收集受既有 `fuyao_client` 同名导入冲突阻断。市场环境与部署扩展回归为 1,479 passed、1 failed，失败项为旧 SQLite 到 PostgreSQL 迁移的 `snapshot_entries` checksum 核对，已在原始 `HEAD` 的独立目录复现。
- Podman 镜像构建完成前端阶段，运行阶段的 Debian 索引下载停滞，已停止构建。Debian 语言包清单、本地中文 OCR 和应用端到端链路已验证，整镜像构建验收待补。
- 个人历史流水、对应行情和公司行动的完整性尚未核实。生产迁移和部署待授权。

## Next Step

按运行手册在个人环境启动并设置期初。确认后分批补录历史交易和本地盘后证据。
