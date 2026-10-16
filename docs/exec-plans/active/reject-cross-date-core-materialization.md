# 拒绝跨日期 core 快照与物化

## Stage（阶段）

离线实现与验证完成（OpenSpec `reject-cross-date-core-materialization`）。

## Status（状态）

complete-offline

## Scope（范围）

- 在 core 单指数归一化、同日留存、snapshot 提交和 materialized aggregate 替换处统一执行精确日期合同。
- 将存量 snapshot/materialized 完整性冲突映射为稳定、脱敏、provider-free 的 HTTP 503 `snapshot_integrity_error`。
- 前端不得把该完整性错误隐藏为 legacy 或跨日期成功结果；普通兼容 fallback 继续保留。
- 补充只读审计、受控前向修复和发布后业务 GET smoke 文档。
- 不执行真实 provider、生产 PostgreSQL 写入、部署、Secret/PVC、Hermes 或 Kubernetes 调度操作。

## Acceptance（验收）

- provider 只返回前一交易日 history 时，该指数为 date mismatch；四同日加一错日可形成同日 partial，五项均错日时按同日留存事实返回 `failed-retained` 或 `failed-missing`。
- 新写入的 snapshot key、payload/quality `asOf`、candidate actual date、core effective date 和各指数 history 尾日一致；兼容与 typed PostgreSQL 写路径都 fail closed。
- materialized aggregate 的实际兼容写路径与 typed CAS 都在替换前验证 key、payload 和组件日期，失败不推进 revision、不覆盖同日合法聚合。
- v2 与 legacy 对存量完整性冲突返回 HTTP 503 `snapshot_integrity_error`，不泄漏 SQL/checksum/path/provider payload，GET 的 provider/write/background-task 计数为零。
- dashboard 明确展示完整性错误，桌面与 390px 可读；普通非完整性 compatibility fallback 不回归。
- 后端/前端 focused 与 full tests、OpenSpec strict、规则门禁、架构门禁、docs-contract full 和 `git diff --check` 通过。

## Completion Evidence（完成证据）

- 2026-10-16：生产只读诊断已复现 `/api/v2/market-environment/2026-10-16/overview` 500 与 legacy core 503；日志定位为 materialized key `2026-10-16` 对应 payload `asOf=2026-10-15`。
- 2026-10-16：OpenSpec proposal、三份 delta specs、design、27 项 tasks 已完成，`openspec validate reject-cross-date-core-materialization --strict` 通过。
- 2026-10-16：新增纯 core 日期证据校验器并接入所有 history adapter、同日留存、fenced committer、compatibility/typed snapshot 与 aggregate 写入；错日失败保留 requested/actual date，合法 partial 保持请求日身份。
- 2026-10-16：v2 与 legacy 对本地完整性冲突稳定返回脱敏 503 `snapshot_integrity_error`；dashboard 明确展示且不发起 legacy fallback。只读审计仅执行 `SELECT`，隔离测试证明审计前后表行数不变。
- 2026-10-16：focused 后端命令覆盖 core acquisition/runtime/committer、snapshot、aggregate、v2/legacy，结果 `107 passed`；补充审计/架构/HTTP focused 结果 `35 passed`。dashboard focused 结果 `31 passed`，完整性错误 390px 渲染测试单文件 `5 passed`。
- 2026-10-16：`.venv/bin/python -m pytest tests -q` 结果 `1515 passed, 6 skipped`；skip 为既有环境条件跳过，无相关失败。`npm run test` 结果 `163 passed`；`npm run build` 成功，只有既有大 chunk warning。
- 2026-10-16：`.venv/bin/python -m src.trading_system.cli rules validate`、`rules coverage`、`docs sync-check`、`openspec validate reject-cross-date-core-materialization --strict`、`.venv/bin/python scripts/check-docs-contract.py --mode=full` 与 `git diff --check` 全部通过；docs-contract 报告 `代码 30 / 文档 6 / plan 1`。
- 2026-10-16：本 change 未执行真实 provider、生产 PostgreSQL 写入/修复、部署、Secret/PVC、Hermes、CronJob 或任何调度操作。

## Remaining Gaps（剩余缺口）

- 离线实现与门禁无剩余缺口。
- 生产现存错位记录不会由本 change 自动修复；部署、只读生产审计与数据前向修复仍需要独立 active plan、备份/停写证据和明确授权。

## Next Step（下一步）

归档本 OpenSpec change；如需上线，另建发布计划执行受审镜像部署和只读业务 GET smoke。如审计确认存量错位，再单独申请备份、writer freeze 与同日前向重采/重建授权。
