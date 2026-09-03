# 盘后市场数据定时采集

## Stage（阶段）

实现部署内盘后调度、CLI 边界、失败隔离和运维验证。

## Status（状态）

`completed` · OpenSpec change `schedule-after-market-data-collection` 的 28 项任务已全部完成。

## Goal（目标）

让 k3s/Helm 部署在上海时区工作日盘后自动采集 `core`、`breadth`、`limits`、`sectors` 和 `activeDirection`，复用现有 collection coordinator 和 SQLite 持久卷；任一数据集失败不得阻止其他成功结果保存，结果继续通过 `/data-collection` 查看和补采。

## Scope（范围）

- 新增内部解析上海日期和结算边界的 `snapshots scheduled-refresh` CLI。
- 新增 k3s Kustomize 与 Helm CronJob，默认工作日 16:30、禁止重叠、禁止整批自动重试。
- 复用现有五类独立 collection task、精确日期校验、lease、失败保留和 materialized aggregate。
- 更新产品规格、架构、runbook、状态和部署教程。
- 增加 CLI、并发、失败隔离、Kustomize、Helm 和 docs-contract 验证。

不包含 APScheduler、Celery、Redis、多节点 SQLite、完整认证或交易所节假日日历。

## Work Phases（工作阶段）

- [x] OpenSpec proposal、design、spec 和 tasks 已创建并通过 strict validation。
- [x] 事实源文档与 active plan 更新。
- [x] scheduled-refresh CLI 与测试实现。
- [x] Kustomize CronJob 实现与渲染验证。
- [x] Helm CronJob、values 与渲染验证。
- [x] 全量测试、OpenSpec、docs-contract 和完成证据更新。

## Acceptance（验收）

- 默认调度为 `Asia/Shanghai` 工作日 16:30，支持关闭、暂停和覆盖 schedule/timezone。
- scheduled-refresh 在周末不调用 provider，结算前拒绝运行，有效时间默认覆盖五类数据。
- 单项失败时其他成功结果独立落盘，父批次为 `partial`，且不自动重新执行整批。
- CronJob 与手工触发重叠时由 CronJob `Forbid` 和 SQLite dataset/date lease 防止重复调用。
- CronJob 使用与 Dashboard 相同镜像、PVC、SQLite 路径、非 root 和只读根文件系统安全边界。
- `/data-collection` 能从本地 SQLite 查看定时运行结果，普通 GET 在采集中仍不访问 provider。
- focused/full pytest、Kustomize、Helm、OpenSpec strict、docs-contract full 和 whitespace 检查通过。

## Completion Evidence（完成证据）

- CLI/collection focused：`.venv\Scripts\python.exe -m pytest tests/test_market_environment_collection.py tests/test_market_environment_service.py -q`，`36 passed`。
- 部署测试：临时 Helm `v3.17.3` 与 kubectl `v1.37.0` 下，`tests/test_deployment_manifests.py` 为 `5 passed`。
- 全量后端：`.venv\Scripts\python.exe -m pytest tests -q`，`117 passed, 3 skipped`；3 个 skip 是普通进程未设置 Helm/kubectl 路径，已由上述真实工具运行覆盖。
- Kustomize：`kubectl kustomize deploy/k3s` 通过。
- Helm：`helm lint deploy/helm/a-stock` 为 `1 chart(s) linted, 0 chart(s) failed`；默认、disabled、suspended/custom schedule 三组 template 通过。
- OpenSpec：`openspec validate schedule-after-market-data-collection --strict` 通过。
- 文档门禁：`.venv\Scripts\python.exe scripts/check-docs-contract.py --mode=full` 通过（代码 15 / 文档 7 / plan 1）。
- 代码差异：`git diff --check` 无 whitespace error，仅有工作区 CRLF 转换提示。

## Remaining Gaps（剩余缺口）

- 第一版不引入权威交易所节假日日历；周一至周五节假日仍会触发，但精确日期校验必须阻止跨日期数据写入。
- 当前 SQLite 与 ReadWriteOnce PVC 仅支持既有单节点、单副本边界，多节点协调另行设计。
- 当前工作区包含前序市场数据管理功能的未提交改动，本计划在其基础上增量实现且不回退。
- 本次没有连接真实 k3s 集群执行 server-side dry-run 或创建真实 Job；已完成本地 Kustomize/Helm 真实渲染，部署时应先 suspend 并手工补跑一次验证 PVC 与外网。

## Next Step（下一步）

归档 OpenSpec change；首次目标集群部署时先保持 CronJob suspend，创建一次性 Job 验证 SQLite PVC、provider 外网和 JSON 日志后再恢复调度。
