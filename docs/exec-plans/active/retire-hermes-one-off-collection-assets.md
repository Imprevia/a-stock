# 退役仓库内的一次性 Hermes 采集资产与配置记录

## Stage（阶段）

离线删除、文档收口与验证完成；未触碰运行时宿主上的实际调度配置。

## Status（状态）

completed-repo-retirement

## Scope（范围）

- 用户判定盘后采集调度配置属于一次性个人设置，不应作为仓库事实记录。
- 删除仓库内的一次性资产：两个外部 caller/prompt 脚本、三个专用测试、golden fixture、该 change 的 active plan 与 OpenSpec change 目录。
- 从 `docs/runbooks.md`、`docs/status.md`、`docs/repository-guide.md`、`README.md` 及其余 active plan 中删除一次性配置值（job ID、cron 表达式、投递目标、caller/prompt SHA-256、`next_run_at`、安装命令、本机路径）和相关历史段落。
- 保留后端机制事实：full endpoint、automation gate 默认关闭、持久幂等/结构化失败、上海日期与结算边界、Kubernetes 调度退役合同，以及 `docs/architecture.md` 与产品规格中的外部调度所有权描述。
- 明确不做：不修改运行时宿主上的 job、delivery、schedule 或已安装脚本；不暂停或删除该 job；不执行 provider、生产 PostgreSQL、部署或调度写操作。

## Acceptance（验收）

- 仓库不再包含具体一次性调度配置值：job ID、投递目标、cron 表达式、caller/prompt SHA-256、一次性 `next_run_at` 和安装路径/命令。
- 被删除资产在仓库内没有悬空引用：无测试、计划、OpenSpec 文档或代码映射仍指向这些文件或该 change。
- 后端 full endpoint、automation gate 与幂等合同文档保持可执行且自洽；`docs/architecture.md` 与产品规格的机制描述不被误删。
- `python -m pytest tests -q`、`python scripts/check-docs-contract.py --mode=full` 与 `git diff --check` 通过。
- 未发生任何运行时调度写入；宿主上的 job 配置保持不变。

## Completion Evidence（完成证据）

- 2026-10-26：删除 13 个一次性资产文件：两个 caller/prompt 脚本、三个专用测试、一个 golden fixture、原 active plan，以及原 OpenSpec change 的六个文件。
- 2026-10-26：移除部署清单测试对被删脚本的存在性依赖；该测试文件单独运行结果为 `151 passed`。
- 2026-10-26：仓库文本扫描确认无已删脚本路径、专用测试名、原 change 名、具体 job ID 或投递目标残留引用；OpenSpec change 列表不再包含已删 change。
- 2026-10-26：`.venv/bin/python -m pytest tests -q` 结果为 `1541 passed, 20 skipped, 1 warning`；warning 为既有 Starlette `BlockingPortal` 弃用提示。
- 2026-10-26：`openspec validate fix-ths-catalog-revision --strict`、市场环境架构门禁、rules validate、rules coverage、docs sync-check 均通过。
- 2026-10-26：`.venv/bin/python scripts/check-docs-contract.py --mode=full` 通过（代码 5 / 文档 19 / plan 9），`git diff --check` 通过。
- 2026-10-26：删除前后仅执行运行时调度器只读列表检查；目标 job 与另外两个无关 job 的 active 状态和配置未变，未执行 edit/pause/resume/remove/run。

## Remaining Gaps（剩余缺口）

- 运行时宿主上的 job 继续运行其已安装副本；仓库与其运行时副本自此不再有版本化对应关系，也不再有校验 SHA。
- 该 job 的安装、升级与回滚步骤随文档删除而不再受仓库管理；后续处置只能按用户明确指令执行。

## Next Step（下一步）

本次仓库退役已完成，无后续仓库动作。任何运行时调度变更或重新引入版本化 caller 资产都必须由用户重新明确授权并建立新计划。